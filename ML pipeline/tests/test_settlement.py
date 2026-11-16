"""Phase 8 mock-only outbox, current authority, recipient and settlement invariants."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from fastapi.testclient import TestClient
from src.daycover import auth,settlement,evidence_engine as engine,daily_evidence as daily,pilot_store
from src.daycover.api import app
from src.daycover.settlement_provider import MockSettlementProvider
from src.daycover.ledger_repository import SqlLedgerRepository
from test_evidence_engine import setup as engine_setup,weather,DAY,NOW,REF


def rows(repo,table):
    with repo.transaction() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table).fetchall()]


def setup(repo,approve=True):
    reviewer,p,term=engine_setup(repo);weather(repo,reviewer,p,DAY)
    owner=auth.provision('settlement_owner','customer','local-owner-test-password')
    service=auth.provision('settlement_service','service')
    engine.evaluate('HC076',DAY,DAY,repo,now=NOW)
    recipient=settlement.register_recipient('HC076','MOCK-recipient-fixture',owner,repo,now=NOW)['recipient_id']
    if approve:settlement.review_recipient('HC076',recipient,'approved',reviewer,REF,repo,now=NOW)
    outbox=next(r['id'] for r in rows(repo,'settlement_outbox') if r['peril']=='haze')
    return owner,reviewer,service,p,term['term_id'],recipient,outbox


def queued(repo,tid,rid,oid,service,key='first-settlement',scenario='success'):
    return settlement.queue('HC076',tid,oid,rid,key,scenario,service,repo,now=NOW)['instruction_id']


def summary(repo,tid):return settlement.overview('HC076',tid,repo,now=NOW)['summary']


def test_accepted_entitlement_and_outbox_are_atomic_but_not_a_payment(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend)
    outbox=rows(ledger_backend,'settlement_outbox')
    assert len(outbox)==1 and outbox[0]['decision_id'] in {r['id'] for r in rows(ledger_backend,'engine_decisions')}
    assert json.loads(outbox[0]['snapshot'])['evidence']['psi_aggregate_id']
    assert rows(ledger_backend,'settlement_instructions')==[] and rows(ledger_backend,'settlement_mock_wallet_entries')==[]
    assert summary(ledger_backend,tid)['net_entitlement_cents']==6000
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==0
    # A separate explicit queue reserves, but does not send or credit anything.
    iid=queued(ledger_backend,tid,rid,oid,service)
    assert queued(ledger_backend,tid,rid,oid,service)==iid
    assert summary(ledger_backend,tid)['reserved_cents']==6000
    assert rows(ledger_backend,'settlement_mock_jobs')==[]
    assert rows(ledger_backend,'pilot_financial_entries')==[]


def test_mock_confirmation_credits_wallet_once_and_submission_is_not_confirmation(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    result=settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    assert result['status']=='submitted' and not result['real_transfer']
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==0
    assert settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)['accepted']
    assert settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)['duplicate']
    assert settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)['duplicate']
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000
    assert summary(ledger_backend,tid)['unreserved_cents']==0
    assert len(rows(ledger_backend,'settlement_mock_wallet_entries'))==1
    assert sum(r['amount_cents'] for r in rows(ledger_backend,'settlement_mock_wallet_entries'))==6000
    with pytest.raises(ValueError):queued(ledger_backend,tid,rid,oid,service,key='do-not-double-pay')
    assert pilot_store.policy('HC076')['remaining_combined_sgd']==120
    assert rows(ledger_backend,'pilot_financial_entries')==[]


def test_recipient_review_is_mock_only_and_revocation_stops_unsent_instructions(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend,False)
    with pytest.raises(ValueError,match='approval'):queued(ledger_backend,tid,rid,oid,service)
    with pytest.raises(ValueError):settlement.review_recipient('HC076',rid,'approved',owner,REF,ledger_backend)
    approved=settlement.review_recipient('HC076',rid,'approved',reviewer,REF,ledger_backend,now=NOW)
    assert not approved['real_recipient_verified']
    iid=queued(ledger_backend,tid,rid,oid,service)
    settlement.review_recipient('HC076',rid,'revoked',reviewer,REF,ledger_backend,now=NOW)
    blocked=settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    assert blocked['status']=='canceled_unsent' and blocked['submission']=='NO_PROVIDER_CALL'
    assert summary(ledger_backend,tid)['reserved_cents']==0
    assert rows(ledger_backend,'settlement_mock_jobs')==[]
    with pytest.raises(ValueError):settlement.register_recipient('HC076','NRIC-S1234567A',owner,ledger_backend)
    assert 'MOCK-recipient-fixture' not in json.dumps(rows(ledger_backend,'settlement_recipients'))


def test_lost_provider_response_recovers_same_reference_without_double_credit(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    class Crash(MockSettlementProvider):
        def submit(self,instruction):super().submit(instruction);raise RuntimeError('Injected crash after provider acceptance')
    with pytest.raises(RuntimeError):settlement.dispatch('HC076',tid,iid,service,ledger_backend,provider=Crash(ledger_backend),now=NOW)
    assert len(rows(ledger_backend,'settlement_mock_jobs'))==1
    assert summary(ledger_backend,tid)['reserved_cents']==6000
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==0
    with pytest.raises(ValueError):queued(ledger_backend,tid,rid,oid,service,key='unsafe-retry')
    reopened=SqlLedgerRepository(ledger_backend.backend,path=ledger_backend.path,url=ledger_backend.url,schema=ledger_backend.schema)
    settlement.dispatch('HC076',tid,iid,service,reopened,now=NOW)
    settlement.reconcile('HC076',tid,iid,reopened,now=NOW)
    assert len(rows(ledger_backend,'settlement_mock_jobs'))==1
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000


def test_timeout_and_pending_remain_reserved_and_retry_policy_is_bounded(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service,scenario='timeout')
    for _ in range(3):assert settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)['status']=='uncertain'
    assert settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)['submission']=='RECONCILE_ONLY'
    assert len(rows(ledger_backend,'settlement_dispatch_attempts'))==3
    assert summary(ledger_backend,tid)['reserved_cents']==6000
    settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000


def test_callback_before_ack_does_not_regress_confirmed_state(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    class EarlyCallback(MockSettlementProvider):
        def submit(self,instruction):
            ack=super().submit(instruction);envelope=super().status(instruction['id'])
            assert settlement.ingest_event('HC076',tid,instruction['id'],envelope['payload'],envelope['signature'],ledger_backend,now=NOW)['accepted']
            return ack
    result=settlement.dispatch('HC076',tid,iid,service,ledger_backend,provider=EarlyCallback(ledger_backend),now=NOW)
    assert result['status']=='confirmed'
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000
    assert len(rows(ledger_backend,'settlement_mock_wallet_entries'))==1


def test_reversal_before_confirmation_stays_net_zero_and_retry_is_net_only(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service,scenario='reversal')
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    provider=MockSettlementProvider(ledger_backend);first=provider.status(iid);reversed_=provider.status(iid)
    settlement.ingest_event('HC076',tid,iid,reversed_['payload'],reversed_['signature'],ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==0
    assert settlement.ingest_event('HC076',tid,iid,first['payload'],first['signature'],ledger_backend,now=NOW)['stale']
    assert sum(r['amount_cents'] for r in rows(ledger_backend,'settlement_mock_wallet_entries'))==0
    retry=queued(ledger_backend,tid,rid,oid,service,key='after-provider-return')
    settlement.dispatch('HC076',tid,retry,service,ledger_backend,now=NOW);settlement.reconcile('HC076',tid,retry,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000
    assert sum(r['amount_cents'] for r in rows(ledger_backend,'settlement_mock_wallet_entries'))==6000


def test_failed_or_terminal_partial_transfer_retries_only_remaining_net_entitlement(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service,scenario='failed')
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW);settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['unreserved_cents']==6000
    partial=queued(ledger_backend,tid,rid,oid,service,key='partial-retry',scenario='partial')
    settlement.dispatch('HC076',tid,partial,service,ledger_backend,now=NOW);settlement.reconcile('HC076',tid,partial,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==3000
    rest=queued(ledger_backend,tid,rid,oid,service,key='remaining-retry')
    assert next(r for r in rows(ledger_backend,'settlement_instructions') if r['id']==rest)['amount_cents']==3000
    settlement.dispatch('HC076',tid,rest,service,ledger_backend,now=NOW);settlement.reconcile('HC076',tid,rest,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000


@pytest.mark.parametrize('field,value,reason',[
    ('recipient_id','foreign-recipient','instruction_or_recipient_reference_mismatch'),
    ('recipient_review_id','unapproved-review','instruction_or_recipient_reference_mismatch'),
    ('provider_ref','incorrect-reference','instruction_or_recipient_reference_mismatch'),
    ('currency','USD','instruction_or_recipient_reference_mismatch'),
    ('gross_cents',6001,'amount_exceeds_immutable_instruction'),
    ('status','pending','invalid_zero_outcome'),
])
def test_invalid_provider_snapshots_are_retained_without_wallet_credit(field,value,reason):
    from src.daycover.ledger_repository import configured_repository
    repo=configured_repository();owner,reviewer,service,p,tid,rid,oid=setup(repo);iid=queued(repo,tid,rid,oid,service)
    settlement.dispatch('HC076',tid,iid,service,repo,now=NOW)
    provider=MockSettlementProvider(repo);valid=provider.status(iid)
    bad=dict(valid['payload']);bad[field]=value
    with repo.transaction() as c:signature=provider.sign(c,bad)
    rejected=settlement.ingest_event('HC076',tid,iid,bad,signature,repo,now=NOW)
    assert rejected['quarantined'] and rejected['reason']==reason
    assert summary(repo,tid)['confirmed_mock_cents']==0 and rows(repo,'settlement_mock_wallet_entries')==[]
    assert settlement.ingest_event('HC076',tid,iid,valid['payload'],'0'*64,repo,now=NOW)['reason']=='invalid_mock_signature'
    assert settlement.ingest_event('HC076',tid,iid,valid['payload'],valid['signature'],repo,now=NOW)['accepted']
    assert summary(repo,tid)['confirmed_mock_cents']==6000
    assert settlement.overview('HC076',tid,repo,now=NOW)['review_required']


def test_wallet_and_cash_posting_failure_rolls_back_callback_receipt(ledger_backend,monkeypatch):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    envelope=MockSettlementProvider(ledger_backend).status(iid);original=settlement._post_cash
    def failed(*args):original(*args);raise RuntimeError('Injected crash after local wallet insert')
    monkeypatch.setattr(settlement,'_post_cash',failed)
    with pytest.raises(RuntimeError):settlement.ingest_event('HC076',tid,iid,envelope['payload'],envelope['signature'],ledger_backend,now=NOW)
    for table in ('settlement_provider_events','settlement_cash_entries','settlement_mock_wallet_entries'):assert rows(ledger_backend,table)==[]
    assert summary(ledger_backend,tid)['reserved_cents']==6000
    monkeypatch.setattr(settlement,'_post_cash',original)
    assert settlement.ingest_event('HC076',tid,iid,envelope['payload'],envelope['signature'],ledger_backend,now=NOW)['accepted']
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000


def test_decision_outbox_failure_rolls_back_entitlement_caps_and_decision(ledger_backend,monkeypatch):
    reviewer,p,term=engine_setup(ledger_backend);weather(ledger_backend,reviewer,p,DAY)
    original=settlement.record_outbox
    def interrupted(*args):original(*args);raise RuntimeError('Injected outbox failure')
    monkeypatch.setattr(settlement,'record_outbox',interrupted)
    with pytest.raises(RuntimeError):engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    for table in ('engine_decisions','engine_entitlement_entries','engine_cap_entries','settlement_outbox'):assert rows(ledger_backend,table)==[]
    monkeypatch.setattr(settlement,'record_outbox',original)
    assert engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)['net_entitlement_cents']==6000
    assert len(rows(ledger_backend,'settlement_outbox'))==1


def test_stale_evidence_stops_unsent_instruction_without_releasing_weather_cap(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    daily.propose_closure(p['centre_id'],DAY,True,'works',REF,'a'*64,ledger_backend)
    result=settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    assert result['status']=='canceled_unsent' and result['submission']=='NO_PROVIDER_CALL'
    assert rows(ledger_backend,'settlement_mock_jobs')==[] and rows(ledger_backend,'settlement_mock_wallet_entries')==[]
    assert engine.history('HC076',ledger_backend)['consumed_cap_cents']==6000
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']==6000
    assert summary(ledger_backend,tid)['reserved_cents']==0


def correction(repo,reviewer,p,tid,closed,marker):
    closure=daily.propose_closure(p['centre_id'],DAY,closed,'cleaning' if closed else 'explicit_open',REF,marker*64,repo)
    daily.review_closure(closure['closure_id'],'approved',reviewer,REF,repo)
    engine.evaluate('HC076',DAY,DAY,repo,now=NOW)
    plan=engine.plan_replay('HC076',tid,DAY,repo,now=NOW)
    engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,repo,now=NOW)
    settlement.sync('HC076',tid,repo,now=NOW)


def test_inflight_correction_reconciles_actual_mock_outcome_as_overpayment_for_review(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    correction(ledger_backend,reviewer,p,tid,True,'b')
    assert summary(ledger_backend,tid)['net_entitlement_cents']==0
    assert summary(ledger_backend,tid)['reserved_cents']==6000
    retry=settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    assert retry['submission']=='NO_PROVIDER_CALL' and retry['reconciliation_required']
    settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['overpaid_mock_cents']==6000
    assert settlement.overview('HC076',tid,ledger_backend,now=NOW)['review_required']
    assert sum(r['amount_cents'] for r in rows(ledger_backend,'settlement_mock_wallet_entries'))==6000
    assert engine.history('HC076',ledger_backend)['consumed_cap_cents']==6000
    assert settlement.overview('HC076',tid,ledger_backend,now=NOW)['real_paid_cents']==0


def test_signed_positive_entitlement_after_downward_correction_is_not_a_second_payment(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW);settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)
    correction(ledger_backend,reviewer,p,tid,True,'c')
    correction(ledger_backend,reviewer,p,tid,False,'d')
    assert [r['amount_cents'] for r in rows(ledger_backend,'engine_entitlement_entries')]==[6000,-6000,6000]
    latest=next(r['id'] for r in reversed(rows(ledger_backend,'settlement_outbox')) if json.loads(r['snapshot'])['target_entitlement_sgd']==60)
    with pytest.raises(ValueError):queued(ledger_backend,tid,rid,latest,service,key='do-not-pay-every-positive-entry')
    assert summary(ledger_backend,tid)['net_entitlement_cents']==summary(ledger_backend,tid)['confirmed_mock_cents']==6000
    assert len(rows(ledger_backend,'settlement_mock_wallet_entries'))==1


def test_recipient_change_cannot_reroute_an_unknown_transfer(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service,scenario='timeout')
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    second=settlement.register_recipient('HC076','MOCK-second-recipient',owner,ledger_backend,now=NOW)['recipient_id']
    settlement.review_recipient('HC076',second,'approved',reviewer,REF,ledger_backend,now=NOW)
    settlement.review_recipient('HC076',rid,'revoked',reviewer,REF,ledger_backend,now=NOW)
    with pytest.raises(ValueError,match='Reconcile'):queued(ledger_backend,tid,second,oid,service,key='no-reroute')
    settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000
    assert len(rows(ledger_backend,'settlement_mock_jobs'))==1


def test_concurrent_queue_dispatch_and_callbacks_cannot_double_credit(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend)
    def create(index):
        try:return queued(ledger_backend,tid,rid,oid,service,key='concurrent-'+str(index))
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:instructions=list(pool.map(create,range(4)))
    assert sum(bool(i) for i in instructions)==1
    iid=next(i for i in instructions if i)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(lambda _:settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW),range(3)))
    envelope=MockSettlementProvider(ledger_backend).status(iid)
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies=list(pool.map(lambda _:settlement.ingest_event('HC076',tid,iid,envelope['payload'],envelope['signature'],ledger_backend,now=NOW),range(4)))
    assert sum(r.get('wallet_changed',False) for r in replies)==1
    assert len(rows(ledger_backend,'settlement_mock_jobs'))==len(rows(ledger_backend,'settlement_mock_wallet_entries'))==1
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==6000


def test_settlement_api_requires_scopes_and_object_ownership_and_hides_real_rails(ledger_backend,monkeypatch):
    monkeypatch.setenv('DAYCOVER_AUTH_MODE','local')
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend,False)
    foreign=auth.provision('foreign_settlement_service','service')
    for actor in (owner,reviewer,service):auth.set_grant(actor,p['merchant_id'])
    client=TestClient(app)
    def login(alias,password):return {'Authorization':'Bearer '+client.post('/api/v1/auth/login',json={'alias':alias,'password':password}).json()['access_token']}
    ch=login('settlement_owner','local-owner-test-password');rh=login('engine_reviewer','local-reviewer-test-password')
    sh={'Authorization':'Bearer '+auth.issue_service(service,['coverage:read','settlement:queue','settlement:submit','settlement:reconcile'])['access_token']}
    fh={'Authorization':'Bearer '+auth.issue_service(foreign,['coverage:read','settlement:queue'])['access_token']}
    base='/api/v1/settlements/HC076/'+tid
    assert client.get(base).status_code==401 and client.get(base,headers=fh).status_code==404
    assert client.post('/api/v1/settlement-recipients/HC076',json={'mock_reference':'NRIC-S1234567A'},headers=ch).status_code==422
    assert client.post('/api/v1/settlement-recipients/HC076/'+rid+'/review',json={'decision':'approved','source_ref':REF},headers=sh).status_code==403
    assert client.post('/api/v1/settlement-recipients/HC076/'+rid+'/review',json={'decision':'approved','source_ref':REF},headers=rh).status_code==200
    payload={'outbox_id':oid,'recipient_id':rid,'idempotency_key':'api-settlement','scenario':'success'}
    assert client.post(base+'/queue',json=payload,headers=ch).status_code==403
    assert client.post(base+'/queue',json=payload|{'amount_cents':100000,'rail':'real_paynow'},headers=sh).status_code==422
    queued_response=client.post(base+'/queue',json=payload,headers=sh)
    assert queued_response.status_code==200,queued_response.text
    path=base+'/instructions/'+queued_response.json()['instruction_id']
    assert client.post(path+'/submit',headers=sh).status_code==200
    assert client.get(base,headers=ch).json()['summary']['confirmed_mock_cents']==0
    assert client.post(path+'/reconcile',headers=sh).status_code==200
    view=client.get(base,headers=ch).json()
    assert view['summary']['confirmed_mock_cents']==view['summary']['mock_wallet_net_cents']==6000
    assert view['real_paid_cents']==0 and not view['real_rail_enabled'] and not view['external_wallet_bridge']
    history=client.get('/api/v1/engine-decisions/HC076',headers=ch).json()
    assert history['mock_settlement']['confirmed_net_mock_cents']==6000 and history['payment_execution']=='MOCK_OUTCOMES_RECORDED'
    assert history['disbursed_sgd']==0
    auth.set_grant(service,p['merchant_id'],False)
    assert client.post(path+'/reconcile',headers=sh).status_code==404


def test_pending_provider_outcome_is_not_guessed_failed_or_paid(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service,scenario='pending')
    assert settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)['status']=='uncertain'
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW)
    settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['confirmed_mock_cents']==0 and summary(ledger_backend,tid)['reserved_cents']==6000
    assert rows(ledger_backend,'settlement_mock_wallet_entries')==[]
    with pytest.raises(ValueError):queued(ledger_backend,tid,rid,oid,service,key='no-guessing')


def test_existing_legacy_synthetic_receipt_is_not_paid_again(ledger_backend):
    p=pilot_store.enrol('HC076',DAY,'S79','south')
    pilot_store.simulate('HC076',DAY,'haze',None,151,None,False,'S79','south')
    tid=next(r['id'] for r in rows(ledger_backend,'engine_terms'))
    with pytest.raises(ValueError,match='Legacy synthetic'):settlement.sync('HC076',tid,ledger_backend,now=NOW)
    assert rows(ledger_backend,'settlement_outbox')==[]
    assert rows(ledger_backend,'settlement_instructions')==[]
    assert rows(ledger_backend,'settlement_mock_wallet_entries')==[]


def test_settlement_history_is_append_only_and_balances_reconcile(ledger_backend):
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend);iid=queued(ledger_backend,tid,rid,oid,service)
    settlement.dispatch('HC076',tid,iid,service,ledger_backend,now=NOW);settlement.reconcile('HC076',tid,iid,ledger_backend,now=NOW)
    assert not settlement.overview('HC076',tid,ledger_backend,now=NOW)['reconciliation_issues']
    for table in ('settlement_recipients','settlement_recipient_reviews','settlement_outbox','settlement_instructions','settlement_instruction_events','settlement_dispatch_attempts','settlement_provider_events','settlement_cash_entries','settlement_mock_wallet_entries'):
        with pytest.raises(Exception):
            with ledger_backend.transaction() as c:c.execute('DELETE FROM '+table)


def test_v7_migration_backfill_and_failure_preserve_existing_billing_and_entitlements(ledger_backend,monkeypatch):
    from src.daycover import ledger_migrations,billing
    owner,reviewer,service,p,tid,rid,oid=setup(ledger_backend)
    billing.prepare('HC076',tid,ledger_backend,now=NOW)
    before_entitlements=rows(ledger_backend,'engine_entitlement_entries');before_bills=rows(ledger_backend,'pilot_billing_entries')
    with ledger_backend.transaction() as c:
        for table in ('settlement_mock_wallet_entries','settlement_cash_entries','settlement_provider_events','settlement_dispatch_attempts','settlement_instruction_events','settlement_mock_jobs','settlement_mock_key','settlement_instructions','settlement_outbox','settlement_recipient_reviews','settlement_recipients'):
            c.execute('DROP TABLE '+table)
        c.execute('DROP TABLE collection_ignored_events');c.execute('DROP TABLE collection_accrual_entries')
        c.execute('DELETE FROM pilot_schema_migrations WHERE version>=7')
    original=ledger_migrations._apply
    def fail(native,backend,script):
        original(native,backend,script)
        if 'CREATE TABLE settlement_recipients' in script:raise RuntimeError('Injected v7 DDL interruption')
    monkeypatch.setattr(ledger_migrations,'_apply',fail)
    with pytest.raises(RuntimeError):ledger_backend.migrate()
    native=ledger_backend._connect()
    try:assert native.execute('SELECT COUNT(*) AS n FROM pilot_schema_migrations').fetchone()['n']==6
    finally:native.close()
    monkeypatch.setattr(ledger_migrations,'_apply',original)
    ledger_backend.migrate();ledger_backend.migrate()
    assert rows(ledger_backend,'engine_entitlement_entries')==before_entitlements
    assert rows(ledger_backend,'pilot_billing_entries')==before_bills
    assert len(rows(ledger_backend,'settlement_outbox'))==1
    assert rows(ledger_backend,'settlement_instructions')==[] and rows(ledger_backend,'settlement_cash_entries')==[]
    assert settlement.sync('HC076',tid,ledger_backend,now=NOW)['outbox_ids']==[oid]


def test_integration_discovery_exposes_mock_availability_without_real_rail_claims():
    body=TestClient(app).get('/api/v1/integration').json()
    assert body['mock_settlement']['available']
    assert body['mock_settlement']['recipient_review_scope']=='local_mock_only'
    assert not body['mock_settlement']['external_wallet_bridge'] and not body['mock_settlement']['real_rail_enabled']
    assert not body['real_settlement_supported'] and not body['real_issuance_supported']
