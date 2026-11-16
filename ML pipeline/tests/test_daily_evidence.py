"""Phase 5 persisted evidence: timing, coverage, review, correction and selection."""
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from src.daycover import auth, daily_evidence as daily, pilot_store
from src.daycover.api import app
from src.daycover.ingestion import SGT
from src.daycover.weather_ingestion import Ingestor, Response, iso

DAY=date(2026,11,15)
NOW=datetime(2026,11,16,8,tzinfo=SGT)
REF='fixture://local-evidence-review'
DOC=hashlib.sha256(b'local-closure-fixture').hexdigest()


class Clock:
    def __init__(self):self.stamp=NOW
    def __call__(self):return self.stamp
    def sleep(self,seconds):self.stamp+=timedelta(seconds=seconds)


class Client:
    def __init__(self,payload):self.payload=payload
    def get(self,*args):return Response(200,json.dumps(self.payload).encode())


def actor(repo):return auth.provision('evidence_reviewer','reviewer','local-review-test-password')


def rows(repo,table):
    with repo.transaction() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table).fetchall()]


def ingest(repo,kind,station,values,*,day=DAY,lat=1.3003,lon=103.8372,omit=(),quarter=False):
    clock=Clock()
    start=datetime.combine(day,datetime.min.time(),SGT)
    if kind=='rain':
        ticks=[start+timedelta(minutes=5*i) for i in range(1,289)]
        metadata={'stations':[{'id':station,'name':station,'location':{'latitude':lat,'longitude':lon}}],
                  'readingType':'TB1 Rainfall 5 Minute Total F','readingUnit':'mm'}
    else:
        ticks=[start+timedelta(minutes=15*i if quarter else 60*i) for i in range(96 if quarter else 24)]
        metadata={'regionMetadata':[{'name':r,'labelLocation':{'latitude':lat,'longitude':lon}} for r in ('north','south','east','west','central')]}
    if not isinstance(values,list):values=[values]*len(ticks)
    by_day={}
    for index,(tick,value) in enumerate(zip(ticks,values)):
        if index in omit:continue
        row={'timestamp':tick.isoformat()}
        if kind=='rain':row['data']=[{'stationId':station,'value':value}]
        else:row.update(date=str(tick.date()),updatedTimestamp=tick.isoformat(),readings={'psi_twenty_four_hourly':{station.removeprefix('REGION_').lower():value}})
        by_day.setdefault(tick.date(),[]).append(row)
    for request_day,items in by_day.items():
        payload={'code':0,'data':metadata|{('readings' if kind=='rain' else 'items'):items}}
        worker=Ingestor(repo,Client(payload),clock=clock,sleep=clock.sleep)
        result=worker.run(worker.start(kind,request_day))
        assert result['status']=='complete',result


def mapping(repo,station,reviewer,start=DAY,end=DAY,decision='approved'):
    versions=[r for r in rows(repo,'weather_station_versions') if r['station']==station]
    return daily.review_mapping(versions[-1]['id'],start,end,decision,reviewer,REF,repo)


def finalized(repo,kind,station,reviewer):
    result=daily.build_daily(kind,station,DAY,repo,now=NOW)
    assert not result['blocking_reasons'],result['blocking_reasons']
    return daily.review_daily(result['aggregate_id'],'final',reviewer,REF,repo,now=NOW)


def test_full_rain_day_persists_candidates_but_unverified_timing_cannot_finalize(ledger_backend):
    reviewer=actor(ledger_backend)
    ingest(ledger_backend,'rain','S79',.1)
    mapping(ledger_backend,'S79',reviewer)
    result=daily.build_daily('rain','S79',DAY,ledger_backend,now=NOW)
    assert result['candidate_value']==28.8 and result['observed_bins']==288 and result['expected_bins']==288
    assert result['completeness']=='complete' and result['status']=='pending'
    assert result['blocking_reasons']==['rain_interval_label_unverified']
    assert result['usable_value'] is None and not result['eligible_for_phase6']
    with pytest.raises(ValueError,match='rain_interval_label_unverified'):
        daily.review_daily(result['aggregate_id'],'final',reviewer,REF,ledger_backend,now=NOW)
    assert daily.build_daily('rain','S79',DAY,ledger_backend,now=NOW)['aggregate_id']==result['aggregate_id']
    assert len(rows(ledger_backend,'pilot_aggregate_inputs'))==288
    assert len(rows(ledger_backend,'pilot_daily_aggregates'))==1


def test_missing_bins_never_become_zero_and_unfinished_day_is_pending(ledger_backend):
    ingest(ledger_backend,'rain','S79',0,omit=(4,9))
    result=daily.build_daily('rain','S79',DAY,ledger_backend,now=NOW)
    assert result['observed_bins']==286 and len(result['missing_bins'])==2
    assert result['candidate_value'] is None and result['usable_value'] is None
    assert 'missing_bins' in result['blocking_reasons']
    unfinished=daily.build_daily('rain','S79',DAY,ledger_backend,now=datetime(2026,11,15,23,59,tzinfo=SGT))
    assert 'day_not_finished' in unfinished['blocking_reasons']
    empty=daily.build_daily('psi','REGION_NORTH',DAY,ledger_backend,now=NOW)
    assert empty['observed_bins']==0 and empty['candidate_value'] is None


def test_psi_hourly_max_ignores_quarter_hour_spikes_and_preserves_finality_on_equal_replay(ledger_backend):
    reviewer=actor(ledger_backend)
    values=[40 if i%4==0 else 499 for i in range(96)];values[12]=151
    ingest(ledger_backend,'psi','REGION_SOUTH',values,quarter=True)
    mapping(ledger_backend,'REGION_SOUTH',reviewer)
    result=finalized(ledger_backend,'psi','REGION_SOUTH',reviewer)
    assert result['candidate_value']==151 and result['usable_value']==151 and result['status']=='final'
    assert result['observed_bins']==24 and result['eligible_for_phase6'] and not result['settlement_ready']
    aid=result['aggregate_id']
    ingest(ledger_backend,'psi','REGION_SOUTH',values,quarter=True)
    assert daily.current_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)['aggregate_id']==aid
    assert rows(ledger_backend,'pilot_financial_entries')==[]


def test_late_correction_invalidates_approval_and_resolution_is_revision_set_specific(ledger_backend):
    reviewer=actor(ledger_backend)
    ingest(ledger_backend,'psi','REGION_SOUTH',101)
    mapping(ledger_backend,'REGION_SOUTH',reviewer)
    original=finalized(ledger_backend,'psi','REGION_SOUTH',reviewer)
    ingest(ledger_backend,'psi','REGION_SOUTH',[151])
    current=daily.current_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)
    assert current['status']=='pending' and current['usable_value'] is None
    assert 'unresolved_revisions' in current['blocking_reasons']
    with pytest.raises(ValueError,match='changed'):
        daily.review_daily(original['candidate_aggregate_id'],'final',reviewer,REF,ledger_backend,now=NOW)
    revised=max((r for r in rows(ledger_backend,'pilot_observations') if float(r['value'])==151),key=lambda r:r['id'])
    daily.review_revision(revised['id'],reviewer,REF,ledger_backend)
    rebuilt=daily.build_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)
    assert rebuilt['status']=='corrected' and rebuilt['candidate_value']==151
    final=daily.review_daily(rebuilt['aggregate_id'],'final',reviewer,REF,ledger_backend,now=NOW)
    assert final['usable_value']==151 and final['aggregate_id']!=original['aggregate_id']
    ingest(ledger_backend,'psi','REGION_SOUTH',[160])
    assert 'unresolved_revisions' in daily.current_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)['blocking_reasons']
    assert len(rows(ledger_backend,'weather_daily_reviews'))==2


def test_rejection_mapping_revocation_and_metadata_changes_fail_closed(ledger_backend):
    reviewer=actor(ledger_backend)
    ingest(ledger_backend,'psi','REGION_SOUTH',40)
    mapping(ledger_backend,'REGION_SOUTH',reviewer)
    result=finalized(ledger_backend,'psi','REGION_SOUTH',reviewer)
    rejected=daily.review_daily(result['candidate_aggregate_id'],'rejected',reviewer,REF,ledger_backend,now=NOW)
    assert rejected['status']=='rejected' and rejected['usable_value'] is None
    mapping(ledger_backend,'REGION_SOUTH',reviewer,decision='revoked')
    assert 'station_mapping_not_reviewed' in daily.current_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)['blocking_reasons']
    ingest(ledger_backend,'psi','REGION_SOUTH',40,lat=1.4)
    assert 'unresolved_revisions' in daily.current_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)['blocking_reasons']


def test_year_and_midnight_boundaries_are_explicit():
    for day in (date(2025,12,31),date(2024,2,29),date(2026,1,1)):
        rain=daily.expected_times(day,'rain');psi=daily.expected_times(day,'psi')
        start=datetime.combine(day,datetime.min.time(),SGT)
        assert rain[0]==iso(start+timedelta(minutes=5))
        assert rain[-1]==iso(start+timedelta(days=1))
        assert psi[0]==iso(start) and psi[-1]==iso(start+timedelta(hours=23))
        assert len(rain)==288 and len(psi)==24


def test_only_active_reviewers_can_approve_and_every_new_table_is_immutable(ledger_backend):
    reviewer=actor(ledger_backend)
    customer=auth.provision('evidence_customer','customer','local-customer-test-password')
    ingest(ledger_backend,'psi','REGION_SOUTH',40)
    version=rows(ledger_backend,'weather_station_versions')[0]
    with pytest.raises(ValueError,match='reviewer'):
        daily.review_mapping(version['id'],DAY,DAY,'approved',customer,REF,ledger_backend)
    auth.disable(reviewer)
    with pytest.raises(ValueError,match='reviewer'):
        daily.review_mapping(version['id'],DAY,DAY,'approved',reviewer,REF,ledger_backend)
    for table in ('weather_mapping_reviews','weather_revision_reviews','weather_daily_details','weather_daily_reviews','weather_closure_versions','weather_closure_reviews','weather_evidence_selections'):
        # Trigger existence is meaningful even for empty tables; deletion is blocked once rows exist in other tests.
        with ledger_backend.transaction() as c:
            if c.backend=='sqlite':
                assert c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",(table,)).fetchall()
            else:
                assert c.execute('SELECT tgname FROM pg_trigger WHERE tgrelid=?::regclass AND NOT tgisinternal',(table,)).fetchall()


def policy(repo):return pilot_store.enrol('HC076',date(2026,11,1),'S79','south')


def closure(repo,p,reviewer,closed=False):
    proposed=daily.propose_closure(p['centre_id'],DAY,closed,'cleaning' if closed else 'explicit_open',REF,DOC,repo)
    daily.review_closure(proposed['closure_id'],'approved',reviewer,REF,repo)
    return proposed


def test_fallback_uses_reviewed_complete_nearest_gauge_and_deterministic_tie(ledger_backend,monkeypatch):
    # Test-only verified-method fixture exercises the future eligible-rain branch.
    # Production keeps RAIN_TIMING_VERIFIED=False with no CLI/environment bypass.
    monkeypatch.setattr(daily,'RAIN_TIMING_VERIFIED',True)
    from src.daycover import data
    centre=next(s for s in data.load_stalls() if s.id=='HC076')
    reviewer=actor(ledger_backend);p=policy(ledger_backend)
    for station in ('S80','S81'):
        ingest(ledger_backend,'rain',station,.25,lat=centre.lat,lon=centre.lon)
        mapping(ledger_backend,station,reviewer)
        finalized(ledger_backend,'rain',station,reviewer)
    # Far-away gauge may be complete and approved; it must still be excluded.
    ingest(ledger_backend,'rain','S82',1,lat=centre.lat+.1,lon=centre.lon)
    mapping(ledger_backend,'S82',reviewer);finalized(ledger_backend,'rain','S82',reviewer)
    unknown=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert unknown['selected_gauge']=='S80' and unknown['distance_km']==0
    assert unknown['selection_reason']=='approved_nearest_valid_within_5km'
    assert {r['station'] for r in unknown['fallback_candidates']}=={'S80','S81'}
    assert not unknown['rain_input_ready'] and unknown['closure']['closed'] is None
    closure(ledger_backend,p,reviewer)
    ready=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert ready['rain_input_ready'] and ready['rain']['usable_value']==72
    assert not ready['settlement_ready'] and not ready['financial_effect']
    assert daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)['selection_id']==ready['selection_id']
    # Valid assigned evidence always takes priority over any closer fallback.
    ingest(ledger_backend,'rain','S79',0,lat=centre.lat+.02,lon=centre.lon)
    mapping(ledger_backend,'S79',reviewer);finalized(ledger_backend,'rain','S79',reviewer)
    primary=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert primary['selected_gauge']=='S79' and primary['selection_reason']=='assigned_gauge'
    assert primary['rain']['usable_value']==0
    assert rows(ledger_backend,'pilot_financial_entries')==[]


def test_no_fallback_for_missing_unreviewed_or_out_of_range_gauges(ledger_backend,monkeypatch):
    monkeypatch.setattr(daily,'RAIN_TIMING_VERIFIED',True)
    from src.daycover import data
    centre=next(s for s in data.load_stalls() if s.id=='HC076')
    reviewer=actor(ledger_backend);policy(ledger_backend)
    ingest(ledger_backend,'rain','S80',1,lat=centre.lat,lon=centre.lon)
    # Complete bins without a mapping review are not an approved geographic fallback.
    daily.build_daily('rain','S80',DAY,ledger_backend,now=NOW)
    missing=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert missing['selected_gauge'] is None and not missing['rain_input_ready']
    mapping(ledger_backend,'S80',reviewer,start=DAY-timedelta(days=2),end=DAY-timedelta(days=1))
    assert daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)['selected_gauge'] is None
    assert pilot_store.policy('HC076')['remaining_combined_sgd']==180


def test_closure_corrections_stay_pending_until_review_and_never_reverse_financials(ledger_backend):
    reviewer=actor(ledger_backend);p=policy(ledger_backend)
    pilot_store.simulate('HC076',DAY,'rain',70,None,None,False,'S79','south')
    original=closure(ledger_backend,p,reviewer,False)
    first=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert first['closure']['status']=='approved' and first['closure']['closed'] is False
    correction=daily.propose_closure(p['centre_id'],DAY,True,'cleaning',REF,DOC,ledger_backend)
    assert daily.propose_closure(p['centre_id'],DAY,True,'cleaning',REF,DOC,ledger_backend)['duplicate']
    pending=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert pending['closure']['status']=='pending' and pending['closure']['closed'] is None
    with pytest.raises(ValueError,match='latest'):
        daily.review_closure(original['closure_id'],'approved',reviewer,REF,ledger_backend)
    daily.review_closure(correction['closure_id'],'approved',reviewer,REF,ledger_backend)
    updated=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert updated['closure']['closed'] is True and updated['closure']['supersedes_id']==original['closure_id']
    assert first['selection_id']!=updated['selection_id']
    assert pilot_store.policy('HC076')['remaining_combined_sgd']==150
    assert len(rows(ledger_backend,'pilot_financial_entries'))==2
    assert len(rows(ledger_backend,'weather_closure_versions'))==2
    for table in ('weather_closure_versions','weather_closure_reviews','weather_evidence_selections'):
        with pytest.raises(Exception):
            with ledger_backend.transaction() as c:c.execute('DELETE FROM '+table)


def test_today_and_yesterday_psi_are_separate_traceable_inputs(ledger_backend):
    reviewer=actor(ledger_backend);p=policy(ledger_backend)
    for day in (DAY-timedelta(days=1),DAY):ingest(ledger_backend,'psi','REGION_SOUTH',110,day=day)
    mapping(ledger_backend,'REGION_SOUTH',reviewer,start=DAY-timedelta(days=1),end=DAY)
    for day in (DAY-timedelta(days=1),DAY):
        candidate=daily.build_daily('psi','REGION_SOUTH',day,ledger_backend,now=NOW)
        daily.review_daily(candidate['aggregate_id'],'final',reviewer,REF,ledger_backend,now=NOW)
    closure(ledger_backend,p,reviewer)
    selection=daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)
    assert selection['haze_today_ready'] and selection['haze_consecutive_ready']
    assert selection['psi_today']['day']==str(DAY)
    assert selection['psi_yesterday']['day']==str(DAY-timedelta(days=1))
    assert selection['psi_today']['aggregate_id']!=selection['psi_yesterday']['aggregate_id']
    assert not selection['rain_input_ready']


def test_get_evidence_is_private_scoped_and_read_only(ledger_backend,monkeypatch):
    monkeypatch.setenv('DAYCOVER_AUTH_MODE','local')
    client=TestClient(app);p=policy(ledger_backend)
    owner=auth.provision('policy_owner','customer','local-owner-test-password')
    auth.provision('foreign_owner','customer','local-foreign-test-password')
    def signin(alias,password):
        r=client.post('/api/v1/auth/login',json={'alias':alias,'password':password});assert r.status_code==200
        return {'Authorization':'Bearer '+r.json()['access_token']}
    headers=signin('policy_owner','local-owner-test-password')
    foreign=signin('foreign_owner','local-foreign-test-password')
    auth.set_grant(owner,p['merchant_id'])
    path='/api/v1/evidence/HC076/'+str(DAY)
    assert client.get(path).status_code==401
    assert client.get(path,headers=foreign).status_code==404
    result=client.get(path,headers=headers)
    assert result.status_code==200,result.text
    assert result.json()['persisted'] is False and result.json()['rain']['usable_value'] is None
    assert rows(ledger_backend,'weather_evidence_selections')==[]
    auth.set_grant(owner,p['merchant_id'],False)
    assert client.get(path,headers=headers).status_code==404


def test_next_midnight_is_required_and_old_complete_days_do_not_expire(ledger_backend):
    reviewer=actor(ledger_backend)
    ingest(ledger_backend,'rain','S79',0,omit=(287,))
    result=daily.build_daily('rain','S79',DAY,ledger_backend,now=NOW)
    assert result['observed_bins']==287 and result['missing_bins']==[iso(datetime(2026,11,16,tzinfo=SGT))]
    ingest(ledger_backend,'psi','REGION_SOUTH',40)
    mapping(ledger_backend,'REGION_SOUTH',reviewer)
    final=finalized(ledger_backend,'psi','REGION_SOUTH',reviewer)
    assert daily.current_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW+timedelta(days=400))['aggregate_id']==final['aggregate_id']


def test_aggregation_transaction_failure_rolls_back_all_links(ledger_backend,monkeypatch):
    ingest(ledger_backend,'psi','REGION_SOUTH',40)
    original=daily._save
    def fail(*args):original(*args);raise RuntimeError('Injected aggregate failure')
    monkeypatch.setattr(daily,'_save',fail)
    with pytest.raises(RuntimeError):daily.build_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)
    assert rows(ledger_backend,'pilot_daily_aggregates')==[]
    assert rows(ledger_backend,'pilot_aggregate_inputs')==[]
    assert rows(ledger_backend,'weather_daily_details')==[]
    monkeypatch.setattr(daily,'_save',original)
    assert daily.build_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)['aggregate_id']


def test_concurrent_builds_produce_one_immutable_version(ledger_backend):
    ingest(ledger_backend,'psi','REGION_SOUTH',40)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:daily.build_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW),range(3)))
    assert len({r['aggregate_id'] for r in results})==1
    assert len(rows(ledger_backend,'pilot_daily_aggregates'))==1
    assert len(rows(ledger_backend,'weather_daily_details'))==1


def test_incomplete_acquisition_and_rejected_observation_cannot_finalize(ledger_backend):
    reviewer=actor(ledger_backend)
    ingest(ledger_backend,'psi','REGION_SOUTH',40)
    mapping(ledger_backend,'REGION_SOUTH',reviewer)
    with ledger_backend.transaction() as c:c.execute("UPDATE weather_runs SET status='paused'")
    partial=daily.build_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)
    assert 'acquisition_not_complete' in partial['blocking_reasons']
    with pytest.raises(ValueError):daily.review_daily(partial['aggregate_id'],'final',reviewer,REF,ledger_backend,now=NOW)
    with ledger_backend.transaction() as c:c.execute("UPDATE weather_runs SET status='complete'")
    obs=rows(ledger_backend,'pilot_observations')[0]
    daily.review_revision(obs['id'],reviewer,REF,ledger_backend,reject=True)
    rejected=daily.build_daily('psi','REGION_SOUTH',DAY,ledger_backend,now=NOW)
    assert 'rejected_observation' in rejected['blocking_reasons'] and rejected['candidate_value'] is None
    for table in ('weather_mapping_reviews','weather_revision_reviews','weather_daily_details','pilot_daily_aggregates'):
        with pytest.raises(Exception):
            with ledger_backend.transaction() as c:c.execute('DELETE FROM '+table)


def test_rejected_closure_never_implies_open_and_confirmation_creates_a_new_version(ledger_backend):
    reviewer=actor(ledger_backend);p=policy(ledger_backend)
    first=closure(ledger_backend,p,reviewer,False)
    change=daily.propose_closure(p['centre_id'],DAY,True,'works',REF,DOC,ledger_backend)
    daily.review_closure(change['closure_id'],'rejected',reviewer,REF,ledger_backend)
    assert daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)['closure']['closed'] is None
    confirmed=daily.propose_closure(p['centre_id'],DAY,False,'explicit_open',REF,DOC,ledger_backend)
    assert confirmed['closure_id'] not in (first['closure_id'],change['closure_id'])
    daily.review_closure(confirmed['closure_id'],'approved',reviewer,REF,ledger_backend)
    assert daily.select_evidence('HC076',DAY,ledger_backend,now=NOW)['closure']['closed'] is False
    assert len(rows(ledger_backend,'weather_closure_versions'))==3


def test_v4_migration_failure_preserves_v3_raw_evidence(ledger_backend,monkeypatch):
    from src.daycover import ledger_migrations
    ingest(ledger_backend,'psi','REGION_SOUTH',40)
    before=rows(ledger_backend,'weather_fetches')
    with ledger_backend.transaction() as c:
        for table in ('settlement_mock_wallet_entries','settlement_cash_entries','settlement_provider_events','settlement_dispatch_attempts','settlement_instruction_events','settlement_mock_jobs','settlement_mock_key','settlement_instructions','settlement_outbox','settlement_recipient_reviews','settlement_recipients'):
            c.execute('DROP TABLE '+table)
        for table in ('billing_mock_refunds','billing_mock_jobs','billing_mock_key','billing_refund_requests','billing_entry_links','billing_provider_events','billing_dispatches','billing_attempts','billing_authorizations','billing_bills','billing_schedules'):
            c.execute('DROP TABLE '+table)
        for table in ('engine_replay_reviews','engine_replay_plans','engine_entitlement_entries','engine_cap_entries','engine_decisions','engine_period_modes','engine_lifecycle_events','engine_terms'):
            c.execute('DROP TABLE '+table)
        for table in ('weather_evidence_selections','weather_daily_reviews','weather_daily_details','weather_closure_reviews','weather_closure_versions','weather_revision_reviews','weather_mapping_reviews'):
            c.execute('DROP TABLE '+table)
        c.execute('DELETE FROM pilot_schema_migrations WHERE version>=4')
    original=ledger_migrations._apply
    def interrupted(native,backend,script):
        original(native,backend,script)
        if 'CREATE TABLE weather_mapping_reviews' in script:raise RuntimeError('Injected migration interruption')
    monkeypatch.setattr(ledger_migrations,'_apply',interrupted)
    with pytest.raises(RuntimeError):ledger_backend.migrate()
    native=ledger_backend._connect()
    try:
        assert native.execute('SELECT COUNT(*) AS n FROM pilot_schema_migrations').fetchone()['n']==3
        assert dict(native.execute('SELECT * FROM weather_fetches').fetchone())==before[0]
    finally:native.close()
    monkeypatch.setattr(ledger_migrations,'_apply',original)
    ledger_backend.migrate()
    assert rows(ledger_backend,'weather_fetches')==before


def test_stored_reviewed_aggregate_and_links_are_append_only(ledger_backend):
    reviewer=actor(ledger_backend);ingest(ledger_backend,'psi','REGION_SOUTH',40)
    mapping(ledger_backend,'REGION_SOUTH',reviewer)
    finalized(ledger_backend,'psi','REGION_SOUTH',reviewer)
    for table in ('pilot_daily_aggregates','weather_daily_details','weather_daily_reviews'):
        with pytest.raises(Exception):
            with ledger_backend.transaction() as c:c.execute('DELETE FROM '+table)
