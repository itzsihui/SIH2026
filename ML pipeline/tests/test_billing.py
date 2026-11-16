"""Exact mock billing, callbacks, reservations and authorization on both SQL backends."""
from datetime import date,datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json

import pytest
from fastapi.testclient import TestClient
from src.daycover import auth,billing,policy_lifecycle as life,pilot_store
from src.daycover.api import app
from src.daycover.billing_provider import MockCollectionProvider
from src.daycover.ledger_repository import SqlLedgerRepository
from src.daycover.ingestion import SGT

DAY=date(2026,11,15)
NOW=datetime(2026,11,20,12,tzinfo=SGT)


def rows(repo,table):
    with repo.transaction() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table).fetchall()]


def setup(repo,start=DAY,now=NOW):
    owner=auth.provision('billing_owner','customer','local-owner-test-password')
    reviewer=auth.provision('billing_reviewer','reviewer','local-review-test-password')
    service=auth.provision('billing_service','service')
    p=pilot_store.enrol('HC076',start,'S79','south')
    tid=life.overview('HC076',repo,as_of=start)['terms'][0]['term_id']
    statement=billing.prepare('HC076',tid,repo,now=now)
    billing.authorize('HC076',tid,owner,'grant',repo,now=now)
    return owner,reviewer,service,p,tid,statement['bills'][0]['id']


def attempt(repo,tid,bill,service,key='first-attempt',scenario='success',now=NOW):
    return billing.create_attempt('HC076',tid,bill,key,scenario,service,repo,now=now)['attempt_id']


def summary(repo,tid):return billing.statement('HC076',tid,repo,as_of=NOW.date())['summary']


def test_exact_schedule_readonly_projection_and_idempotent_obligations(ledger_backend):
    p=pilot_store.enrol('HC076',date(2024,1,31),'S79','south')
    tid=life.overview('HC076',ledger_backend)['terms'][0]['term_id']
    projection=billing.statement('HC076',tid,ledger_backend,as_of=date(2024,3,1))
    assert not projection['prepared'] and rows(ledger_backend,'pilot_billing_entries')==[]
    prepared=billing.prepare('HC076',tid,ledger_backend,now=datetime(2024,3,1,tzinfo=SGT))
    assert [b['amount_cents'] for b in prepared['bills']]==[867]*8+[866]*4
    assert [b['due_on'] for b in prepared['bills'][:3]]==['2024-01-31','2024-02-29','2024-03-31']
    assert prepared['summary']['annual_obligation_cents']==10400 and prepared['summary']['due_outstanding_cents']==1734
    billing.prepare('HC076',tid,ledger_backend,now=NOW)
    assert len(rows(ledger_backend,'pilot_billing_entries'))==12
    assert prepared['real_collected_cents']==0 and not prepared['real_mandate_connected']
    assert prepared['authorization']['status']=='missing'


def test_submission_is_not_collection_and_confirmation_is_idempotent(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    aid=attempt(ledger_backend,tid,bill,service)
    assert attempt(ledger_backend,tid,bill,service)==aid
    assert summary(ledger_backend,tid)['pending_cents']==867
    submitted=billing.submit('HC076',tid,aid,ledger_backend,now=NOW)
    assert submitted['status']=='submitted' and not submitted['collection_confirmed']
    assert summary(ledger_backend,tid)['collected_cents']==0
    assert billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)['accepted']
    assert billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)['duplicate']
    totals=summary(ledger_backend,tid)
    assert totals['collected_cents']==867 and totals['pending_cents']==0 and totals['outstanding_cents']==9533
    assert totals['due_outstanding_cents']==0
    with pytest.raises(ValueError):attempt(ledger_backend,tid,bill,service,key='different-attempt')
    with pytest.raises(ValueError):attempt(ledger_backend,tid,bill,service,scenario='failed')
    assert len(rows(ledger_backend,'billing_mock_jobs'))==1
    for table in ('pilot_instructions','pilot_financial_entries','engine_cap_entries','engine_entitlement_entries'):assert rows(ledger_backend,table)==[]


def test_failed_and_partial_attempts_only_retry_confirmed_remainder(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    failed=attempt(ledger_backend,tid,bill,service,scenario='failed')
    billing.submit('HC076',tid,failed,ledger_backend,now=NOW);billing.reconcile('HC076',tid,failed,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['failed_attempt_cents']==867
    partial=attempt(ledger_backend,tid,bill,service,key='retry-partial',scenario='partial')
    billing.submit('HC076',tid,partial,ledger_backend,now=NOW);billing.reconcile('HC076',tid,partial,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['collected_cents']==433
    final=attempt(ledger_backend,tid,bill,service,key='retry-remaining')
    assert next(r for r in rows(ledger_backend,'billing_attempts') if r['id']==final)['amount_cents']==434
    billing.submit('HC076',tid,final,ledger_backend,now=NOW);billing.reconcile('HC076',tid,final,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['collected_cents']==867
    assert summary(ledger_backend,tid)['outstanding_cents']==9533


def test_timeout_retains_reservation_until_provider_reconciliation(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    aid=attempt(ledger_backend,tid,bill,service,scenario='timeout')
    assert billing.submit('HC076',tid,aid,ledger_backend,now=NOW)['status']=='uncertain'
    with pytest.raises(ValueError,match='reserved'):attempt(ledger_backend,tid,bill,service,key='unsafe-retry')
    assert summary(ledger_backend,tid)['pending_cents']==867
    assert billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)['accepted']
    assert summary(ledger_backend,tid)['collected_cents']==867


def test_reversal_before_confirmation_and_late_callback_do_not_double_credit(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    aid=attempt(ledger_backend,tid,bill,service,scenario='reversal')
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW)
    provider=MockCollectionProvider(ledger_backend)
    first=provider.status(aid);returned=provider.status(aid)
    assert billing.ingest_event('HC076',tid,aid,returned['payload'],returned['signature'],ledger_backend,now=NOW)['accepted']
    assert summary(ledger_backend,tid)['collected_cents']==0 and summary(ledger_backend,tid)['reversed_cents']==867
    late=billing.ingest_event('HC076',tid,aid,first['payload'],first['signature'],ledger_backend,now=NOW)
    assert late['stale'] and summary(ledger_backend,tid)['collected_cents']==0
    retry=attempt(ledger_backend,tid,bill,service,key='after-return')
    billing.submit('HC076',tid,retry,ledger_backend,now=NOW);billing.reconcile('HC076',tid,retry,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['collected_cents']==867
    assert summary(ledger_backend,tid)['gross_collected_cents']==1734


def test_explicit_mock_refund_is_bounded_and_does_not_imply_real_refund_right(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    aid=attempt(ledger_backend,tid,bill,service)
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW);billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)
    with pytest.raises(ValueError,match='reviewer'):billing.request_refund('HC076',tid,aid,owner,'refund',ledger_backend,now=NOW)
    refunded=billing.request_refund('HC076',tid,aid,reviewer,'refund',ledger_backend,now=NOW)
    assert refunded['accepted'] and summary(ledger_backend,tid)['refunded_cents']==867
    assert summary(ledger_backend,tid)['collected_cents']==0
    assert billing.request_refund('HC076',tid,aid,reviewer,'refund',ledger_backend,now=NOW)['duplicate']
    with pytest.raises(ValueError):billing.request_refund('HC076',tid,aid,reviewer,'second-refund',ledger_backend,now=NOW)
    assert billing.statement('HC076',tid,ledger_backend)['commercial_rules']['refund_eligibility']=='not_specified_not_invented'


@pytest.mark.parametrize('field,value,expected',[
    ('bill_id','foreign-bill','provider_reference_mismatch'),('provider_ref','wrong-reference','provider_reference_mismatch'),
    ('currency','USD','provider_reference_mismatch'),('gross_cents',868,'provider_amount_exceeds_authorization'),
    ('status','pending','invalid_zero_outcome'),
])
def test_wrong_callbacks_are_quarantined_without_balance_change(field,value,expected):
    from src.daycover.ledger_repository import configured_repository
    repo=configured_repository();owner,reviewer,service,p,tid,bill=setup(repo)
    aid=attempt(repo,tid,bill,service);billing.submit('HC076',tid,aid,repo,now=NOW)
    provider=MockCollectionProvider(repo);envelope=provider.status(aid)
    bad=dict(envelope['payload']);bad[field]=value
    with repo.transaction() as c:signature=provider.sign(c,bad)
    rejected=billing.ingest_event('HC076',tid,aid,bad,signature,repo,now=NOW)
    assert rejected['quarantined'] and rejected['reason']==expected
    assert summary(repo,tid)['collected_cents']==0
    assert billing.ingest_event('HC076',tid,aid,envelope['payload'],'0'*64,repo,now=NOW)['reason']=='invalid_mock_signature'
    assert billing.ingest_event('HC076',tid,aid,envelope['payload'],envelope['signature'],repo,now=NOW)['accepted']
    assert summary(repo,tid)['collected_cents']==867
    assert billing.statement('HC076',tid,repo)['review_required']


def test_revocation_cancels_unsent_and_reconciles_already_submitted(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    aid=attempt(ledger_backend,tid,bill,service)
    billing.authorize('HC076',tid,owner,'revoke',ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['pending_cents']==0
    assert billing.submit('HC076',tid,aid,ledger_backend,now=NOW)['status']=='canceled_unsubmitted'
    assert rows(ledger_backend,'billing_mock_jobs')==[]
    billing.authorize('HC076',tid,owner,'grant',ledger_backend,now=NOW)
    nextaid=attempt(ledger_backend,tid,bill,service,key='after-reauthorization')
    billing.submit('HC076',tid,nextaid,ledger_backend,now=NOW)
    billing.authorize('HC076',tid,owner,'revoke',ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['pending_cents']==867
    billing.reconcile('HC076',tid,nextaid,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['collected_cents']==867


def test_only_one_concurrent_attempt_can_reserve_a_bill(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    def create(i):
        try:return attempt(ledger_backend,tid,bill,service,key='parallel-'+str(i))
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(create,range(4)))
    assert sum(bool(x) for x in results)==1
    assert summary(ledger_backend,tid)['pending_cents']==867


def test_fee_sensitivity_keeps_risk_price_and_income_claims_separate():
    output=billing.cost_scenarios()
    assert Decimal(output['scenarios']['selected_monthly']['expected_collection_cost_cents'])==300
    assert Decimal(output['scenarios']['unselected_weekly_comparison']['expected_collection_cost_cents'])==1300
    assert output['scenarios']['selected_monthly']['annual_premium_cents']==10400
    assert not output['actual_fee_quote_verified'] and not output['risk_premium_recalculated'] and not output['income_affordability_verified']
    with pytest.raises(ValueError):billing.cost_scenarios(failure_rate=Decimal('NaN'))


def test_lost_provider_response_retries_same_job_without_new_authorization(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    aid=attempt(ledger_backend,tid,bill,service)
    class CrashAfterProvider(MockCollectionProvider):
        def submit(self,a):super().submit(a);raise RuntimeError('Injected crash after provider acceptance')
    with pytest.raises(RuntimeError):billing.submit('HC076',tid,aid,ledger_backend,provider=CrashAfterProvider(ledger_backend),now=NOW)
    assert summary(ledger_backend,tid)['pending_cents']==867 and summary(ledger_backend,tid)['collected_cents']==0
    assert len(rows(ledger_backend,'billing_mock_jobs'))==1
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW)
    billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)
    assert len(rows(ledger_backend,'billing_mock_jobs'))==1 and summary(ledger_backend,tid)['collected_cents']==867


def test_callback_before_acknowledgement_cannot_regress_confirmed_status(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend);aid=attempt(ledger_backend,tid,bill,service)
    class EarlyCallback(MockCollectionProvider):
        def submit(self,a):
            ack=super().submit(a);event=super().status(a['id'])
            assert billing.ingest_event('HC076',tid,a['id'],event['payload'],event['signature'],ledger_backend,now=NOW)['accepted']
            return ack
    result=billing.submit('HC076',tid,aid,ledger_backend,provider=EarlyCallback(ledger_backend),now=NOW)
    assert result['status']=='confirmed' and result['collection_confirmed']
    assert summary(ledger_backend,tid)['collected_cents']==867
    assert billing.submit('HC076',tid,aid,ledger_backend,now=NOW)['duplicate']


def test_callback_posting_failure_rolls_back_receipt_and_ledger(ledger_backend,monkeypatch):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend);aid=attempt(ledger_backend,tid,bill,service)
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW)
    event=MockCollectionProvider(ledger_backend).status(aid);original=billing._post
    def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('Injected ledger interruption')
    monkeypatch.setattr(billing,'_post',fail)
    with pytest.raises(RuntimeError):billing.ingest_event('HC076',tid,aid,event['payload'],event['signature'],ledger_backend,now=NOW)
    assert rows(ledger_backend,'billing_provider_events')==[]
    assert len(rows(ledger_backend,'pilot_billing_entries'))==12
    assert summary(ledger_backend,tid)['pending_cents']==867
    monkeypatch.setattr(billing,'_post',original)
    assert billing.ingest_event('HC076',tid,aid,event['payload'],event['signature'],ledger_backend,now=NOW)['accepted']
    assert summary(ledger_backend,tid)['collected_cents']==867


def test_forged_terminal_increase_is_quarantined_after_retry(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend);aid=attempt(ledger_backend,tid,bill,service,scenario='partial')
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW);billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)
    retry=attempt(ledger_backend,tid,bill,service,key='confirmed-remainder')
    billing.submit('HC076',tid,retry,ledger_backend,now=NOW);billing.reconcile('HC076',tid,retry,ledger_backend,now=NOW)
    provider=MockCollectionProvider(ledger_backend);forged=provider.status(aid)['payload']
    forged.update(sequence=2,event_id='mock-inconsistent-terminal-capture',status='confirmed',gross_cents=867)
    with ledger_backend.transaction() as c:signature=provider.sign(c,forged)
    result=billing.ingest_event('HC076',tid,aid,forged,signature,ledger_backend,now=NOW)
    assert result['quarantined']
    assert summary(ledger_backend,tid)['collected_cents']==867


def test_pending_is_not_failed_and_unknown_submission_cannot_be_guessed(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend);aid=attempt(ledger_backend,tid,bill,service,scenario='pending')
    assert billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)['status']=='uncertain'
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW)
    billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)
    assert summary(ledger_backend,tid)['pending_cents']==867 and summary(ledger_backend,tid)['failed_attempt_cents']==0
    with pytest.raises(ValueError):attempt(ledger_backend,tid,bill,service,key='do-not-retry-pending')


def test_collection_after_authorization_expiry_reconciles_but_new_debits_are_blocked(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend);aid=attempt(ledger_backend,tid,bill,service)
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW)
    late=NOW.replace(year=2028)
    billing.reconcile('HC076',tid,aid,ledger_backend,now=late)
    with pytest.raises(ValueError,match='authorization'):attempt(ledger_backend,tid,bill,service,key='expired',now=late)
    assert summary(ledger_backend,tid)['collected_cents']==867
    assert billing.statement('HC076',tid,ledger_backend,as_of=late.date())['authorization']['status']=='expired_or_canceled'


def test_billing_does_not_lapse_or_reprice_coverage_or_change_caps(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    before=pilot_store.policy('HC076')
    aid=attempt(ledger_backend,tid,bill,service)
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW);billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)
    after=pilot_store.policy('HC076')
    assert after['remaining_combined_sgd']==before['remaining_combined_sgd']==180
    assert after['billing']['collected_sgd']==0
    assert after['billing']['mock_billing']['summary']['collected_cents']==867
    assert after['simulation_lifecycle_state']==before['simulation_lifecycle_state']
    assert rows(ledger_backend,'engine_entitlement_entries')==[] and rows(ledger_backend,'pilot_financial_entries')==[]


def test_billing_api_is_scoped_and_customer_authorization_is_separate(ledger_backend,monkeypatch):
    monkeypatch.setenv('DAYCOVER_AUTH_MODE','local')
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    foreign=auth.provision('foreign_billing_service','service')
    for pid in (owner,reviewer,service):auth.set_grant(pid,p['merchant_id'])
    client=TestClient(app)
    def login(alias,password):
        r=client.post('/api/v1/auth/login',json={'alias':alias,'password':password});assert r.status_code==200
        return {'Authorization':'Bearer '+r.json()['access_token']}
    ch=login('billing_owner','local-owner-test-password');rh=login('billing_reviewer','local-review-test-password')
    sh={'Authorization':'Bearer '+auth.issue_service(service,['coverage:read','billing:collect','billing:reconcile'])['access_token']}
    fh={'Authorization':'Bearer '+auth.issue_service(foreign,['coverage:read','billing:collect'])['access_token']}
    base='/api/v1/billing/HC076/'+tid
    assert client.get(base).status_code==401 and client.get(base,headers=fh).status_code==404
    assert client.post(base+'/authorization',json={'action':'grant','simulation_only':True},headers=sh).status_code==403
    assert client.post(base+'/attempts',json={'bill_id':bill,'idempotency_key':'api-attempt','scenario':'success'},headers=ch).status_code==403
    forged={'bill_id':bill,'idempotency_key':'api-attempt','scenario':'success','amount_cents':100000,'sponsor_funded_cents':10400}
    assert client.post(base+'/attempts',json=forged,headers=sh).status_code==422
    created=client.post(base+'/attempts',json={k:v for k,v in forged.items() if k in ('bill_id','idempotency_key','scenario')},headers=sh)
    assert created.status_code==200,created.text
    path=base+'/attempts/'+created.json()['attempt_id']
    assert client.post(path+'/submit',headers=sh).status_code==200
    assert client.get(base,headers=ch).json()['summary']['collected_cents']==0
    assert client.post(path+'/reconcile',headers=sh).status_code==200
    response=client.get(base,headers=ch).json()
    assert response['summary']['collected_cents']==867 and response['real_collected_cents']==0
    assert response['authorization']['real_mandate_status']=='NOT_CONNECTED'
    assert all(not p['granted'] for p in client.get('/api/v1/consents/HC076',headers=ch).json()['permissions'])
    assert client.post(path+'/mock-refund',json={'idempotency_key':'api-refund','acknowledge_mock_only':True},headers=sh).status_code==403
    assert client.post(path+'/mock-refund',json={'idempotency_key':'api-refund','acknowledge_mock_only':True},headers=rh).status_code==200
    auth.set_grant(owner,p['merchant_id'],False)
    assert client.get(base,headers=ch).status_code==404


def test_all_twelve_collections_cannot_exceed_annual_net_obligation(ledger_backend):
    now=datetime(2026,12,31,12,tzinfo=SGT)
    owner,reviewer,service,p,tid,bill=setup(ledger_backend,start=date(2026,1,31),now=now)
    schedule=billing.statement('HC076',tid,ledger_backend,as_of=now.date())
    for invoice in schedule['bills']:
        aid=attempt(ledger_backend,tid,invoice['id'],service,key='annual-'+str(invoice['instalment']),now=now)
        billing.submit('HC076',tid,aid,ledger_backend,now=now);billing.reconcile('HC076',tid,aid,ledger_backend,now=now)
        with pytest.raises(ValueError):attempt(ledger_backend,tid,invoice['id'],service,key='duplicate-'+str(invoice['instalment']),now=now)
    result=billing.statement('HC076',tid,ledger_backend,as_of=now.date())
    assert result['summary']['collected_cents']==10400
    assert result['summary']['outstanding_cents']==0 and result['summary']['pending_cents']==0
    assert result['real_collected_cents']==0 and result['summary']['sponsor_funded_cents']==0


def test_future_bills_and_cancellation_do_not_invent_retry_lapse_or_refund_rules(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    future=billing.statement('HC076',tid,ledger_backend)['bills'][1]
    with pytest.raises(ValueError,match='Future'):attempt(ledger_backend,tid,future['id'],service,key='future')
    aid=attempt(ledger_backend,tid,bill,service)
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW);billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)
    life.transition('HC076',tid,'cancel_simulation',reviewer,NOW.date(),ledger_backend,now=NOW)
    result=billing.statement('HC076',tid,ledger_backend,as_of=NOW.date())
    assert result['summary']['collected_cents']==867 and result['summary']['refunded_cents']==0
    assert result['summary']['annual_obligation_cents']==10400
    assert result['commercial_rules']['cancellation_proration']=='not_specified_not_invented'
    with pytest.raises(ValueError):billing.authorize('HC076',tid,owner,'grant',ledger_backend,now=NOW)


def test_renewal_gets_separate_schedule_and_no_automatic_collection_authorization(ledger_backend):
    historical=datetime(2025,11,20,12,tzinfo=SGT)
    owner,reviewer,service,p,tid,bill=setup(ledger_backend,start=date(2025,11,15),now=historical)
    newterm=life.renew('HC076',DAY,'daycover-pilot-m1-2026.11-v1',ledger_backend,now=NOW)
    statement=billing.prepare('HC076',newterm['term_id'],ledger_backend,now=NOW)
    assert statement['authorization']['status']=='missing'
    assert statement['bills'][0]['id']!=bill and statement['summary']['annual_obligation_cents']==10400
    assert len(rows(ledger_backend,'billing_schedules'))==2 and len(rows(ledger_backend,'billing_bills'))==24
    with pytest.raises(ValueError):attempt(ledger_backend,newterm['term_id'],statement['bills'][0]['id'],service,key='new-term')


def test_billing_tables_and_entries_are_append_only(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend);aid=attempt(ledger_backend,tid,bill,service)
    billing.submit('HC076',tid,aid,ledger_backend,now=NOW);billing.reconcile('HC076',tid,aid,ledger_backend,now=NOW)
    billing.request_refund('HC076',tid,aid,reviewer,'immutable-refund',ledger_backend,now=NOW)
    for table in ('billing_schedules','billing_bills','billing_authorizations','billing_attempts','billing_dispatches','billing_provider_events','billing_entry_links','billing_refund_requests','billing_mock_refunds','pilot_billing_entries'):
        with pytest.raises(Exception):
            with ledger_backend.transaction() as c:c.execute('DELETE FROM '+table)


def test_v6_migration_rollback_preserves_terms_receipts_and_entitlements(ledger_backend,monkeypatch):
    from src.daycover import ledger_migrations,evidence_engine
    from test_evidence_engine import setup as engine_setup,weather
    reviewer,p,term=engine_setup(ledger_backend)
    weather(ledger_backend,reviewer,p,DAY)
    evidence_engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    before=rows(ledger_backend,'engine_entitlement_entries')
    with ledger_backend.transaction() as c:
        for table in ('settlement_mock_wallet_entries','settlement_cash_entries','settlement_provider_events','settlement_dispatch_attempts','settlement_instruction_events','settlement_mock_jobs','settlement_mock_key','settlement_instructions','settlement_outbox','settlement_recipient_reviews','settlement_recipients'):
            c.execute('DROP TABLE '+table)
        for table in ('billing_mock_refunds','billing_mock_jobs','billing_mock_key','billing_refund_requests','billing_entry_links','billing_provider_events','billing_dispatches','billing_attempts','billing_authorizations','billing_bills','billing_schedules'):
            c.execute('DROP TABLE '+table)
        c.execute('DROP TABLE collection_ignored_events');c.execute('DROP TABLE collection_accrual_entries')
        c.execute('DELETE FROM pilot_schema_migrations WHERE version>=6')
    original=ledger_migrations._apply
    def interrupted(native,backend,script):
        original(native,backend,script)
        if 'CREATE TABLE billing_schedules' in script:raise RuntimeError('Injected billing migration failure')
    monkeypatch.setattr(ledger_migrations,'_apply',interrupted)
    with pytest.raises(RuntimeError):ledger_backend.migrate()
    native=ledger_backend._connect()
    try:assert native.execute('SELECT COUNT(*) AS n FROM pilot_schema_migrations').fetchone()['n']==5
    finally:native.close()
    monkeypatch.setattr(ledger_migrations,'_apply',original)
    ledger_backend.migrate();ledger_backend.migrate()
    assert rows(ledger_backend,'engine_entitlement_entries')==before
    assert evidence_engine.history('HC076',ledger_backend)['net_entitlement_cents']==6000
    assert rows(ledger_backend,'pilot_billing_entries')==[]


def test_affordability_is_hypothetical_net_income_math_not_digital_receipt_inference():
    result=billing.cost_scenarios()
    first=result['hypothetical_affordability_scenarios'][0]
    assert first['monthly_net_income_assumption_cents']==50000
    assert Decimal(first['annual_premium_share_percent'])==Decimal(10400)*100/(Decimal(50000)*12)
    assert not first['customer_income_verified']
    with pytest.raises(ValueError):billing.cost_scenarios(monthly_net_income_assumptions_cents=(0,))


def test_unapproved_funded_credit_is_not_silently_counted_or_used_to_lapse_cover(ledger_backend):
    owner,reviewer,service,p,tid,bill=setup(ledger_backend)
    with ledger_backend.transaction() as c:
        c.execute('INSERT INTO pilot_billing_entries VALUES (?,?,?,?,?,?,?,?,?,?)',('unapproved-credit',p['policy_id'],p['policy_period_id'],'credit',-100,'SGD',str(DAY),None,'unapproved-credit',NOW.isoformat()))
        c.execute('INSERT INTO billing_entry_links VALUES (?,?,NULL,NULL)',('unapproved-credit',bill))
    with pytest.raises(ValueError,match='Unsupported funded credit'):billing.statement('HC076',tid,ledger_backend)
    coverage=pilot_store.policy('HC076')
    assert coverage['remaining_combined_sgd']==180
    assert coverage['billing']['mock_billing']['status']=='REVIEW_REQUIRED'
