"""Canonical raw lineage, resumability and failure behavior on both real SQL backends."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import hashlib
import json
import threading

import pytest
from src.daycover.ingestion import SGT
from src.daycover.weather_ingestion import Ingestor, InvalidPage, OfficialClient, Response, parse_page, source_health, iso, SOURCE

NOW=datetime(2026,11,16,8,0,tzinfo=SGT)


class Clock:
    def __init__(self):self.value=NOW;self.waits=[];self.lock=threading.Lock()
    def __call__(self):
        with self.lock:return self.value
    def sleep(self,seconds):
        with self.lock:
            self.waits.append(seconds);self.value+=timedelta(seconds=seconds)


class Client:
    def __init__(self,*responses):self.responses=list(responses);self.calls=[]
    def get(self,*args):
        self.calls.append(args)
        return self.responses.pop(0)


def rain(value=0,stamp=NOW,token=None,lat=1.3,stations=None):
    metadata=stations or [{'id':'S79','deviceId':'S79','name':'Reference fixture','location':{'latitude':lat,'longitude':103.8}}]
    data={'stations':metadata,'readingType':'TB1 Rainfall 5 Minute Total F','readingUnit':'mm',
          'readings':[{'timestamp':stamp.isoformat(),'data':[{'stationId':'S79','value':value}]}]}
    if token is not None:data['paginationToken']=token
    return {'code':0,'data':data,'errorMsg':''}


def psi(stamp=NOW):
    regions=('north','south','east','west','central')
    return {'code':0,'data':{'regionMetadata':[{'name':r,'labelLocation':{'latitude':1.3,'longitude':103.8}} for r in regions],
            'items':[{'timestamp':stamp.isoformat(),'updatedTimestamp':stamp.isoformat(),'date':str(stamp.date()),
                      'readings':{'psi_twenty_four_hourly':{r:40 for r in regions}}}]}}


def response(payload,status=200):return Response(status,json.dumps(payload).encode())


def runner(repo,client,clock=None,**kwargs):
    clock=clock or Clock()
    return Ingestor(repo,client,clock=clock,sleep=clock.sleep,**kwargs)


def rows(repo,table):
    with repo.transaction() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table).fetchall()]


def test_raw_lineage_equal_replay_and_no_financial_side_effects(ledger_backend):
    raw=response(rain());client=Client(raw,raw);worker=runner(ledger_backend,client)
    rid=worker.start('rain');result=worker.run(rid)
    assert result['status']=='complete' and result['pages']==1 and not result['settlement_ready']
    assert worker.run(rid)['status']=='complete' and len(client.calls)==1
    second=worker.start('rain');assert worker.run(second)['status']=='complete'
    stored=rows(ledger_backend,'weather_fetches')
    assert len(stored)==2 and all(base64.b64decode(r['raw_base64'])==raw.body for r in stored)
    assert all(r['raw_sha256']==hashlib.sha256(raw.body).hexdigest() for r in stored)
    observations=rows(ledger_backend,'pilot_observations')
    assert len(observations)==1 and float(observations[0]['value'])==0
    assert datetime.fromisoformat(observations[0]['observed_at'])==NOW and observations[0]['quality']=='validated_provisional'
    provenance=rows(ledger_backend,'weather_observation_provenance')
    assert {r['classification'] for r in provenance}=={'new','equal_duplicate'}
    assert len(rows(ledger_backend,'weather_station_versions'))==1
    assert rows(ledger_backend,'pilot_financial_entries')==[] and rows(ledger_backend,'pilot_daily_aggregates')==[]
    # Stored bytes alone reproduce accepted values under the pinned parser and query.
    recreated=parse_page(base64.b64decode(stored[0]['raw_base64']),'rain',NOW)
    assert recreated.readings[0].value==0
    assert source_health(ledger_backend,worker.clock())['rain']['status']=='available_provisional'
    for table in ('weather_fetches','weather_station_versions','weather_observation_provenance','weather_station_presence'):
        with pytest.raises(Exception):
            with ledger_backend.transaction() as c:c.execute('DELETE FROM '+table)


def test_paginated_checkpoint_resumes_after_bad_partial_page(ledger_backend):
    client=Client(response(rain(stamp=NOW-timedelta(minutes=5),token='page-two')),Response(200,b'{bad-json'))
    worker=runner(ledger_backend,client);rid=worker.start('rain',date(2026,11,16))
    failed=worker.run(rid)
    assert failed['status']=='quarantined' and failed['pages']==1
    assert len(rows(ledger_backend,'pilot_observations'))==1
    repaired=Client(response(rain(value=1)))
    resumed=runner(ledger_backend,repaired,worker.clock)
    result=resumed.run(rid)
    assert result['status']=='complete' and result['pages']==2
    assert repaired.calls==[('rain','2026-11-16','page-two')]
    assert len(rows(ledger_backend,'pilot_observations'))==2
    assert len(rows(ledger_backend,'weather_fetches'))==3


def test_page_bound_and_pagination_cycles(ledger_backend):
    client=Client(response(rain(token='cursor')),response(rain(stamp=NOW+timedelta(minutes=5),token='cursor')))
    worker=runner(ledger_backend,client);rid=worker.start('rain',NOW.date())
    paused=worker.run(rid,max_pages=1)
    assert paused['status']=='paused' and paused['pages']==1
    result=worker.run(rid)
    assert result['status']=='quarantined' and result['error_code']=='pagination_cycle'
    assert result['pages']==1 and len(rows(ledger_backend,'pilot_observations'))==1


def test_transient_retries_rate_limit_and_timeout_are_visible(ledger_backend):
    client=Client(Response(None,error='transport_unavailable'),Response(429,b'rate limited',retry_after='4'),response(rain()))
    worker=runner(ledger_backend,client);rid=worker.start('rain');result=worker.run(rid)
    assert result['status']=='complete' and len(client.calls)==3
    assert [r['outcome'] for r in rows(ledger_backend,'weather_fetches')]==['transport_error','transport_error','accepted']
    assert any(w>=4 for w in worker.clock.waits)
    assert {a['code'] for a in result['alerts']}=={'transport_unavailable','http_429'}
    health=source_health(ledger_backend,worker.clock())
    assert health['rain']['status']=='degraded' and not health['rain']['settlement_ready']


def test_retry_budget_and_long_retry_after_persist_across_restart(ledger_backend):
    clock=Clock();client=Client(Response(503,b'outage'),Response(503,b'outage'),Response(503,b'outage'))
    worker=runner(ledger_backend,client,clock);rid=worker.start('rain');result=worker.run(rid)
    assert result['status']=='failed' and len(client.calls)==3
    assert rows(ledger_backend,'pilot_observations')==[]
    client2=Client(Response(429,b'wait',retry_after='120'))
    worker2=runner(ledger_backend,client2,clock);rid2=worker2.start('psi')
    assert worker2.run(rid2)['status']=='failed'
    after_restart=runner(ledger_backend,Client(),clock)
    assert after_restart.run(rid2)['error_code']=='rate_limit_deferred'
    assert after_restart.client.calls==[]


def test_403_and_oversized_body_fail_closed_without_retries(ledger_backend):
    worker=runner(ledger_backend,Client(Response(403,b'<html>forbidden</html>')))
    result=worker.run(worker.start('rain'))
    assert result['status']=='failed' and result['error_code']=='http_403' and len(worker.client.calls)==1
    second=runner(ledger_backend,Client(Response(200,b'partial',complete=False,error='body_too_large')),worker.clock)
    result=second.run(second.start('rain'))
    assert result['status']=='quarantined'
    assert rows(ledger_backend,'pilot_observations')==[]
    assert rows(ledger_backend,'weather_fetches')[1]['body_complete']==0


def test_corrections_and_relocation_retain_all_versions(ledger_backend):
    worker=runner(ledger_backend,Client(response(rain(0)),response(rain(2)),response(rain(2,lat=1.4))))
    for _ in range(3):assert worker.run(worker.start('rain'))['status']=='complete'
    observations=rows(ledger_backend,'pilot_observations')
    assert len(observations)==3 and {float(r['value']) for r in observations}=={0,2}
    assert len(rows(ledger_backend,'weather_station_versions'))==2
    assert {r['classification'] for r in rows(ledger_backend,'weather_observation_provenance')}=={'new','conflicting_revision'}
    codes={r['code'] for r in rows(ledger_backend,'weather_alerts')}
    assert {'station_metadata_changed','observation_conflict'}<=codes
    versions=rows(ledger_backend,'weather_station_versions')
    assert min(r['first_observed_at'] for r in versions)==iso(NOW)
    assert max(r['first_observed_at'] for r in versions)>iso(NOW)
    assert source_health(ledger_backend,worker.clock())['rain']['status']=='degraded'


def test_missing_station_and_stale_live_source_remain_visible(ledger_backend):
    extra={'id':'S80','deviceId':'S80','name':'Missing station','location':{'latitude':1.4,'longitude':103.8}}
    payload=rain();payload['data']['stations'].append(extra)
    clock=Clock();worker=runner(ledger_backend,Client(response(payload)),clock)
    result=worker.run(worker.start('rain'))
    assert result['status']=='complete' and result['alerts'][0]['code']=='stations_without_readings'
    presence=rows(ledger_backend,'weather_station_presence')
    assert sorted(r['reading_count'] for r in presence)==[0,1]
    clock.sleep(1900)
    assert source_health(ledger_backend,clock())['rain']['status']=='stale'
    assert source_health(ledger_backend,clock())['psi']['status']=='missing'


def test_backfill_late_data_is_not_live_health_or_daily_evidence(ledger_backend):
    old=NOW-timedelta(days=10)
    worker=runner(ledger_backend,Client(response(rain(stamp=old)),response(rain(stamp=old))))
    result=worker.run(worker.start('rain',old.date()))
    assert result['status']=='complete'
    assert rows(ledger_backend,'weather_observation_provenance')[0]['classification']=='late'
    assert rows(ledger_backend,'weather_station_versions')[0]['first_observed_at']==iso(NOW)
    assert source_health(ledger_backend,worker.clock())['rain']['status']=='missing'
    live=worker.run(worker.start('rain'))
    assert live['status']=='quarantined' and live['error_code']=='stale_snapshot'
    assert len(rows(ledger_backend,'pilot_observations'))==1
    with pytest.raises(ValueError):worker.start('rain',NOW.date()+timedelta(days=1))


def test_atomic_page_and_cursor_rollback_can_replay(ledger_backend,monkeypatch):
    worker=runner(ledger_backend,Client(response(rain()),response(rain())))
    rid=worker.start('rain');original=worker._persist_page
    def crash(*args):
        original(*args)
        raise RuntimeError('Injected failure after observation writes')
    monkeypatch.setattr(worker,'_persist_page',crash)
    with pytest.raises(RuntimeError):worker.run(rid)
    assert rows(ledger_backend,'pilot_observations')==[]
    assert rows(ledger_backend,'weather_fetches')==[]
    assert worker.status(rid)['pages']==0
    monkeypatch.setattr(worker,'_persist_page',original)
    assert worker.run(rid)['status']=='complete'
    assert len(rows(ledger_backend,'pilot_observations'))==1


def test_regional_psi_source_update_metadata_is_preserved(ledger_backend):
    payload=psi();payload['data']['items'][0]['readings']['psi_twenty_four_hourly'].pop('north')
    worker=runner(ledger_backend,Client(response(payload)))
    result=worker.run(worker.start('psi'))
    assert result['status']=='complete' and len(rows(ledger_backend,'pilot_observations'))==4
    assert result['alerts'][0]['code']=='stations_without_readings'
    assert all(r['source_updated_at']==iso(NOW) for r in rows(ledger_backend,'weather_observation_provenance'))
    assert all(r['metric']=='psi_24hr' and r['unit']=='PSI' for r in rows(ledger_backend,'pilot_observations'))


@pytest.mark.parametrize('mutation',[
    lambda p:p['data'].update(readingUnit='inch'),
    lambda p:p['data'].update(readingType='Hourly rainfall'),
    lambda p:p['data']['stations'].append(p['data']['stations'][0]),
    lambda p:p['data']['stations'][0]['location'].update(latitude=100),
    lambda p:p['data']['readings'][0].update(timestamp=NOW.replace(tzinfo=None).isoformat()),
    lambda p:p['data']['readings'][0].update(timestamp=(NOW+timedelta(minutes=1)).isoformat()),
    lambda p:p['data']['readings'][0].update(timestamp=(NOW+timedelta(hours=1)).isoformat()),
    lambda p:p['data']['readings'][0]['data'][0].update(stationId='UNKNOWN'),
    lambda p:p['data']['readings'][0]['data'][0].update(value=True),
    lambda p:p['data']['readings'][0]['data'][0].update(value=-1),
    lambda p:p['data']['readings'][0]['data'][0].update(value=float('nan')),
    lambda p:p['data'].update(readings=[]),
    lambda p:p['data'].update(paginationToken=123),
])
def test_malformed_page_quarantines_atomically(mutation):
    from src.daycover.ledger_repository import configured_repository
    repo=configured_repository();payload=rain();mutation(payload)
    worker=runner(repo,Client(response(payload)));result=worker.run(worker.start('rain'))
    assert result['status']=='quarantined'
    assert rows(repo,'pilot_observations')==[] and rows(repo,'weather_station_versions')==[]
    assert len(rows(repo,'weather_fetches'))==1


def test_equal_in_page_duplicate_collapses_but_conflict_rejects():
    payload=rain();payload['data']['readings'][0]['data']*=2
    assert len(parse_page(json.dumps(payload).encode(),'rain',NOW).readings)==1
    payload['data']['readings'][0]['data'][1]={'stationId':'S79','value':1}
    with pytest.raises(InvalidPage,match='conflicting_values_in_page'):parse_page(json.dumps(payload).encode(),'rain',NOW)
    with pytest.raises(InvalidPage):parse_page(json.dumps(psi()).encode(),'psi',NOW,NOW.date()-timedelta(days=1))


def test_real_client_bounds_redirects_timeouts_and_keeps_key_out_of_url(monkeypatch):
    import httpx
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(302,headers={'Location':'https://untrusted.invalid/private'},content=b'redirect')
    original=httpx.Client
    monkeypatch.setenv('DATAGOV_API_KEY','test-not-real-key')
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    result=OfficialClient().get('rain','2026-11-16','opaque token')
    assert result.status==302 and len(seen)==1
    assert 'test-not-real-key' not in str(seen[0].url)
    assert seen[0].headers['x-api-key']=='test-not-real-key'
    def timeout(request):raise httpx.ReadTimeout('Sensitive request details should not be stored',request=request)
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(timeout),**kwargs))
    assert OfficialClient().get('psi',None,None).error=='transport_unavailable'


def test_concurrent_workers_keep_raw_but_commit_page_once(ledger_backend):
    barrier=threading.Barrier(2)
    class ConcurrentClient:
        def get(self,*args):barrier.wait(timeout=10);return response(rain())
    clock=Clock();worker=runner(ledger_backend,ConcurrentClient(),clock);rid=worker.start('rain')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:runner(ledger_backend,worker.client,clock).run(rid),range(2)))
    assert all(r['status']=='complete' and r['pages']==1 for r in results)
    assert len(rows(ledger_backend,'pilot_observations'))==1
    assert len(rows(ledger_backend,'weather_observation_provenance'))==1
    assert {r['outcome'] for r in rows(ledger_backend,'weather_fetches')}=={'accepted','superseded'}


def test_threshold_like_interval_does_not_settle_an_enrolled_policy(ledger_backend):
    from src.daycover import pilot_store
    p=pilot_store.enrol('HC001',date(2026,11,1),'S79','south')
    worker=runner(ledger_backend,Client(response(rain(74.5))))
    assert worker.run(worker.start('rain'))['status']=='complete'
    assert pilot_store.policy('HC001')['remaining_combined_sgd']==180
    assert pilot_store.history('HC001')['claims_count']==0
    assert rows(ledger_backend,'pilot_financial_entries')==[]
    assert rows(ledger_backend,'pilot_daily_aggregates')==[]


def test_v3_migration_failure_preserves_v2_accounts(ledger_backend,monkeypatch):
    from src.daycover import auth, ledger_migrations
    pid=auth.provision('existing_account','customer','existing-test-password')
    with ledger_backend.transaction() as c:
        before=dict(c.execute('SELECT * FROM auth_principals WHERE id=?',(pid,)).fetchone())
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
        if c.backend=='postgres':c.execute('DROP FUNCTION weather_append_only()')
        c.execute('DELETE FROM pilot_schema_migrations WHERE version>=3')
    original=ledger_migrations._apply
    def fail(native,backend,script):
        original(native,backend,script)
        if 'CREATE TABLE weather_runs' in script:raise RuntimeError('Injected migration failure')
    monkeypatch.setattr(ledger_migrations,'_apply',fail)
    with pytest.raises(RuntimeError):ledger_backend.migrate()
    native=ledger_backend._connect()
    try:
        assert dict(native.execute('SELECT * FROM auth_principals').fetchone())==before
        assert native.execute('SELECT COUNT(*) AS n FROM pilot_schema_migrations').fetchone()['n']==2
    finally:native.close()
    monkeypatch.setattr(ledger_migrations,'_apply',original)
    ledger_backend.migrate()
    with ledger_backend.transaction() as c:
        assert dict(c.execute('SELECT * FROM auth_principals WHERE id=?',(pid,)).fetchone())==before


def test_metadata_disappearance_and_repeated_conflicts_stay_visible(ledger_backend):
    payload=rain();payload['data']['stations'].append({'id':'S80','name':'Other','location':{'latitude':1.4,'longitude':103.8}})
    worker=runner(ledger_backend,Client(response(payload),response(rain(2)),response(rain(2))))
    for _ in range(3):assert worker.run(worker.start('rain'))['status']=='complete'
    assert 'stations_absent_metadata' in {a['code'] for a in rows(ledger_backend,'weather_alerts')}
    assert source_health(ledger_backend,worker.clock())['rain']['unresolved_review_alerts']>=1
    assert source_health(ledger_backend,worker.clock())['rain']['status']=='degraded'
