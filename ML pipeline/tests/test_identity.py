"""Actual HTTP security boundary and both SQL backends, not mocked authorization."""
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from src.daycover.api import app
from src.daycover import auth, identity_api, pilot_store
from src.daycover.contracts import M1_VERSION
from src.daycover.ledger_repository import configured_repository, SqlLedgerRepository, MIGRATIONS

client=TestClient(app)
PASSWORD='local-test-password-only'


@pytest.fixture(autouse=True)
def secure_mode(monkeypatch):
    monkeypatch.setenv('DAYCOVER_AUTH_MODE','local')


def user(alias='merchant_one',role='customer'):
    pid=auth.provision(alias,role,None if role=='service' else PASSWORD)
    if role=='service':
        token=auth.issue_service(pid,sorted(auth.ROLES[role]))['access_token']
    else:
        result=client.post('/api/v1/auth/login',json={'alias':alias,'password':PASSWORD})
        assert result.status_code==200,result.text
        token=result.json()['access_token']
    return pid,{'Authorization':'Bearer '+token}


def body(ref='stall-one',**changes):
    s=identity_api.CENTRES['HC076']
    return dict(centre_id=s.id,latitude=s.lat,longitude=s.lon,external_namespace='wallet_sandbox',
                external_ref=ref,licence_ref='licence-'+ref,evidence_sha256=hashlib.sha256(ref.encode()).hexdigest(),
                accepted_version=M1_VERSION) | changes


def onboarding(headers,ref='stall-one'):
    response=client.post('/api/v1/onboarding',json=body(ref),headers=headers)
    assert response.status_code==200,response.text
    return response.json()


def approve(row,headers,alias='reviewer_one'):
    reviewer,rh=user(alias,'reviewer')
    auth.set_grant(reviewer,row['merchant_id'])
    response=client.post('/api/v1/onboarding/'+row['stall_id']+'/review',json={'status':'eligible_simulation','reason':'local_evidence_checked'},headers=rh)
    assert response.status_code==200,response.text
    return rh


def enrol(row,headers):
    return client.post('/api/v1/policies',json={'stall_id':row['stall_id'],'accepted_version':M1_VERSION,'consent':True},headers=headers)


# Same complete onboarding -> accepted contract -> deterministic simulated receipt on SQLite/Postgres.
def test_no_sales_fixed_cover_end_to_end(ledger_backend):
    owner,headers=user()
    row=onboarding(headers)
    assert row['status']=='pending_review' and row['transactions_required'] is False
    assert enrol(row,headers).status_code==409
    rh=approve(row,headers)
    response=enrol(row,headers)
    assert response.status_code==200,response.text
    policy=response.json()
    assert policy['merchant_id']==row['merchant_id']
    assert policy['operator_id']==row['operator_id']
    assert policy['stall_entity_id']==row['stall_entity_id']
    assert policy['contract']['assigned_gauge']==row['gauge']
    assert policy['real_policy_issued'] is False and policy['billing']['collected_sgd']==0
    stall=row['stall_id']
    assert all(not p['granted'] for p in client.get('/api/v1/consents/'+stall,headers=headers).json()['permissions'])
    event={'stall_id':stall,'peril':'RAIN_70MM','event_date':pilot_store.today_sgt().isoformat()}
    assert client.post('/api/v1/triggers/simulate',json=event,headers=headers).status_code==403
    assert client.post('/api/v1/triggers/simulate',json=event,headers=rh).status_code==403
    service,sh=user('weather_service','service')
    assert client.post('/api/v1/triggers/simulate',json=event,headers=sh).status_code==404
    auth.set_grant(service,row['merchant_id'])
    # Ensure today is not a scheduled reference closure for this scenario.
    event['event_date']=(pilot_store.today_sgt()-timedelta(days=1)).isoformat()
    # Enrolment start is today, so a yesterday event must fail despite valid service access.
    assert client.post('/api/v1/triggers/simulate',json=event,headers=sh).status_code==409
    event.pop('event_date')
    result=client.post('/api/v1/triggers/simulate',json=event,headers=sh)
    assert result.status_code==200,result.text
    if pilot_store.today_sgt() in identity_api.CENTRES[row['centre_ref']].closures:
        assert result.json()['status']=='SUPPRESSED'
    else:
        assert result.json()['amount']==30
        assert result.json()['remaining_coverage']['remaining_combined_sgd']==150
    repeat=client.post('/api/v1/triggers/simulate',json=event,headers=sh).json()
    assert repeat['duplicate'] and not repeat['disbursed']
    assert client.get('/api/v1/payouts/'+stall,headers=headers).status_code==200
    auth.set_grant(owner,row['merchant_id'],False)
    assert client.get('/api/v1/policy/'+stall,headers=headers).status_code==404
    assert enrol(row,headers).status_code==404


def test_cross_merchant_and_privileged_routes(ledger_backend):
    _,a=user();_,b=user('merchant_two','operator')
    row=onboarding(a);other=onboarding(b,'other')
    stall=row['stall_id']
    for path in ('/api/v1/onboarding/','/api/v1/policy/','/api/v1/payouts/','/api/v1/consents/'):
        assert client.get(path+stall).status_code==401
        assert client.get(path+stall,headers=b).status_code==404
        assert client.get(path+'LOCAL-unknown',headers=b).status_code==404
    assert client.get('/api/v1/telemetry/live',params={'stall_id':stall},headers=b).status_code==404
    assert client.post('/quote',json={'stall_id':stall},headers=b).status_code==404
    assert enrol(row,b).status_code==404
    assert len(client.get('/api/v1/me/stalls',headers=b).json()['stalls'])==1
    assert client.get('/api/v1/me/stalls',headers=b).json()['stalls'][0]['stall_id']==other['stall_id']
    for path in ('/dash/portfolio','/dash/flags','/events','/engine/replay'):
        assert client.get(path,headers=a).status_code==403
    assert client.post('/api/v1/auth/singpass',json={}).status_code==501
    assert client.post('/api/v1/auth/phone-otp',json={'phone_number':'sensitive'}).status_code==501
    assert client.get('/api/v1/policy/HC076',headers=a).status_code==404
    assert client.post('/api/v1/onboarding',json=body('evil',role='reviewer',merchant_id=row['merchant_id']),headers=b).status_code==422
    assert client.get('/api/v1/contracts').status_code==200


@pytest.mark.parametrize('changes',[
    {'accepted_version':'future-unknown'}, {'latitude':2.0}, {'longitude':104.0},
    {'centre_id':'unknown'}, {'evidence_sha256':'not-a-hash'}, {'gauge':'S999'},
    {'latitude':float('inf')}, {'licence_ref':' '}, {'external_ref':' '},
])
def test_onboarding_validation(changes):
    _,h=user()
    # Infinity encoded manually to exercise parser validation as well as finite checks.
    content=json.dumps(body(**changes))
    response=client.post('/api/v1/onboarding',content=content,headers=h|{'Content-Type':'application/json'})
    assert response.status_code==422,response.text


def test_duplicate_and_explicit_external_mapping(ledger_backend):
    _,h=user();_,other=user('merchant_two')
    row=onboarding(h)
    assert onboarding(h)==row
    assert client.post('/api/v1/onboarding',json=body(),headers=other).status_code==409
    assert client.post('/api/v1/onboarding',json=body(accepted_version='future'),headers=h).status_code==422
    assert client.post('/api/v1/onboarding',json=body(evidence_sha256='a'*64),headers=h).status_code==409
    assert client.post('/api/v1/onboarding',json=body('different',licence_ref='licence-stall-one'),headers=h).status_code==409
    with configured_repository().transaction() as c:
        stored=c.execute('SELECT * FROM auth_onboarding WHERE stall_id=?',(row['stall_id'],)).fetchone()
        assert stored['external_ref_hash']==auth.digest('stall-one')
        assert stored['licence_ref_hash']==auth.digest('licence-stall-one')
        assert c.execute('SELECT COUNT(*) FROM auth_onboarding').fetchone()[0]==1


def test_review_permissions_and_versions(ledger_backend):
    _,h=user();row=onboarding(h)
    path='/api/v1/onboarding/'+row['stall_id']+'/review'
    payload={'status':'eligible_simulation','reason':'local_evidence_checked'}
    assert client.post(path,json=payload,headers=h).status_code==403
    rid,rh=user('reviewer_one','reviewer')
    assert client.post(path,json=payload,headers=rh).status_code==404
    auth.set_grant(rid,row['merchant_id'])
    assert client.post(path,json=payload|{'reason':'eligibility_withdrawn'},headers=rh).status_code==422
    assert client.post(path,json=payload,headers=rh).status_code==200
    assert client.post('/api/v1/policies',json={'stall_id':row['stall_id'],'accepted_version':'future','consent':True},headers=h).status_code==422
    assert client.post('/api/v1/policies',json={'stall_id':row['stall_id'],'accepted_version':M1_VERSION,'consent':False},headers=h).status_code==422
    assert enrol(row,h).status_code==200
    assert enrol(row,h).status_code==200
    assert client.post(path,json={'status':'revoked','reason':'eligibility_withdrawn'},headers=rh).status_code==200
    assert enrol(row,h).status_code==409


def test_session_rotation_expiry_revocation_and_secret_storage(ledger_backend,monkeypatch):
    pid,h=user()
    original=h['Authorization'][7:]
    with configured_repository().transaction() as c:
        row=c.execute('SELECT * FROM auth_credentials WHERE token_hash=?',(auth.digest(original),)).fetchone()
        assert original not in json.dumps(row)
        p=c.execute('SELECT * FROM auth_principals WHERE id=?',(pid,)).fetchone()
        assert PASSWORD not in json.dumps(p)
    result=client.post('/api/v1/auth/refresh',headers=h)
    assert result.status_code==200,result.text
    new={'Authorization':'Bearer '+result.json()['access_token']}
    assert client.get('/api/v1/auth/me',headers=h).status_code==401
    assert client.get('/api/v1/auth/me',headers=new).status_code==200
    with monkeypatch.context() as m:
        m.setattr(auth,'now',lambda:row['created_at']+901)
        assert client.get('/api/v1/auth/me',headers=new).status_code==401
        assert client.post('/api/v1/auth/refresh',headers=new).status_code==401
    assert client.post('/api/v1/auth/logout',headers=new).status_code==200
    assert client.get('/api/v1/auth/me',headers=new).status_code==401
    h1=client.post('/api/v1/auth/login',json={'alias':'merchant_one','password':PASSWORD}).json()
    h2=client.post('/api/v1/auth/login',json={'alias':'merchant_one','password':PASSWORD}).json()
    assert client.post('/api/v1/auth/logout-all',headers={'Authorization':'Bearer '+h1['access_token']}).status_code==200
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+h2['access_token']}).status_code==401
    result=client.post('/api/v1/auth/login',json={'alias':'merchant_one','password':PASSWORD})
    auth.disable(pid)
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+result.json()['access_token']}).status_code==401
    assert client.post('/api/v1/auth/login',json={'alias':'merchant_one','password':PASSWORD}).status_code==401


def test_bad_login_rate_limit_and_no_secret_echo(ledger_backend):
    user()
    for alias in ('merchant_one','unknown_alias'):
        for _ in range(5):
            r=client.post('/api/v1/auth/login',json={'alias':alias,'password':'secret-wrong-value'})
            assert r.status_code==401
            assert r.json()=={'detail':'Invalid credentials.'}
        assert client.post('/api/v1/auth/login',json={'alias':alias,'password':PASSWORD}).status_code==429
    response=client.post('/api/v1/auth/login',json={'alias':'x','password':'sensitive','nric':'sensitive'})
    assert response.status_code==422 and 'sensitive' not in response.text
    assert client.post('/api/v1/auth/login',json={'alias':'other_user','password':PASSWORD,'role':'reviewer'}).status_code==422


def test_controlled_service_scope_expiry_and_rotation(ledger_backend,monkeypatch):
    pid=auth.provision('weather_service','service')
    with pytest.raises(ValueError): auth.issue_service(pid,['consent:write'])
    with pytest.raises(ValueError): auth.issue_service(pid,['coverage:read'],ttl=86401)
    result=auth.issue_service(pid,['coverage:read'],ttl=60)
    h={'Authorization':'Bearer '+result['access_token']}
    assert client.post('/api/v1/triggers/simulate',json={'stall_id':'HC076','peril':'RAIN_70MM'},headers=h).status_code==403
    assert client.post('/api/v1/auth/refresh',headers=h).status_code==403
    with monkeypatch.context() as m:
        m.setattr(auth,'now',lambda:result['expires_at'])
        assert client.get('/api/v1/auth/me',headers=h).status_code==401
    rotated=auth.issue_service(pid,['coverage:read'],rotate=True)
    assert client.get('/api/v1/auth/me',headers=h).status_code==401
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+rotated['access_token']}).status_code==200


def test_optional_consent_purposes_revocation_expiry_and_audit(ledger_backend,monkeypatch):
    _,h=user();row=onboarding(h);approve(row,h)
    assert enrol(row,h).status_code==200
    sid,sh=user('analysis_service','service');auth.set_grant(sid,row['merchant_id'])
    stall=row['stall_id'];path='/api/v1/consents/'+stall
    access='/api/v1/transaction-access/'+stall
    params={'purpose':'income_baseline'}
    assert client.get(access,params=params,headers=sh).status_code==403
    payload={'purpose':'income_baseline','action':'grant','scope':'transactions:read'}
    granted=client.post(path,json=payload,headers=h)
    assert granted.status_code==200,granted.text
    assert client.get(access,params=params,headers=sh).json()['authorized']
    assert client.get(access,params={'purpose':'weather_impact_research'},headers=sh).status_code==403
    assert client.post(path,json=payload|{'scope':'transactions:retain'},headers=h).status_code==422
    assert client.post(path,json=payload|{'retention_days':1},headers=h).status_code==422
    assert client.post(path,json=payload,headers=sh).status_code==403
    with monkeypatch.context() as m:
        m.setattr(auth,'now',lambda:granted.json()['expires_at'])
        # Need a fresh service token at this future time to distinguish consent expiry.
        fresh=auth.issue_service(sid,['transactions:read'])
        assert client.get(access,params=params,headers={'Authorization':'Bearer '+fresh['access_token']}).status_code==403
    assert client.post(path,json=payload|{'action':'revoke'},headers=h).json()['granted'] is False
    assert client.get(access,params=params,headers=sh).status_code==403
    retention={'purpose':'transaction_retention','action':'grant','scope':'transactions:retain','retention_days':30}
    assert client.post(path,json=retention|{'retention_days':0},headers=h).status_code==422
    assert client.post(path,json=retention,headers=h).status_code==200
    assert client.get(access,params={'purpose':'transaction_retention'},headers=sh).status_code==200
    # Sales permission withdrawal does not withdraw fixed cover.
    assert client.get('/api/v1/policy/'+stall,headers=h).json()['remaining_combined_sgd']==180
    assert client.post('/api/v1/triggers/simulate',json={'stall_id':stall,'peril':'HAZE_151_ACUTE'},headers=sh).status_code==200
    with ledger_backend.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM auth_consent_events').fetchone()[0]==3
    with pytest.raises(Exception):
        with ledger_backend.transaction() as c:
            c.execute('DELETE FROM auth_consent_events')


def test_explicit_demo_mode_does_not_bypass_local_resources(monkeypatch):
    _,h=user();row=onboarding(h)
    monkeypatch.setenv('DAYCOVER_AUTH_MODE','demo')
    persona=client.post('/api/v1/auth/singpass',json={'custom_nric':'PRIVATE','custom_name':'PRIVATE'}).json()
    assert persona['demo_only'] and not persona['identity_verified'] and 'PRIVATE' not in json.dumps(persona)
    assert client.get('/api/v1/policy/'+row['stall_id']).status_code==401
    assert client.get('/api/v1/policy/HC076',headers={'Authorization':'Bearer invalid'}).status_code==401
    monkeypatch.setenv('DAYCOVER_AUTH_MODE','invalid')
    assert client.get('/api/v1/contracts').status_code==503


def test_v2_checksum_refuses_tampered_migration(tmp_path,monkeypatch):
    path=tmp_path/'v1.sqlite3'
    script=(MIGRATIONS/'001_sqlite.sql').read_text()
    with sqlite3.connect(path) as conn:
        conn.executescript(script)
        conn.execute('INSERT INTO pilot_schema_migrations VALUES (?,?)',(1,hashlib.sha256(script.encode()).hexdigest()))
    repo=SqlLedgerRepository(path=path)
    monkeypatch.setenv('DAYCOVER_PILOT_DB',str(path))
    repo.migrate()
    with repo.transaction() as c:
        assert len(c.execute('SELECT * FROM pilot_schema_migrations').fetchall())==7
        c.execute('UPDATE pilot_schema_migrations SET checksum=? WHERE version=2',('tampered',))
    with pytest.raises(ValueError,match='checksum'): repo.migrate()


def test_concurrent_refresh_and_duplicate_onboarding(ledger_backend):
    _,h=user()
    def submit(_):
        return client.post('/api/v1/onboarding',json=body(),headers=h)
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses=list(pool.map(submit,range(3)))
    assert all(r.status_code==200 for r in responses)
    assert len({r.json()['stall_id'] for r in responses})==1
    with ThreadPoolExecutor(max_workers=2) as pool:
        refreshed=list(pool.map(lambda _:client.post('/api/v1/auth/refresh',headers=h),range(2)))
    assert sorted(r.status_code for r in refreshed)==[200,401]


def test_refresh_cannot_extend_absolute_session_lifetime(ledger_backend,monkeypatch):
    _,h=user()
    original=auth.now()
    token=h['Authorization'][7:]
    # A sliding session can be refreshed only up to its original eight-hour boundary.
    for elapsed in range(800,28800,800):
        monkeypatch.setattr(auth,'now',lambda elapsed=elapsed:original+elapsed)
        result=client.post('/api/v1/auth/refresh',headers={'Authorization':'Bearer '+token})
        assert result.status_code==200,result.text
        token=result.json()['access_token']
        assert result.json()['expires_at']<=original+28800
    monkeypatch.setattr(auth,'now',lambda:original+28800)
    assert client.post('/api/v1/auth/refresh',headers={'Authorization':'Bearer '+token}).status_code==401


def test_v1_upgrade_and_failure_preserve_ledger(ledger_backend,monkeypatch):
    from src.daycover import ledger_migrations
    from datetime import date
    # Prepare a genuine v1 state in this fixture's disposable database only.
    policy=pilot_store.enrol('HC001',date(2025,12,15),'S79','south')
    receipt=pilot_store.simulate('HC001',date(2026,1,2),'rain',70,None,None,False,'S79','south')
    with ledger_backend.transaction() as c:
        saved=dict(c.execute('SELECT * FROM pilot_policies').fetchone())
        for table in ('settlement_mock_wallet_entries','settlement_cash_entries','settlement_provider_events','settlement_dispatch_attempts','settlement_instruction_events','settlement_mock_jobs','settlement_mock_key','settlement_instructions','settlement_outbox','settlement_recipient_reviews','settlement_recipients'):
            c.execute('DROP TABLE '+table)
        for table in ('billing_mock_refunds','billing_mock_jobs','billing_mock_key','billing_refund_requests','billing_entry_links','billing_provider_events','billing_dispatches','billing_attempts','billing_authorizations','billing_bills','billing_schedules'):
            c.execute('DROP TABLE '+table)
        for table in ('engine_replay_reviews','engine_replay_plans','engine_entitlement_entries','engine_cap_entries','engine_decisions','engine_period_modes','engine_lifecycle_events','engine_terms'):
            c.execute('DROP TABLE '+table)
        for table in ('weather_evidence_selections','weather_daily_reviews','weather_daily_details','weather_closure_reviews','weather_closure_versions','weather_revision_reviews','weather_mapping_reviews'):
            c.execute('DROP TABLE '+table)
        for table in ('weather_observation_provenance','weather_station_presence','weather_station_versions','weather_alerts','weather_fetches','weather_runs','weather_transport_gate'):
            c.execute('DROP TABLE '+table)
        c.execute('DROP INDEX weather_observation_lookup')
        if c.backend=='postgres':
            c.execute('DROP FUNCTION weather_append_only()')
        for table in ('auth_credentials','auth_grants','auth_onboarding','auth_consent_events','auth_login_limits','auth_principals'):
            c.execute('DROP TABLE '+table)
        if c.backend=='postgres':
            c.execute('DROP FUNCTION auth_consent_immutable()')
        c.execute('DELETE FROM pilot_schema_migrations WHERE version>=2')
    original_apply=ledger_migrations._apply
    def interrupted(native,backend,script):
        original_apply(native,backend,script)
        if 'CREATE TABLE auth_principals' in script:
            raise RuntimeError('Injected migration interruption')
    monkeypatch.setattr(ledger_migrations,'_apply',interrupted)
    with pytest.raises(RuntimeError,match='interruption'):
        ledger_backend.migrate()
    # Inspect directly: normal repository access deliberately refuses an unmigrated PG DB.
    native=ledger_backend._connect()
    try:
        if ledger_backend.backend=='sqlite':
            assert native.execute("SELECT name FROM sqlite_master WHERE name='auth_principals'").fetchone() is None
        else:
            assert native.execute("SELECT to_regclass('auth_principals') AS name").fetchone()['name'] is None
        assert native.execute('SELECT COUNT(*) AS n FROM pilot_schema_migrations').fetchone()['n']==1
        assert dict(native.execute('SELECT * FROM pilot_policies').fetchone())['id']==saved['id']
    finally:
        native.close()
    monkeypatch.setattr(ledger_migrations,'_apply',original_apply)
    ledger_backend.migrate()
    with ledger_backend.transaction() as c:
        assert dict(c.execute('SELECT * FROM pilot_policies').fetchone())==saved
    assert pilot_store.policy('HC001')['policy_id']==policy['policy_id']
    assert pilot_store.policy('HC001')['remaining_combined_sgd']==150
    assert pilot_store.history('HC001')['claims'][0]['claim_id']==receipt['claim_id']


def test_secure_default_and_openapi_credentials(monkeypatch):
    monkeypatch.delenv('DAYCOVER_AUTH_MODE')
    assert client.get('/api/v1/policy/HC076').status_code==401
    assert client.post('/api/v1/auth/singpass',json={}).status_code==501
    schema=client.get('/openapi.json').json()
    for path,method in [('/api/v1/policies','post'),('/api/v1/policy/{stall_id}','get'),('/api/v1/triggers/simulate','post'),('/api/v1/onboarding','post')]:
        assert schema['paths'][path][method]['security']==[{'HTTPBearer':[]}]
