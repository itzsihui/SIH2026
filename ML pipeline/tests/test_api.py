import pytest
from fastapi.testclient import TestClient
from src.daycover.api import _dashboard_dist, app

c = TestClient(app)


def test_health_rules_quote():
    assert c.get("/health").json()["ok"]
    assert c.get("/rules").json()["rain_daily_mm"] == 70.0
    q = c.post("/quote", json={"stall_id": "HC001"}).json()
    assert q["premium"] == 104 and "nothing" in q["no_pay_notice"]
    assert c.post("/quote", json={"stall_id": "NOPE"}).status_code == 404


def test_evaluate_real_haze_day():
    r = c.post("/engine/evaluate", params={"date": "2015-10-07", "stall_id": "HC001"}).json()
    assert any(e["peril"] == "haze" and e["status"] == "paid" for e in r["events"])
    assert c.get("/events").json()


def test_replay_validation():
    assert c.post("/engine/replay", params={"start": "2020-01-02", "end": "2020-01-01"}).status_code == 422
    s = c.post("/engine/replay", params={"start": "2015-09-01", "end": "2015-12-31", "plan": "haze", "stall_id": "HC001"}).json()
    assert s["paid_total_sgd"] == 150.0  # S$150.00 hard annual haze cap
    assert s["haze_paid_events"] == 4


def test_mobile_api_v1_endpoints():
    # 1. Health
    h = c.get("/api/v1/health").json()
    assert h["status"] == "HEALTHY"

    # 2. Singpass auth
    auth = c.post("/api/v1/auth/singpass", json={"persona_id": "auntie_mei"}).json()
    assert auth["id"] == "HC076"
    assert "Maxwell" in auth["hawker_centre"]
    assert auth["assigned_station_id"] == "S79"  # real gauge for that stall, not a persona label
    assert "Ah Mei" in auth["stall_name"]

    # 3. Hawker centres
    hc = c.get("/api/v1/hawker-centres").json()
    assert hc["total"] >= 123

    # 4. Telemetry
    tel = c.get("/api/v1/telemetry/live", params={"stall_id": "HC001"}).json()
    assert tel["rain_trigger_mm"] == 70.0 and tel["rain_gauge_id"]
    assert tel["psi_as_of"] and "not connected" in tel["source_note"]  # honest: latest record on file, not live

    c.post('/api/v1/policies', json={'stall_id': 'HC001', 'accepted_version': 'daycover-pilot-m1-2026.11-v1', 'consent': True})
    # 5. Trigger simulation - Rain
    sim_rain = c.post("/api/v1/triggers/simulate", json={"peril": "RAIN_70MM", "stall_id": "HC001"}).json()
    assert sim_rain["disbursed"] is True
    assert sim_rain["amount"] == 30.00
    assert sim_rain["simulated"] is True and "Simulated" in sim_rain["settlement_rail"]

    # 6. Trigger simulation - Acute Haze
    sim_haze = c.post("/api/v1/triggers/simulate", json={"peril": "HAZE_151_ACUTE", "stall_id": "HC001"}).json()
    assert sim_haze["disbursed"] is True
    assert sim_haze["amount"] == 60.00

    # 7. Scheduled cleaning suppression
    c.post('/api/v1/policies', json={'stall_id': 'HC002', 'accepted_version': 'daycover-pilot-m1-2026.11-v1', 'consent': True})
    sim_clean = c.post("/api/v1/triggers/simulate", json={"peril": "CLEANING_CLOSURE", "stall_id": "HC002"}).json()
    assert sim_clean["disbursed"] is False
    assert sim_clean["status"] == "SUPPRESSED"

    # 8. Concierge chat
    chat = c.post("/api/v1/concierge/chat", json={"message": "how much for heavy rain?"}).json()
    assert "S$30" in chat["reply"]
    assert "70" in chat["reply"]
    assert chat["decides_payouts"] is False
    for banned in ("2.21", "0.02", "Munich", "FairPrice", "under 3", "instant"):
        assert banned.lower() not in chat["reply"].lower()

    # 9. Stalls endpoint
    stalls_res = c.get("/stalls")
    assert stalls_res.status_code == 200
    stalls_data = stalls_res.json()
    assert len(stalls_data) >= 10


def test_dashboard_backtest_uses_current_rules():
    rules = c.get("/rules").json()
    response = c.get("/dash/backtest")
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["rule_version"] == rules["version"]
    assert meta["rain_trigger_mm"] == rules["rain_daily_mm"]
    assert meta["haze_money_cap_sgd"] == rules["haze_cap_amount_per_year"]
    assert meta["haze_day_definition"] == rules["haze_day_definition"]


@pytest.mark.skipif(not (_dashboard_dist / "index.html").is_file(), reason="dashboard build is not installed")
def test_dashboard_static_mount():
    response = c.get("/dashboard/")
    assert response.status_code == 200
    assert "DayCover" in response.text or 'id="root"' in response.text
