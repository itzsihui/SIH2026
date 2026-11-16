"""Reviewed-evidence decisions and lifecycle on SQLite and real PostgreSQL."""
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from src.daycover import auth, daily_evidence as daily, evidence_engine as engine, policy_lifecycle as life, pilot_store
from src.daycover.api import app
from src.daycover.contracts import M1_VERSION
from src.daycover.ingestion import SGT
from src.daycover.ledger_repository import SqlLedgerRepository
from src.daycover.weather_ingestion import Ingestor,Response

DAY=date(2026,11,15)
NOW=datetime(2026,11,20,12,tzinfo=SGT)
REF='fixture://phase6-reviewed-source'


def rows(repo,table):
    with repo.transaction() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table).fetchall()]


def setup(repo,start=DAY):
    reviewer=auth.provision('engine_reviewer','reviewer','local-reviewer-test-password')
    policy=pilot_store.enrol('HC076',start,'S79','south')
    term=life.overview('HC076',repo,as_of=start)['terms'][0]
    life.transition('HC076',term['term_id'],'activate_simulation',reviewer,repository=repo,now=NOW)
    return reviewer,policy,term


def weather(repo,reviewer,p,day,value=151,*,resolve=False,closed=False,now=NOW):
    start=datetime.combine(day,datetime.min.time(),SGT)
    values=value if isinstance(value,list) else [value]*24
    payload={'code':0,'data':{'regionMetadata':[{'name':r,'labelLocation':{'latitude':1.3,'longitude':103.8}} for r in ('north','south','east','west','central')],
                'items':[{'timestamp':(start+timedelta(hours=i)).isoformat(),'readings':{'psi_twenty_four_hourly':{'south':v}}} for i,v in enumerate(values)]}}
    class Clock:
        def __init__(self):self.now=now
        def __call__(self):return self.now
        def sleep(self,seconds):self.now+=timedelta(seconds=seconds)
    class Client:
        def get(self,*args):return Response(200,json.dumps(payload).encode())
    clock=Clock();worker=Ingestor(repo,Client(),clock=clock,sleep=clock.sleep)
    assert worker.run(worker.start('psi',day))['status']=='complete'
    version=next(r for r in rows(repo,'weather_station_versions') if r['station']=='REGION_SOUTH')
    with repo.transaction() as c:mapping=daily._mapping(c,'REGION_SOUTH',day)
    if not mapping:daily.review_mapping(version['id'],day,day,'approved',reviewer,REF,repo)
    if resolve:
        for observation in rows(repo,'pilot_observations'):
            at=datetime.fromisoformat(observation['observed_at']).astimezone(SGT)
            if at.date()==day and observation['station']=='REGION_SOUTH' and float(observation['value'])==values[at.hour]:
                daily.review_revision(observation['id'],reviewer,REF,repo)
    candidate=daily.build_daily('psi','REGION_SOUTH',day,repo,now=now)
    assert not candidate['blocking_reasons'],candidate['blocking_reasons']
    daily.review_daily(candidate.get('candidate_aggregate_id',candidate['aggregate_id']),'final',reviewer,REF,repo,now=now)
    closure=daily.propose_closure(p['centre_id'],day,closed,'cleaning' if closed else 'explicit_open',REF,hashlib.sha256(str(day).encode()).hexdigest(),repo)
    if not closure['duplicate']:daily.review_closure(closure['closure_id'],'approved',reviewer,REF,repo)


def test_qualified_psi_entitlement_never_creates_payment_and_rain_stays_pending(ledger_backend):
    reviewer,p,term=setup(ledger_backend)
    weather(ledger_backend,reviewer,p,DAY)
    result=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    rain,haze=result['decisions']
    assert rain['status']=='PENDING' and rain['target_entitlement_sgd']==0
    assert haze['status']=='TRIGGERED' and haze['target_entitlement_sgd']==60
    assert haze['evidence']['psi_aggregate_id'] and haze['evidence']['selection_id']
    assert result['used']['haze_days']==1 and result['used']['total']==60
    assert result['net_entitlement_cents']==6000 and not haze['disbursed']
    duplicate=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert all(r['duplicate'] for r in duplicate['decisions'])
    assert len(rows(ledger_backend,'engine_cap_entries'))==1
    for table in ('pilot_instructions','pilot_settlement_attempts','pilot_financial_entries'):assert rows(ledger_backend,table)==[]
    assert pilot_store.policy('HC076')['remaining_combined_sgd']==120
    assert pilot_store.history('HC076')['claims_count']==0
    assert pilot_store.history('HC076')['reviewed_evidence_entitlements']['net_entitlement_cents']==6000
    with pytest.raises(ValueError,match='cannot share'):pilot_store.simulate('HC076',DAY,'haze',None,151,None,False,'S79','south')


def test_caps_day_counts_and_calendar_year_dont_reset(ledger_backend):
    start=date(2026,12,30);now=datetime(2027,1,10,12,tzinfo=SGT)
    reviewer,p,term=setup(ledger_backend,start)
    for i in range(4):weather(ledger_backend,reviewer,p,start+timedelta(days=i),151,now=now)
    result=engine.evaluate('HC076',start,start+timedelta(days=3),ledger_backend,now=now)
    assert [r['target_entitlement_sgd'] for r in result['decisions'] if r['peril']=='haze']==[60,60,30,0]
    assert result['used']['haze_days']==3 and result['used']['haze_sgd']==150
    assert result['used']['total']==150
    assert len(rows(ledger_backend,'engine_cap_entries'))==3


def test_haze_two_day_threshold_requires_qualified_previous_day(ledger_backend):
    reviewer,p,term=setup(ledger_backend)
    weather(ledger_backend,reviewer,p,DAY,110)
    first=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert first['decisions'][1]['status']=='PENDING'
    weather(ledger_backend,reviewer,p,DAY-timedelta(days=1),110)
    second=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert second['decisions'][1]['target_entitlement_sgd']==30
    assert second['used']['haze_days']==1


def test_late_closure_correction_requires_review_and_never_restores_cap(ledger_backend):
    reviewer,p,term=setup(ledger_backend);weather(ledger_backend,reviewer,p,DAY)
    original=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    correction=daily.propose_closure(p['centre_id'],DAY,True,'cleaning',REF,'a'*64,ledger_backend)
    daily.review_closure(correction['closure_id'],'approved',reviewer,REF,ledger_backend)
    proposal=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert proposal['decisions'][1]['effect']=='review_required'
    assert proposal['net_entitlement_cents']==6000
    plan=engine.plan_replay('HC076',term['term_id'],DAY,ledger_backend,now=NOW)
    reviewed=engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    history=engine.history('HC076',ledger_backend)
    assert history['net_entitlement_cents']==0 and history['consumed_cap_cents']==6000
    assert reviewed['used']['haze_days']==1 and reviewed['used']['haze_sgd']==60
    assert engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)['duplicate']
    assert original['decisions'][1]['target_entitlement_sgd']==60
    assert len(rows(ledger_backend,'engine_entitlement_entries'))==2
    assert rows(ledger_backend,'pilot_financial_entries')==[]


def test_pending_correction_preserves_existing_entitlement_and_stale_plans_refuse(ledger_backend):
    reviewer,p,term=setup(ledger_backend);weather(ledger_backend,reviewer,p,DAY)
    engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    plan=engine.plan_replay('HC076',term['term_id'],DAY,ledger_backend,now=NOW)
    daily.propose_closure(p['centre_id'],DAY,True,'works',REF,'b'*64,ledger_backend)
    with pytest.raises(ValueError,match='changed'):engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    new=engine.plan_replay('HC076',term['term_id'],DAY,ledger_backend,now=NOW)
    engine.approve_replay('HC076',new['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']==6000
    assert engine.history('HC076',ledger_backend)['consumed_cap_cents']==6000


def test_upward_correction_topup_does_not_consume_an_extra_haze_day(ledger_backend):
    reviewer,p,term=setup(ledger_backend)
    weather(ledger_backend,reviewer,p,DAY-timedelta(days=1),110)
    weather(ledger_backend,reviewer,p,DAY,110)
    engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    weather(ledger_backend,reviewer,p,DAY,151,resolve=True)
    engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    plan=engine.plan_replay('HC076',term['term_id'],DAY,ledger_backend,now=NOW)
    result=engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    assert result['used']['haze_days']==1 and result['used']['haze_sgd']==60
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']==6000
    assert sorted(r['amount_cents'] for r in rows(ledger_backend,'engine_cap_entries'))==[3000,3000]


def test_prospective_cancellation_expiry_and_explicit_renewal_keep_old_terms(ledger_backend):
    reviewer,p,term=setup(ledger_backend,date(2024,2,29))
    before=rows(ledger_backend,'pilot_policies')[0]
    with pytest.raises(ValueError):life.renew('HC076',date(2025,3,1),M1_VERSION,ledger_backend,now=NOW)
    renewal=life.renew('HC076',date(2025,2,28),M1_VERSION,ledger_backend,now=NOW)
    assert renewal['end']=='2026-02-27'
    assert life.renew('HC076',date(2025,2,28),M1_VERSION,ledger_backend,now=NOW)['duplicate']
    life.transition('HC076',term['term_id'],'record_expiry',reviewer,repository=ledger_backend,now=NOW)
    assert rows(ledger_backend,'pilot_policies')[0]==before
    with pytest.raises(LookupError):engine.evaluate('HC076',date(2026,2,28),date(2026,2,28),ledger_backend,now=NOW)
    # Future anniversary acceptance is explicit and does not imply activation.
    nextterm=life.renew('HC076',date(2026,2,28),M1_VERSION,ledger_backend,now=NOW)
    lifecycle=life.overview('HC076',ledger_backend,as_of=DAY)
    assert lifecycle['terms'][-1]['state']=='ENROLLED_SIMULATION'
    life.transition('HC076',nextterm['term_id'],'activate_simulation',reviewer,repository=ledger_backend,now=NOW)
    cancelday=date(2026,11,21)
    life.transition('HC076',nextterm['term_id'],'cancel_simulation',reviewer,cancelday,ledger_backend,now=NOW)
    assert life.overview('HC076',ledger_backend,as_of=cancelday)['terms'][-1]['state']=='CANCELED_SIMULATION'
    assert life.transition('HC076',nextterm['term_id'],'cancel_simulation',reviewer,cancelday,ledger_backend,now=NOW+timedelta(days=5))['duplicate']
    with pytest.raises(ValueError):life.renew('HC076',date(2027,2,28),M1_VERSION,ledger_backend,now=NOW)


def test_full_and_sliced_restarted_runs_have_same_decisions_and_balances(ledger_backend,tmp_path,monkeypatch):
    start=DAY-timedelta(days=2)
    def scenario(repo,sliced):
        reviewer,p,term=setup(repo,start)
        for i in range(3):weather(repo,reviewer,p,start+timedelta(days=i),151)
        if sliced:
            output=[]
            for i in range(3):
                # New repository objects reconstruct all state; no in-memory cap cursor.
                reopened=SqlLedgerRepository(repo.backend,path=repo.path,url=repo.url,schema=repo.schema)
                output+=engine.evaluate('HC076',start+timedelta(days=i),start+timedelta(days=i),reopened,now=NOW)['decisions']
        else:output=engine.evaluate('HC076',start,DAY,repo,now=NOW)['decisions']
        return [(r['day'],r['peril'],r['status'],r['target_entitlement_sgd']) for r in output],engine.history('HC076',repo)['net_entitlement_cents']
    full=scenario(ledger_backend,False)
    other=SqlLedgerRepository(path=tmp_path/'sliced.sqlite3');other.migrate()
    with monkeypatch.context() as m:
        m.setenv('DAYCOVER_PILOT_BACKEND','sqlite');m.setenv('DAYCOVER_PILOT_DB',str(other.path));m.delenv('DAYCOVER_PILOT_DATABASE_URL',raising=False)
        sliced=scenario(other,True)
    assert full==sliced


def test_out_of_order_events_only_apply_via_reviewed_ordered_plan(ledger_backend):
    start=DAY-timedelta(days=1)
    reviewer,p,term=setup(ledger_backend,start)
    weather(ledger_backend,reviewer,p,start,151);weather(ledger_backend,reviewer,p,DAY,151)
    engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    earlier=engine.evaluate('HC076',start,start,ledger_backend,now=NOW)
    assert all(r['effect']=='review_required' for r in earlier['decisions'])
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']==6000
    plan=engine.plan_replay('HC076',term['term_id'],DAY,ledger_backend,now=NOW)
    result=engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    assert result['used']['haze_days']==2 and result['used']['total']==120
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']==12000
    assert all(r['duplicate'] for r in engine.evaluate('HC076',start,DAY,ledger_backend,now=NOW)['decisions'])


def test_concurrent_duplicate_requests_do_not_duplicate_caps_or_entitlement(ledger_backend):
    reviewer,p,term=setup(ledger_backend);weather(ledger_backend,reviewer,p,DAY)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW),range(4)))
    assert sum(not r['decisions'][1]['duplicate'] for r in results)==1
    assert len(rows(ledger_backend,'engine_cap_entries'))==1
    assert len(rows(ledger_backend,'engine_entitlement_entries'))==1
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']==6000


def test_renewal_uses_new_period_with_fresh_caps_without_rewriting_prior_term(ledger_backend):
    reviewer,p,term=setup(ledger_backend,date(2025,11,15))
    oldday=date(2025,11,15)
    weather(ledger_backend,reviewer,p,oldday,151)
    engine.evaluate('HC076',oldday,oldday,ledger_backend,now=NOW)
    accepted=rows(ledger_backend,'pilot_policies')[0]
    renewal=life.renew('HC076',DAY,M1_VERSION,ledger_backend,now=NOW)
    weather(ledger_backend,reviewer,p,DAY,151)
    inactive=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert inactive['decisions'][1]['status']=='INACTIVE'
    life.transition('HC076',renewal['term_id'],'activate_simulation',reviewer,repository=ledger_backend,now=NOW)
    # Explicit activation changes a previously finalized inactive assessment: review required.
    plan=engine.plan_replay('HC076',renewal['term_id'],DAY,ledger_backend,now=NOW)
    result=engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    assert result['used']['total']==60 and result['used']['haze_days']==1
    assert daily.select_evidence('HC076',DAY,ledger_backend,now=NOW,persist=False)['haze_today_ready']
    assert pilot_store.policy('HC076')['policy_start']==str(DAY)
    with ledger_backend.transaction() as c:
        assert c.used(term['period_id'])['total']==60
        assert c.used(renewal['period_id'])['total']==60
    assert rows(ledger_backend,'pilot_policies')[0]==accepted
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']==12000


def test_five_haze_days_and_both_perils_share_frozen_caps(ledger_backend,monkeypatch):
    import test_daily_evidence as fixtures
    monkeypatch.setattr(fixtures,'NOW',NOW)
    ingest_rain=fixtures.ingest
    monkeypatch.setattr(daily,'RAIN_TIMING_VERIFIED',True) # Test-only source-method fixture.
    reviewer,p,term=setup(ledger_backend)
    weather(ledger_backend,reviewer,p,DAY)
    ingest_rain(ledger_backend,'rain','S79',.25,day=DAY)
    version=next(r for r in rows(ledger_backend,'weather_station_versions') if r['station']=='S79')
    daily.review_mapping(version['id'],DAY,DAY,'approved',reviewer,REF,ledger_backend)
    rain=daily.build_daily('rain','S79',DAY,ledger_backend,now=NOW)
    daily.review_daily(rain['aggregate_id'],'final',reviewer,REF,ledger_backend,now=NOW)
    first=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert [r['target_entitlement_sgd'] for r in first['decisions']]==[30,60]
    for i in range(1,4):weather(ledger_backend,reviewer,p,DAY+timedelta(days=i),151)
    last=engine.evaluate('HC076',DAY+timedelta(days=1),DAY+timedelta(days=3),ledger_backend,now=NOW)
    assert last['used']['total']==180 and last['used']['haze_sgd']==150
    assert len(rows(ledger_backend,'engine_cap_entries'))==4


def test_entitlement_failure_rolls_back_whole_decision_slice(ledger_backend,monkeypatch):
    reviewer,p,term=setup(ledger_backend);weather(ledger_backend,reviewer,p,DAY)
    original=engine._record
    def failed(*args,**kwargs):
        result=original(*args,**kwargs)
        if args[3]=='haze':raise RuntimeError('Injected failure after cap/entitlement posting')
        return result
    monkeypatch.setattr(engine,'_record',failed)
    with pytest.raises(RuntimeError):engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    for table in ('engine_decisions','engine_cap_entries','engine_entitlement_entries','engine_period_modes'):
        assert rows(ledger_backend,table)==[]
    monkeypatch.setattr(engine,'_record',original)
    assert engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)['net_entitlement_cents']==6000


def test_canceled_event_dates_are_inactive_and_cancellation_cannot_be_backdated(ledger_backend):
    reviewer,p,term=setup(ledger_backend)
    with pytest.raises(ValueError):life.transition('HC076',term['term_id'],'cancel_simulation',reviewer,DAY,ledger_backend,now=NOW)
    life.transition('HC076',term['term_id'],'cancel_simulation',reviewer,DAY,ledger_backend,now=NOW-timedelta(days=6))
    weather(ledger_backend,reviewer,p,DAY,151)
    result=engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert all(r['status']=='INACTIVE' for r in result['decisions'])
    assert result['net_entitlement_cents']==0
    assert rows(ledger_backend,'engine_cap_entries')==[]
    with pytest.raises(ValueError):pilot_store.simulate('HC076',DAY,'haze',None,151,None,False,'S79','south')


def test_scoped_api_forbids_cross_merchant_and_forged_weather_or_amount(ledger_backend,monkeypatch):
    monkeypatch.setenv('DAYCOVER_AUTH_MODE','local')
    reviewer,p,term=setup(ledger_backend);weather(ledger_backend,reviewer,p,DAY)
    customer=auth.provision('engine_customer','customer','local-customer-test-password')
    service=auth.provision('engine_service','service')
    foreign=auth.provision('foreign_service','service')
    auth.set_grant(customer,p['merchant_id']);auth.set_grant(service,p['merchant_id']);auth.set_grant(reviewer,p['merchant_id'])
    client=TestClient(app)
    sh={'Authorization':'Bearer '+auth.issue_service(service,['coverage:read','decision:evaluate'])['access_token']}
    fh={'Authorization':'Bearer '+auth.issue_service(foreign,['coverage:read','decision:evaluate'])['access_token']}
    def sign(alias,password):return {'Authorization':'Bearer '+client.post('/api/v1/auth/login',json={'alias':alias,'password':password}).json()['access_token']}
    ch=sign('engine_customer','local-customer-test-password');rh=sign('engine_reviewer','local-reviewer-test-password')
    path='/api/v1/engine-decisions/HC076/evaluate';payload={'start':str(DAY),'end':str(DAY)}
    assert client.post(path,json=payload).status_code==401
    assert client.post(path,json=payload,headers=fh).status_code==404
    assert client.post(path,json=payload,headers=ch).status_code==403
    assert client.post(path,json=payload|{'amount':1000,'psi':500},headers=sh).status_code==422
    result=client.post(path,json=payload,headers=sh)
    assert result.status_code==200,result.text
    assert result.json()['net_entitlement_cents']==6000
    assert client.post('/api/v1/lifecycle/HC076/transition',json={'term_id':term['term_id'],'action':'cancel_simulation','effective_on':'2026-11-21'},headers=sh).status_code==403
    replay=client.post('/api/v1/engine-decisions/HC076/replay',json={'term_id':term['term_id'],'through_day':str(DAY)},headers=sh)
    assert replay.status_code==200,replay.text
    approval='/api/v1/engine-decisions/HC076/replay/'+replay.json()['plan_id']+'/approve'
    assert client.post(approval,json={'source_ref':REF},headers=sh).status_code==403
    assert client.post(approval,json={'source_ref':REF},headers=rh).status_code==200
    auth.set_grant(service,p['merchant_id'],False)
    assert client.get('/api/v1/engine-decisions/HC076',headers=sh).status_code==404


def test_haze_five_day_limit_is_unique_covered_days(ledger_backend):
    start=DAY-timedelta(days=1)
    reviewer,p,term=setup(ledger_backend,start)
    for i in range(-1,6):weather(ledger_backend,reviewer,p,start+timedelta(days=i),110)
    result=engine.evaluate('HC076',start,start+timedelta(days=5),ledger_backend,now=NOW)
    assert [r['target_entitlement_sgd'] for r in result['decisions'] if r['peril']=='haze']==[30,30,30,30,30,0]
    assert result['used']['haze_days']==5 and result['used']['haze_sgd']==150


def test_migration_v5_failure_preserves_v4_policy_receipts_and_caps(ledger_backend,monkeypatch):
    from src.daycover import ledger_migrations
    p=pilot_store.enrol('HC076',DAY,'S79','south')
    receipt=pilot_store.simulate('HC076',DAY,'haze',None,151,None,False,'S79','south')
    saved_policy=rows(ledger_backend,'pilot_policies')
    saved_receipts=rows(ledger_backend,'pilot_decisions')
    with ledger_backend.transaction() as c:
        for table in ('settlement_mock_wallet_entries','settlement_cash_entries','settlement_provider_events','settlement_dispatch_attempts','settlement_instruction_events','settlement_mock_jobs','settlement_mock_key','settlement_instructions','settlement_outbox','settlement_recipient_reviews','settlement_recipients'):
            c.execute('DROP TABLE '+table)
        for table in ('billing_mock_refunds','billing_mock_jobs','billing_mock_key','billing_refund_requests','billing_entry_links','billing_provider_events','billing_dispatches','billing_attempts','billing_authorizations','billing_bills','billing_schedules'):
            c.execute('DROP TABLE '+table)
        for table in ('engine_replay_reviews','engine_replay_plans','engine_entitlement_entries','engine_cap_entries','engine_decisions','engine_period_modes','engine_lifecycle_events','engine_terms'):
            c.execute('DROP TABLE '+table)
        c.execute('DELETE FROM pilot_schema_migrations WHERE version>=5')
    original=ledger_migrations._apply
    def fail(native,backend,script):
        original(native,backend,script)
        if 'CREATE TABLE engine_terms' in script:raise RuntimeError('Injected v5 interruption')
    monkeypatch.setattr(ledger_migrations,'_apply',fail)
    with pytest.raises(RuntimeError):ledger_backend.migrate()
    native=ledger_backend._connect()
    try:assert native.execute('SELECT COUNT(*) AS n FROM pilot_schema_migrations').fetchone()['n']==4
    finally:native.close()
    monkeypatch.setattr(ledger_migrations,'_apply',original)
    ledger_backend.migrate();ledger_backend.migrate()
    assert rows(ledger_backend,'pilot_policies')==saved_policy and rows(ledger_backend,'pilot_decisions')==saved_receipts
    assert len(rows(ledger_backend,'engine_terms'))==1
    assert rows(ledger_backend,'engine_period_modes')[0]['mode']=='synthetic_demo'
    assert pilot_store.policy('HC076')['remaining_combined_sgd']==120
    with pytest.raises(ValueError,match='cannot share'):engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)


def test_reviewed_ledger_and_replay_records_are_append_only(ledger_backend):
    reviewer,p,term=setup(ledger_backend);weather(ledger_backend,reviewer,p,DAY)
    engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    plan=engine.plan_replay('HC076',term['term_id'],DAY,ledger_backend,now=NOW)
    engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    for table in ('engine_terms','engine_lifecycle_events','engine_period_modes','engine_decisions','engine_cap_entries','engine_entitlement_entries','engine_replay_plans','engine_replay_reviews'):
        with pytest.raises(Exception):
            with ledger_backend.transaction() as c:c.execute('DELETE FROM '+table)


def test_cap_reservations_are_never_released_by_out_of_order_replay(ledger_backend):
    start=DAY-timedelta(days=3)
    reviewer,p,term=setup(ledger_backend,start)
    for i in range(4):weather(ledger_backend,reviewer,p,start+timedelta(days=i),151)
    # Later days consumed the whole haze subcap before the earlier event was known.
    engine.evaluate('HC076',start+timedelta(days=1),DAY,ledger_backend,now=NOW)
    assert engine.history('HC076',ledger_backend)['consumed_cap_cents']==15000
    engine.evaluate('HC076',start,start,ledger_backend,now=NOW)
    plan=engine.plan_replay('HC076',term['term_id'],DAY,ledger_backend,now=NOW)
    result=engine.approve_replay('HC076',plan['plan_id'],reviewer,REF,ledger_backend,now=NOW)
    assert result['used']['haze_sgd']==150 and result['used']['haze_days']==3
    assert engine.history('HC076',ledger_backend)['consumed_cap_cents']==15000
    assert engine.history('HC076',ledger_backend)['net_entitlement_cents']>=0
    assert result['payment_execution']=='NOT_SUBMITTED'


def test_activation_and_expiry_dates_are_server_owned_and_unknown_versions_reject(ledger_backend):
    reviewer,p,term=setup(ledger_backend)
    with pytest.raises(ValueError,match='Only cancellation'):
        life.transition('HC076',term['term_id'],'activate_simulation',reviewer,DAY+timedelta(days=1),ledger_backend,now=NOW)
    with pytest.raises(ValueError,match='Unsupported accepted'):
        life.renew('HC076',date(2027,11,15),'unapproved-new-design',ledger_backend,now=NOW)
    assert len(rows(ledger_backend,'engine_terms'))==1


def test_renewed_period_version_mismatch_fails_closed(ledger_backend):
    reviewer,p,term=setup(ledger_backend,date(2025,11,15))
    renewed=life.renew('HC076',DAY,M1_VERSION,ledger_backend,now=NOW)
    with ledger_backend.transaction() as c:
        c.execute('INSERT INTO pilot_product_versions VALUES (?,?,?,?)',('invalid-period-version','{}','not-a-registry-hash','simulation'))
        c.execute('UPDATE pilot_periods SET version_id=? WHERE id=?',('invalid-period-version',renewed['period_id']))
    with pytest.raises(ValueError,match='Term/period'):
        engine.evaluate('HC076',DAY,DAY,ledger_backend,now=NOW)
    assert rows(ledger_backend,'engine_cap_entries')==[]
