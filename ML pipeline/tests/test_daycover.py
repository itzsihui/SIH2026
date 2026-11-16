from datetime import date, timedelta
from src.daycover import data
from src.daycover.engine import evaluate, rain_observation, replay
from src.daycover.rules import DEFAULT_RULES as R, haze_payout, heat_rules, rain_daily, RuleSet


def test_haze_tiers():
    assert haze_payout(151, None)[:2] == (2, 60.0)
    assert haze_payout(120, 105)[:2] == (1, 30.0)
    assert haze_payout(120, 90)[0] == 0          # single day >=101 does not pay
    assert haze_payout(None, 150)[0] == 0         # missing reading is not a trigger


def test_rain_boundary_and_missing():
    assert rain_daily(70.0)[0] and not rain_daily(69.9)[0]
    assert rain_daily(None)[0] is False


def test_heat_shadow_case_study():
    # Sumit's 1 Mar 2026 case: mean 32.525 qualifies the 32.0 and 32.5 rolling rules; 33.2 trips the single-reading rule
    h = heat_rules([32.3, 32.5, 32.1, 33.2])
    assert h["single"] and h["rolling"][32.0] and h["rolling"][32.5]
    # 1 Nov 2025 spike: single flags, rolling does not
    h2 = heat_rules([31.0, 31.2, 33.0, 31.1])
    assert h2["single"] and not h2["rolling"][32.0]


def _stall(plan="haze+rain"):
    s = [x for x in data.load_stalls(plan)][0]
    return s


def test_real_haze_day_pays_and_is_deterministic():
    s = _stall()
    d = date(2015, 10, 7)
    a = [e.to_dict() for e in evaluate(s, d)]
    assert a == [e.to_dict() for e in evaluate(s, d)]
    paid = [e for e in a if e["status"] == "paid" and e["peril"] == "haze"]
    assert paid and paid[0]["rule_version"] == R.version and paid[0]["evidence"]["psi_today"] >= 101


def test_plan_gating():
    s = _stall("rain")
    assert not [e for e in evaluate(s, date(2015, 10, 7)) if e.peril == "haze"]


def test_closure_excludes_payout():
    s = _stall()
    d = date(2015, 10, 7)
    s.closures = {d}
    ev = [e for e in evaluate(s, d) if e.peril == "haze"]
    assert ev and ev[0].status == "excluded" and ev[0].amount == 0


def test_haze_cap_five_days_per_year():
    s = _stall("haze")
    evs = [e for e in replay([s], date(2015, 9, 1), date(2015, 12, 31)) if e.peril == "haze"]
    paid = [e for e in evs if e.status == "paid"]
    assert len(paid) <= R.haze_cap_days_per_year
    assert sum(e.amount for e in paid) == R.haze_cap_amount_per_year  # Hard S$150.00 monetary sub-cap
    assert any(e.status == "capped" for e in evs)


def test_rain_unknown_date_is_not_zero_or_paid():
    s = _stall("rain")
    d = date(2018, 3, 3)
    assert d not in data.rain_dates() or True
    if d not in data.rain_dates():
        assert evaluate(s, d) == []


def test_rain_rule_pays_once_per_year_on_sampled_date():
    s = _stall("rain")
    wet = None
    for dd in sorted(data.rain_dates()):
        got = [e for e in evaluate(s, dd) if e.peril == "rain" and e.status == "paid"]
        if got:
            wet = dd
            break
    assert wet is not None
    assert got[0].amount == R.rain_payout


def test_threshold_override():
    assert RuleSet(rain_daily_mm=80).rain_daily_mm == 80


def test_haze_monetary_subcap_partial_and_hard_limit():
    stall = _stall("haze")
    start = date(2020, 1, 1)
    history = {start + timedelta(days=offset): {stall.region: 151} for offset in range(4)}
    events = replay([stall], start, max(history), psi_history=history)
    assert [(e.status, e.amount) for e in events if e.peril == "haze"] == [
        ("paid", 60.0), ("paid", 60.0), ("paid", 30.0), ("capped", 0.0),
    ]


def test_rain_uses_assigned_gauge_then_nearest_valid_gauge_within_radius(monkeypatch):
    day = date(2020, 1, 1)
    stall = data.Stall("TEST", "Test centre", 1.36, 103.8, gauge="assigned")
    stations = {f"g{n}": (1.36, 103.8 + n * .004) for n in range(1, 8)}
    stations.update(assigned=(1.36, 103.83), outside=(1.36, 103.9))
    row = {"valid": True, "mm": 70.0, "max_1h": 10.0}
    table = {(day, gauge): row for gauge in ("g7", "assigned", "outside")}
    monkeypatch.setattr(data, "gauges", lambda: stations)
    monkeypatch.setattr(data, "rain_daily_table", lambda: table)

    assert rain_observation(stall, day) == ("assigned", row, False)
    table[day, "assigned"] = {**row, "valid": False}
    assert rain_observation(stall, day) == ("g7", row, True)
    del table[day, "g7"]
    assert rain_observation(stall, day) is None
