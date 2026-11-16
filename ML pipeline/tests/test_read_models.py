"""Phase 9 canonical read projections, authorization and external HTTP consumers."""
from datetime import timedelta
import os
import socket
import subprocess
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from src.daycover import auth, read_models, settlement, evidence_engine as engine, billing
from src.daycover.api import app
from test_settlement import setup, queued, rows
from test_evidence_engine import DAY, NOW, weather


def principal(repo, pid, role='customer'):
    return auth.Principal(pid, role, frozenset({'coverage:read'}), 'test-fixture')


def grant(repo, pid, merchant):
    auth.set_grant(pid,merchant)


def prepared(repo):
    owner,reviewer,service,p,tid,rid,oid=setup(repo)
    grant(repo,owner,p['merchant_id']);grant(repo,reviewer,p['merchant_id']);grant(repo,service,p['merchant_id'])
    return owner,reviewer,service,p,tid,rid,oid


def view(repo,owner,tid,**kwargs):
    return read_models.snapshot('HC076',tid,DAY,principal(repo,owner),repo,now=NOW,**kwargs)


def test_read_view_has_one_authority_and_does_not_write(ledger_backend):
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    before={t:rows(repo,t) for t in ('pilot_audit','engine_decisions','weather_evidence_selections','billing_bills','settlement_instructions')}
    v=view(repo,owner,tid)
    assert v['schema_version']=='daycover.part2.v1'
    assert v['identity']['merchant_id']==p['merchant_id']
    assert v['policy']['term_id']==tid and v['policy']['period_id']==v['settlement']['period_id']
    assert v['policy']['contract_sha256']==v['weather']['contract_sha256']
    assert v['coverage']['remaining']=={'rain_events':1,'rain_cents':3000,'haze_days':4,'haze_cents':9000,'combined_cents':12000}
    assert v['settlement']['summary']['net_entitlement_cents']==6000
    assert v['settlement']['summary']['confirmed_mock_cents']==0
    assert v['billing']['summary']['annual_obligation_cents']==10400 and not v['billing']['prepared']
    assert not v['boundaries']['rain_timing_verified'] and v['boundaries']['real_paid_cents']==0
    assert v['source_reviews'] and not v['weather']['persisted']
    assert view(repo,owner,tid)['state_sha256']==v['state_sha256']
    assert {t:rows(repo,t) for t in before}==before


def test_confirmation_and_reversal_project_net_mock_only(ledger_backend):
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    iid=queued(repo,tid,rid,oid,service,scenario='reversal')
    settlement.dispatch('HC076',tid,iid,service,repo,now=NOW)
    assert view(repo,owner,tid)['settlement']['summary']['reserved_cents']==6000
    settlement.reconcile('HC076',tid,iid,repo,now=NOW)
    v=view(repo,owner,tid)
    assert v['settlement']['summary']['confirmed_mock_cents']==6000 and len(v['receipts'])==1
    settlement.reconcile('HC076',tid,iid,repo,now=NOW)
    v=view(repo,owner,tid)
    assert v['settlement']['summary']['confirmed_mock_cents']==0 and len(v['receipts'])==2
    assert v['coverage']['remaining']['combined_cents']==12000
    assert v['boundaries']['real_paid_cents']==0


def test_current_source_change_marks_historical_decision_stale(ledger_backend):
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    assert next(d for d in view(repo,owner,tid)['decisions'] if d['peril']=='haze')['current_context_matches']
    weather(repo,reviewer,p,DAY,20,resolve=True,now=NOW+timedelta(hours=1))
    v=view(repo,owner,tid)
    assert not next(d for d in v['decisions'] if d['peril']=='haze')['current_context_matches']
    assert v['settlement']['review_required']
    assert v['settlement']['summary']['confirmed_mock_cents']==0


def test_operations_queue_is_scoped_and_never_grants_write(ledger_backend):
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    queued(repo,tid,rid,oid,service,scenario='timeout')
    with pytest.raises(Exception) as exc:view(repo,owner,tid,operations=True)
    assert exc.value.status_code==403
    v=read_models.snapshot('HC076',tid,DAY,principal(repo,reviewer,'reviewer'),repo,now=NOW,operations=True)
    assert v['operations']['source_gaps'] and v['operations']['pending_decisions']
    assert len(v['operations']['reconciliation_queue'])==1
    assert v['operations']['lifecycle_events']
    stranger=auth.provision('view_stranger','customer','local-stranger-password')
    with pytest.raises(Exception) as exc:view(repo,stranger,tid)
    assert exc.value.status_code==404


def test_term_binding_dates_and_auth_errors(ledger_backend):
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    token=auth.login('settlement_owner','local-owner-test-password')['access_token']
    client=TestClient(app);url=f'/api/v1/read-models/stalls/HC076/terms/{tid}'
    headers={'Authorization':'Bearer '+token}
    assert client.get(url,params={'day':str(DAY)}).status_code==401
    assert client.get(url,params={'day':'bad'},headers=headers).status_code==422
    assert client.get(url,params={'day':str(DAY-timedelta(days=1))},headers=headers).status_code==409
    assert client.get(url.replace(tid,'foreign-term'),params={'day':str(DAY)},headers=headers).status_code==404
    assert client.post(url,headers=headers).status_code==405
    response=client.get(url,params={'day':str(DAY)},headers=headers)
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    assert client.get('/api/v1/read-models/stalls/HC076/terms',headers=headers).json()['terms'][0]['term_id']==tid
    auth.disable(owner)
    assert client.get(url,params={'day':str(DAY)},headers=headers).status_code==401


def test_no_evaluation_and_closed_day_are_honest(ledger_backend):
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    next_day=DAY+timedelta(days=1)
    v=read_models.snapshot('HC076',tid,next_day,principal(repo,owner),repo,now=NOW)
    assert all(d['status']=='NOT_EVALUATED' for d in v['decisions'])
    weather(repo,reviewer,p,next_day,151,closed=True)
    engine.evaluate('HC076',next_day,next_day,repo,now=NOW)
    v=read_models.snapshot('HC076',tid,next_day,principal(repo,owner),repo,now=NOW)
    assert all(d['status']!='TRIGGERED' for d in v['decisions'])
    assert v['coverage']['remaining']['combined_cents']==12000


def test_http_consumer_retry_and_expiry(ledger_backend):
    repo=ledger_backend
    owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    token=auth.login('settlement_owner','local-owner-test-password')['access_token']
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=os.environ.copy();env['DAYCOVER_AUTH_MODE']='local'
    process=subprocess.Popen(['.venv/bin/python','-m','uvicorn','src.daycover.api:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=5) as client:
            for _ in range(100):
                try:
                    if client.get('/api/v1/ledger/health').status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.05)
            else:pytest.fail('Local HTTP server did not become ready')
            url=f'/api/v1/read-models/stalls/HC076/terms/{tid}?day={DAY}'
            headers={'Authorization':'Bearer '+token}
            first=client.get(url,headers=headers);assert first.status_code==200,first.text
            assert client.get(url,headers=headers).json()['state_sha256']==first.json()['state_sha256']
            class OneTimeout(httpx.BaseTransport):
                def __init__(self):self.first=True;self.delegate=httpx.HTTPTransport()
                def handle_request(self,request):
                    if self.first:
                        self.first=False
                        raise httpx.ReadTimeout('Injected client timeout',request=request)
                    return self.delegate.handle_request(request)
                def close(self):self.delegate.close()
            with httpx.Client(transport=OneTimeout(),timeout=5) as retrying:
                address=f'http://127.0.0.1:{port}'+url
                with pytest.raises(httpx.ReadTimeout):retrying.get(address,headers=headers)
                assert retrying.get(address,headers=headers).json()['state_sha256']==first.json()['state_sha256']
            assert not rows(repo,'settlement_instructions')
            with repo.transaction() as c:c.execute('UPDATE auth_credentials SET expires_at=0 WHERE principal_id=?',(owner,))
            assert client.get(url,headers=headers).status_code==401
    finally:
        process.terminate();process.wait(timeout=10)


def test_billing_status_remains_separate_from_benefit(ledger_backend):
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    statement=billing.prepare('HC076',tid,repo,now=NOW)
    billing.authorize('HC076',tid,owner,'grant',repo,now=NOW)
    attempt=billing.create_attempt('HC076',tid,statement['bills'][0]['id'],'read-view-bill','success',service,repo,now=NOW)
    billing.submit('HC076',tid,attempt['attempt_id'],repo,now=NOW)
    assert view(repo,owner,tid)['billing']['summary']['collected_cents']==0
    billing.reconcile('HC076',tid,attempt['attempt_id'],repo,now=NOW)
    v=view(repo,owner,tid)
    assert v['billing']['summary']['collected_cents']==867
    assert v['settlement']['summary']['confirmed_mock_cents']==0
    assert v['coverage']['remaining']['combined_cents']==12000


def test_service_scope_revoked_grant_and_503_contract(ledger_backend,monkeypatch):
    from src.daycover.ledger_repository import LedgerUnavailable
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    token=auth.issue_service(service,['decision:evaluate'])['access_token']
    client=TestClient(app);url=f'/api/v1/read-models/stalls/HC076/terms/{tid}?day={DAY}'
    assert client.get(url,headers={'Authorization':'Bearer '+token}).status_code==403
    token=auth.issue_service(service,['coverage:read'])['access_token'];headers={'Authorization':'Bearer '+token}
    assert client.get(url,headers=headers).status_code==200
    auth.set_grant(service,p['merchant_id'],False)
    assert client.get(url,headers=headers).status_code==404
    auth.set_grant(service,p['merchant_id'])
    def unavailable():raise LedgerUnavailable('fixture unavailable')
    monkeypatch.setattr(read_models,'configured_repository',unavailable)
    response=client.get(url,headers=headers)
    assert response.status_code==503
    assert 'fixture' not in response.text


def test_openapi_publishes_versioned_read_only_contract():
    spec=app.openapi();path='/api/v1/read-models/stalls/{stall}/terms/{term_id}'
    assert set(spec['paths'][path])=={'get'}
    assert spec['components']['schemas']['Snapshot']['properties']['schema_version']['const']=='daycover.part2.v1'
    assert spec['components']['schemas']['Remaining']['properties']['combined_cents']['type']=='integer'


def test_renewal_projects_selected_period_without_prior_year_balances(ledger_backend):
    from src.daycover import policy_lifecycle as life
    from src.daycover.contracts import M1_VERSION
    repo=ledger_backend;owner,reviewer,service,p,tid,rid,oid=prepared(repo)
    next_start=DAY.replace(year=DAY.year+1)
    life.renew('HC076',next_start,M1_VERSION,repo,now=NOW)
    directory=read_models.terms('HC076',principal(repo,owner),repo,now=NOW)
    renewed=next(t for t in directory['terms'] if t['start']==str(next_start))
    v=read_models.snapshot('HC076',renewed['term_id'],next_start,principal(repo,owner),repo,now=NOW)
    assert v['policy']['state']=='NOT_STARTED'
    assert v['coverage']['remaining']['combined_cents']==18000
    assert v['settlement']['summary']['net_entitlement_cents']==0
    assert not v['receipts']
    old=read_models.snapshot('HC076',tid,DAY,principal(repo,owner),repo,now=NOW.replace(year=NOW.year+1))
    assert old['policy']['state']=='EXPIRED' and old['policy']['event_day_state']=='ACTIVE_SIMULATION'
    assert old['coverage']['remaining']['combined_cents']==12000
