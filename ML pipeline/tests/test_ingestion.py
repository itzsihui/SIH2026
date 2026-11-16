from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import pytest
from src.daycover.ingestion import parse_snapshot, daily_summary, Reading, SGT
from scripts import ingest_nea_telemetry as job

NOW = datetime(2026,11,16,4,0,tzinfo=SGT)


def rain(value=0):
    return {'code': 0, 'data': {'readingUnit': 'mm', 'readingType': 'TB1 Rainfall 5 Minute Total F',
        'stations': [{'id':'S79'}], 'readings': [{'timestamp': NOW.isoformat(), 'data': [{'stationId':'S79','value':value}]}]}}


def psi(value=101):
    return {'code': 0, 'data': {'items': [{'timestamp': NOW.isoformat(), 'readings': {'psi_twenty_four_hourly': {'south':value}}}]}}


def test_schema_units_zero_and_timezone():
    r = parse_snapshot(rain(), 'rain', NOW)[0]
    assert r.value == 0 and r.metric == 'rainfall_5min_mm' and r.unit == 'mm'
    assert parse_snapshot(psi(), 'psi', NOW)[0].station == 'REGION_SOUTH'
    assert r.observed_at.astimezone(timezone.utc).hour == 20


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), None, True, '70'])
def test_bad_values(value):
    with pytest.raises(ValueError): parse_snapshot(rain(value), 'rain', NOW)


def test_invalid_metadata_missing_future_stale_duplicates():
    for mutate in [
        lambda p: p['data'].update(readingUnit='inch'),
        lambda p: p['data'].update(readings=[]),
        lambda p: p['data']['readings'][0].update(timestamp='2026-11-16T04:00:00'),
        lambda p: p['data']['readings'][0].update(timestamp=(NOW-timedelta(hours=2)).isoformat()),
        lambda p: p['data']['readings'][0].update(timestamp=(NOW+timedelta(hours=2)).isoformat()),
        lambda p: p['data']['readings'][0]['data'].append({'stationId':'S79','value':0}),
        lambda p: p['data']['readings'][0]['data'][0].update(stationId='UNKNOWN'),
    ]:
        p = rain(); mutate(p)
        with pytest.raises(ValueError): parse_snapshot(p, 'rain', NOW)
    with pytest.raises(ValueError): parse_snapshot(psi(501),'psi', NOW)
    with pytest.raises(ValueError): parse_snapshot(None,'rain', NOW)


def test_complete_daily_aggregation_missing_and_conflicting_duplicates():
    day = date(2026,11,15)
    midnight = datetime(2026,11,15,tzinfo=SGT)
    rows = [Reading('S79','rainfall_5min_mm',midnight+timedelta(minutes=5*i),1,'mm') for i in range(1,289)]
    assert daily_summary(rows,day,'S79','rain')['value'] == 288
    assert daily_summary(rows+rows,day,'S79','rain')['value'] == 288
    assert daily_summary(rows[:-1],day,'S79','rain')['value'] is None
    assert daily_summary(rows,day+timedelta(days=1),'S79','rain')['value'] is None
    with pytest.raises(ValueError): daily_summary(rows+[replace(rows[0],value=2)],day,'S79','rain')
    hourly = [Reading('REGION_SOUTH','psi_24hr',midnight+timedelta(hours=i),100+i,'PSI') for i in range(24)]
    assert daily_summary(hourly,day,'REGION_SOUTH','psi')['value'] == 123
    assert daily_summary(hourly[:-1],day,'REGION_SOUTH','psi')['status'] == 'pending'


def test_outage_does_not_invent_readings():
    from src.daycover.weather_ingestion import Response
    from src.daycover.ledger_repository import configured_repository
    class Unavailable:
        def get(self,*args): return Response(403,b'Access denied')
    for ingest in (job.ingest_psi_readings,job.ingest_rainfall_readings):
        with pytest.raises(ValueError): ingest(client=Unavailable())
    with configured_repository().transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM pilot_observations').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM weather_fetches').fetchone()[0]==2
