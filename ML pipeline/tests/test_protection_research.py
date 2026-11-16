"""Phase 14: protection research is exact, honest about exposure, and cannot alter the contract."""
import sqlite3

import numpy as np
import pandas as pd
import pytest
from src.daycover import contracts
from src.daycover.protection_research import (ASSUMPTIONS, DESIGNS, ProposalStore, design_rules, gauge_disagreement,
                                              haze_events, liquidity_year, max_liability_case, portfolio, protection_quality,
                                              sparse_psi_stress, wilson, year_table)


def psi_frame(extra=None):
    d = pd.date_range("2018-01-01", "2020-12-31")
    df = pd.DataFrame({"date": d.date.astype(str)})
    for r in ("north", "south", "east", "west", "central"):
        v = np.full(len(d), 60.0)
        v[100:106] = [110, 120, 160, 210, 130, 90]
        df[r] = v
    return df


def test_exact_caps_and_design_difference():
    psi = psi_frame()
    m1, _ = design_rules("M1_180")
    alt, _ = design_rules("ALT_150_M1_TRIGGERS")
    a = sum(x for _, x in haze_events(psi, "north", m1)[2018])
    b = sum(x for _, x in haze_events(psi, "north", alt)[2018])
    assert a == 150 and b == 120
    assert [x for _, x in haze_events(psi, "north", m1)[2018]] == [30, 60, 60]
    assert [x for _, x in haze_events(psi, "north", alt)[2018]] == [30, 60, 30]
    assert [x for _, x in haze_events(psi, "north", design_rules("PLAN4_STYLE_150")[0])[2018]] == [30, 30, 60]


def test_incomplete_years_skipped_not_zero():
    assert haze_events(psi_frame().iloc[:500], "north", design_rules("M1_180")[0]).keys() == {2018}


def test_m1_unchanged_and_non_m1_designs_not_executable():
    assert contracts.get_contract(contracts.M1_VERSION).sha256 == contracts.M1_SHA256
    assert DESIGNS["M1_180"]["executable"] and not DESIGNS["ALT_150_M1_TRIGGERS"]["executable"] and not DESIGNS["PLAN4_STYLE_150"]["executable"]


def test_max_liability_and_reinsurance_cap():
    m = max_liability_case("M1_180", 104.0, 0.0)
    assert m["claims_sgd"] == 180_000 and m["reinsurance_recovery_sgd"] == pytest.approx(180_000 - 156_000)
    assert max_liability_case("ALT_150_M1_TRIGGERS", 104.0, 0.0)["claims_sgd"] == 150_000


def test_portfolio_reproducible_and_clustering_raises_tail():
    psi = psi_frame()
    a = dict(ASSUMPTIONS, simulations=2000)
    x = portfolio(psi, "M1_180", 104.0, 0.15, None, 0.05, a)
    assert x == portfolio(psi, "M1_180", 104.0, 0.15, None, 0.05, a) and x["solvency_guarantee"] is False
    c = portfolio(psi, "M1_180", 104.0, 0.15, 0.6, 0.05, a)
    assert c["claims_p99_sgd"] >= x["claims_p99_sgd"] and 0 <= x["prob_net_negative_no_reinsurance"] <= 1
    worse = portfolio(psi, "M1_180", 104.0, 0.15, None, 0.15, a)
    assert worse["net_result_p01_no_reinsurance_sgd"] <= x["net_result_p01_no_reinsurance_sgd"]


def test_liquidity_timing_peak_deficit():
    r = liquidity_year(psi_frame(), "M1_180", 2018, 104.0, 1000, 0.0)
    assert r["annual_claims_sgd"] > r["annual_premium_collected_sgd"] and r["peak_cumulative_deficit_sgd"] > 0


def test_sparse_missing_is_never_filled_and_shortfall_nonnegative():
    r = sparse_psi_stress(psi_frame().assign(date=lambda d: d.date), design_rules("M1_180")[0], shares=(0.3,))
    assert r["missing_30pct"]["blank_readings"] > 0 and "never filled" in r["treatment"]


def test_protection_quality_counts_and_low_power():
    pl = pd.DataFrame({"trading_day": ["2025-01-01", "2025-01-02", "2025-01-03"] * 1, "psi_region": ["north"] * 3, "psi": [60, 120, 160.0]})
    pl = pd.concat([pl, pd.DataFrame({"trading_day": ["2024-12-31"], "psi_region": ["north"], "psi": [60.0]})])
    f = pd.DataFrame({"trading_day": ["2025-01-01", "2025-01-02", "2025-01-03"], "psi_region": "north", "psi": [60, 120, 160.0],
                      "rolling_pred": [1000.0] * 3, "digital_cents": [1000.0, 500.0, 1000.0]})
    q = protection_quality(f, pl, design_rules("M1_180")[0])
    assert q["trigger_days"] == 1 and q["disrupted_days"] == 1 and q["trigger_and_disrupted"] == 0
    assert q["paid_without_measured_disruption"] == 1 and q["missed_disruption_days"] == 1 and q["low_power"]


def test_wilson_and_gauge_disagreement():
    assert wilson(0, 0) is None and 0 <= wilson(5, 10)[0] < 0.5 < wilson(5, 10)[1] <= 1
    rain = pd.DataFrame({"date": ["d1", "d1", "d2", "d2"], "station_id": ["A", "B", "A", "B"], "daily_rainfall_mm": [80, 10, 20, 30],
                         "is_valid_day": [True] * 4})
    st = pd.DataFrame({"id": ["A", "B"], "latitude": [1.3, 1.301], "longitude": [103.8, 103.8]})
    g = gauge_disagreement(rain, st)
    assert g["trigger_days_at_A"] == 1 and g["B_also_triggers"] == 0 and g["p_B_given_A"] == 0.0


def test_proposal_store_append_only_and_cannot_rewrite_existing_version(tmp_path):
    s = ProposalStore(tmp_path / "p.sqlite3")
    pid = s.propose("optimiser", "ALT_150_M1_TRIGGERS", {"x": 1})
    assert pid == s.propose("optimiser", "ALT_150_M1_TRIGGERS", {"x": 1})
    with pytest.raises(ValueError):
        s.decide(pid, "approved_for_future_version", "rev", "n", contracts.M1_VERSION)
    with pytest.raises(ValueError):
        s.decide(pid, "approved_for_future_version", "rev", "n")
    s.decide(pid, "approved_for_future_version", "rev", "n", "daycover-pilot-m1-2027.11-v2")
    assert len(s.decisions(pid)) == 1
    with sqlite3.connect(tmp_path / "p.sqlite3") as c, pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM proposals")
    assert contracts.get_contract(contracts.M1_VERSION).sha256 == contracts.M1_SHA256
