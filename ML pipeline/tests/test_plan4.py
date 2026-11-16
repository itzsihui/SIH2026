"""README Plan 4 rules: boundaries, caps, priority, policy-year anniversary and replay consistency. M1 stays frozen."""
from datetime import date, timedelta
import pytest
from src.daycover import contracts
from src.daycover.plan4 import Plan4Engine, TERMS, replay

D = date(2026, 3, 1)
INC = date(2026, 1, 1)


def one(eng, day, rain=None, psi=None, yest=None, closed=False):
    return {x["peril"]: x for x in eng.evaluate_day(day, rain, psi, yest, closed)}


@pytest.mark.parametrize("psi,yest,expect", [(100, 120, 0), (101, 100, 0), (101, 101, 3000), (150, 101, 3000), (200, 150, 3000), (201, 0, 6000), (200, None, "pending")])
def test_haze_boundaries(psi, yest, expect):
    r = one(Plan4Engine(INC), D, rain=0.0, psi=psi, yest=yest)["haze"]
    assert (r["status"] == "pending") if expect == "pending" else r["amount_cents"] == expect


@pytest.mark.parametrize("mm,expect", [(69.9, 0), (70.0, 3000), (None, "pending")])
def test_rain_boundaries(mm, expect):
    r = one(Plan4Engine(INC), D, rain=mm, psi=50, yest=50)["rain"]
    assert (r["status"] == "pending") if expect == "pending" else r["amount_cents"] == expect


def test_allowances_three_moderate_two_severe_and_haze_subcap():
    e = Plan4Engine(INC)
    paid = [one(e, D + timedelta(days=i), 0.0, 150, 150)["haze"] for i in range(4)]
    assert [p["amount_cents"] for p in paid] == [3000, 3000, 3000, 0] and paid[3]["status"] == "capped"
    sev = [one(e, D + timedelta(days=10 + i), 0.0, 250, 0)["haze"] for i in range(3)]
    assert [s["amount_cents"] for s in sev] == [3000, 0, 0]          # 90 used: S$120 haze subcap curtails the first severe day to S$30
    assert e.state_for(D).haze_cents == 12000 and e.state_for(D).total_cents == 12000


def test_rain_bucket_is_reserved_and_annual_cap_150():
    e = Plan4Engine(INC)
    for i in range(3):
        one(e, D + timedelta(days=i), 0.0, 250, 0)                       # haze exhausts S$120 before any rain
    r = one(e, D + timedelta(days=30), 80.0, 50, 50)["rain"]
    assert r["amount_cents"] == 3000 and r["remaining_combined_cents"] == 0
    assert one(e, D + timedelta(days=60), 80.0, 50, 50)["rain"]["status"] == "capped"   # one rain day per policy year
    assert e.state_for(D).total_cents == 15000


def test_same_day_severe_haze_and_rain_daily_ceiling():
    e = Plan4Engine(INC)
    r = one(e, D, 80.0, 230, 0)
    assert r["rain"]["amount_cents"] == 3000 and r["haze"]["amount_cents"] == 3000 and e.state_for(D).paid_by_day[str(D)] == 6000
    assert "curtailed" in r["haze"]["reason"]


def test_closure_excludes_without_consuming_caps_and_missing_is_pending_not_zero():
    e = Plan4Engine(INC)
    c = one(e, D, 80.0, 250, 0, closed=True)
    assert all(x["status"] == "excluded" and x["amount_cents"] == 0 for x in c.values()) and e.state_for(D).total_cents == 0
    assert one(e, D, None, None, None)["rain"]["status"] == "pending"


def test_september_policy_year_does_not_reset_on_january_first():
    e = Plan4Engine(date(2026, 9, 1))
    one(e, date(2026, 12, 20), 80.0, 50, 50)
    assert one(e, date(2027, 1, 5), 80.0, 50, 50)["rain"]["status"] == "capped"          # same policy year
    assert one(e, date(2027, 9, 2), 80.0, 50, 50)["rain"]["status"] == "paid"            # renewal anniversary: new year
    with pytest.raises(ValueError):
        e.evaluate_day(date(2026, 8, 31), 80.0, 50, 50)                                  # before inception: no cover


def test_leap_day_anniversary_convention():
    e = Plan4Engine(date(2028, 2, 29))
    assert e.state_for(date(2029, 2, 28)).start == date(2029, 2, 28)


def test_full_year_and_slice_replays_agree_on_overlap():
    days = [{"day": str(date(2026, 1, 1) + timedelta(days=i)), "rain_mm": 80.0 if i in (40, 41) else 5.0,
             "psi": 130 if i in (10, 11, 12, 100, 101) else 250 if i == 200 else 60} for i in range(365)]
    full = replay(date(2026, 1, 1), days)
    sliced = replay(date(2026, 1, 1), days[:150])
    key = lambda x: (x["day"], x["peril"], x["status"], x["amount_cents"])
    assert [key(x) for x in full if x["day"] <= days[149]["day"]] == [key(x) for x in sliced]


def test_m1_unchanged_and_plan4_not_enrolable():
    assert contracts.get_contract(contracts.M1_VERSION).sha256 == contracts.M1_SHA256
    assert TERMS["version"] == "candidate-plan4-150-proposal-v1"
    with pytest.raises(ValueError):
        contracts.simulation_contract(TERMS["version"])
    assert TERMS["heat_or_flood_payable"] is False and TERMS["annual_combined_cap"] == 150
