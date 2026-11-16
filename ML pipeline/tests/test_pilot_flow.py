from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from fastapi.testclient import TestClient
from src.daycover import pilot_store
from src.daycover.api import app, _STALLS
from src.daycover.pilot import CONTRACT
from src.daycover.policy_year import policy_year_bounds

c = TestClient(app)
START = date(2025, 12, 15)


def enrol(stall='HC001', start=START):
    return c.post('/api/v1/policies', json={'stall_id': stall, 'start_date': str(start),
        'accepted_version': CONTRACT['version'], 'consent': True})


def event(day, peril='RAIN_70MM', **fields):
    return c.post('/api/v1/triggers/simulate', json={'stall_id': 'HC001', 'peril': peril,
        'event_date': str(day), **fields})


def test_full_mobile_contract_flow_and_persistence(monkeypatch):
    auth = c.post('/api/v1/auth/singpass', json={'persona_id': 'auntie_mei'}).json()
    sid = auth['id']
    assert c.get('/api/v1/policy/'+sid).status_code == 404
    p = enrol(sid).json()
    assert p['rule_version'] == CONTRACT['version'] and p['remaining_combined_sgd'] == 180
    r = c.post('/api/v1/triggers/simulate', json={'stall_id': sid, 'peril': 'RAIN_70MM', 'event_date': '2026-01-02'}).json()
    assert r['amount'] == 30 and r['evidence']['gauge'] == auth['assigned_station_id']
    assert r['remaining_coverage']['remaining_rain_events'] == 0
    # A fresh client/connection sees persisted history, no Postgres dependency.
    other = TestClient(app)
    assert other.get('/api/v1/payouts/'+sid).json()['claims_count'] == 1
    assert other.get('/api/v1/policy/'+sid).json()['remaining_combined_sgd'] == 150
    repeat = c.post('/api/v1/triggers/simulate', json={'stall_id': sid, 'peril': 'RAIN_70MM', 'event_date': '2026-01-02'}).json()
    assert repeat['duplicate'] and not repeat['disbursed']
    assert repeat['claim_id'] == r['claim_id']


def test_caps_overlap_and_no_january_reset(monkeypatch):
    monkeypatch.setattr(_STALLS['HC001'], 'closures', set())
    enrol()
    assert event(date(2025,12,31)).json()['amount'] == 30
    assert event(date(2026,1,1)).json()['status'] == 'CAPPED'
    amounts = [event(date(2026,1,1)+timedelta(days=i), 'HAZE_151_ACUTE').json()['amount'] for i in range(4)]
    assert amounts == [60, 60, 30, 0]
    p = c.get('/api/v1/policy/HC001').json()
    assert p['remaining_combined_sgd'] == 0 and p['annual_haze_days_paid'] == 3
    assert c.get('/api/v1/payouts/HC001').json()['total_disbursed'] == 180


def test_haze_five_day_limit(monkeypatch):
    monkeypatch.setattr(_STALLS['HC001'], 'closures', set())
    enrol()
    for i in range(6):
        r = event(START+timedelta(days=i), 'HAZE_101_CONSECUTIVE').json()
        assert r['amount'] == (30 if i < 5 else 0)
    assert c.get('/api/v1/policy/HC001').json()['annual_haze_days_paid'] == 5


def test_threshold_missing_pending_retry_and_closure(monkeypatch):
    monkeypatch.setattr(_STALLS['HC001'], 'closures', {START})
    enrol()
    assert event(START).json()['status'] == 'SUPPRESSED'
    assert event(START+timedelta(days=1), rain_daily_mm=69.9).json()['status'] == 'NO_TRIGGER'
    pending_day = START+timedelta(days=2)
    assert event(pending_day, rain_daily_mm=None).json()['status'] == 'PENDING'
    assert event(pending_day, rain_daily_mm=70).json()['amount'] == 30
    assert event(pending_day, 'HAZE_101_CONSECUTIVE', psi_yesterday=None).json()['status'] == 'PENDING'
    assert event(pending_day, 'HAZE_151_ACUTE', psi_today=151, psi_yesterday=None).json()['amount'] == 60


def test_validation_policy_term_and_immutability(monkeypatch):
    monkeypatch.setattr(_STALLS['HC001'], 'closures', set())
    assert event(START).status_code == 404
    body = {'stall_id': 'HC001', 'accepted_version': 'wrong', 'consent': True}
    assert c.post('/policies', json=body).status_code == 422
    body.update(accepted_version=CONTRACT['version'], consent=False)
    assert c.post('/policies', json=body).status_code == 422
    assert enrol().status_code == 200
    assert enrol(start=START+timedelta(days=1)).status_code == 409
    assert event(START-timedelta(days=1)).status_code == 409
    assert event(date(2026,12,15)).status_code == 422  # future weather
    assert event(START, rain_daily_mm=-1).status_code == 422
    assert event(START, station_id='WRONG').status_code == 422
    assert c.get('/api/v1/policy/NOPE').status_code == 404
    assert event(START+timedelta(days=2)).json()['amount'] == 30
    assert event(START+timedelta(days=1)).status_code == 409
    assert c.post('/engine/evaluate', params={'date': str(START), 'stall_id': 'NOPE'}).status_code == 404


def test_expiry_no_automatic_renewal_and_leap_day(monkeypatch):
    enrol(start=date(2024,2,29))
    assert event(date(2025,2,28)).status_code == 409
    assert c.get('/api/v1/policy/HC001').json()['status'] == 'DEMO_INACTIVE'
    assert policy_year_bounds(date(2024,2,29), date(2024,2,29)) == (date(2024,2,29), date(2025,2,27))
    assert policy_year_bounds(date(2024,2,29), date(2028,2,29))[0] == date(2028,2,29)


def test_concurrent_duplicates_only_post_once(monkeypatch):
    monkeypatch.setattr(_STALLS['HC001'], 'closures', set())
    enrol()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: pilot_store.simulate('HC001', START, 'rain',70,None,None,False,'S79','south'), range(8)))
    assert sum(r['disbursed'] for r in results) == 1
    assert pilot_store.history('HC001')['total_disbursed'] == 30


def test_monthly_billing_exact_and_no_unsupported_claims():
    assert sum(CONTRACT['instalments_cents']) == 10400
    assert CONTRACT['instalments_cents'] == [867]*8 + [866]*4
    enrol()
    p = c.get('/api/v1/policy/HC001').json()
    assert p['billing']['outstanding_sgd'] == 104 and p['billing']['collected_sgd'] == 0
    assert CONTRACT['subsidy_sgd'] == 0


def test_frozen_contract_registry_matches_code():
    import json
    from pathlib import Path
    # JSON normalizes tuples in dataclass shadow settings.
    assert json.loads(Path('contracts/'+CONTRACT['version']+'.json').read_text()) == json.loads(json.dumps(CONTRACT))
