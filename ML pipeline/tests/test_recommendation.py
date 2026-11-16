"""Phase 13: advisory recommendations, fixed fallback, inclusivity, immutability and approval workflow."""
import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from src.daycover import contracts
from src.daycover.recommendation import (RecommendationStore, application_check, expected_payout, haze_year_payouts,
                                         band_rules, load_config, price_bands, recommend, earnings_profile)


def psi_frame():
    d = pd.date_range("2020-01-01", "2022-12-31")
    v = np.full(len(d), 60.0)
    v[10:16] = [110, 120, 160, 120, 130, 90]       # 2020: tier1 + tier2 + tier1 days
    return pd.DataFrame({"date": d.date.astype(str), "north": v})


def daily(n=60, level=10000, mid="M"):
    d = pd.date_range("2025-09-01", periods=n)
    return pd.DataFrame({"merchant_id": mid, "trading_day": d.date.astype(str), "digital_cents": level})


CFG = load_config()


def test_haze_replay_uses_exact_band_rules_and_caps():
    psi = psi_frame()
    m1 = band_rules(CFG["bands"]["M1_FIXED"])
    lite = band_rules(CFG["bands"]["LITE_90"])
    a, b = haze_year_payouts(psi, "north", m1), haze_year_payouts(psi, "north", lite)
    assert a[0] == 30 + 60 + 30 + 30 and a[1:] == [0, 0]   # 110->no (needs prior>=101), 120 t1, 160 t2, 120 t1, 130 t1
    assert b[0] == pytest.approx(a[0] / 2)


def test_combined_cap_applies_and_rain_once():
    r = band_rules(CFG["bands"]["M1_FIXED"])
    assert expected_payout([150.0], r, 180, 1.0) == 180.0
    assert expected_payout([0.0], r, 180, 1.0) == 30.0
    with pytest.raises(ValueError):
        expected_payout([], r, 180, 0.1)


def test_incomplete_years_not_zero_filled():
    psi = psi_frame().iloc[:500]
    assert len(haze_year_payouts(psi, "north", band_rules(CFG["bands"]["M1_FIXED"]))) == 1


def test_no_consent_or_sparse_history_gets_fixed_m1_without_penalty():
    psi = psi_frame()
    r = recommend("M", "north", "2025-11-15", daily(), psi, consent=False, cfg=CFG)
    assert r["recommendation"]["band"] == "M1_FIXED" and r["recommendation"]["penalty"] is False
    assert r["earnings_profile"] is None and r["recommendation"]["reason"] == "no_consent"
    r = recommend("M", "north", "2025-11-15", daily(n=5), psi, consent=True, cfg=CFG)
    assert r["recommendation"]["reason"] == "insufficient_digital_history"
    # fixed price identical irrespective of history
    assert r["pricing_by_band"]["M1_FIXED"]["central"]["indicative_annual_premium_cents"] == 10400


def test_history_is_past_only_and_scoped_to_digital():
    d = daily()
    p1 = earnings_profile(d, "M", "2025-10-15", CFG)
    d2 = d.copy(); d2.loc[d2.trading_day >= "2025-10-15", "digital_cents"] = 10**9
    assert p1 == earnings_profile(d2, "M", "2025-10-15", CFG)
    assert "not_total_or_cash" in p1["scope"]


def test_unaffordable_goes_to_fixed_with_review_and_outputs_separated():
    r = recommend("M", "north", "2025-11-15", daily(level=50), psi_frame(), True, CFG)
    assert r["recommendation"]["reason"] == "no_band_passes_affordability_test_review_needed"
    r = recommend("M", "north", "2025-11-15", daily(), psi_frame(), True, CFG)
    assert {"normal_earnings_cents_per_day", "estimated_loss_per_weather_day_sgd", "affordability"} <= set(r)
    assert r["estimated_loss_per_weather_day_sgd"]["basis"] == "assumption_not_verified"
    assert r["advisory_only"] and not r["applies_to_existing_terms"]


def test_recommendation_is_reproducible():
    a = recommend("M", "north", "2025-11-15", daily(), psi_frame(), True, CFG)
    assert a == recommend("M", "north", "2025-11-15", daily(), psi_frame(), True, CFG)


def test_m1_contract_and_prices_unchanged_by_recommendation():
    before = contracts.get_contract(contracts.M1_VERSION).sha256
    assert before == contracts.M1_SHA256
    price_bands(CFG, psi_frame(), "north")
    assert contracts.get_contract(contracts.M1_VERSION).sha256 == before
    assert CFG["bands"]["M1_FIXED"]["combined_cap_sgd"] == 180 and CFG["reference_annual_premium_cents"] == 10400


def _rec(store, band="LITE_90"):
    r = recommend("M", "north", "2025-11-15", daily(), psi_frame(), True, CFG)
    r["recommendation"]["band"] = band
    r["recommendation"]["registered_contract"] = CFG["bands"][band]["registered_contract"]
    return store.propose(r, now="2025-11-15T00:00:00+00:00"), r


def test_workflow_roles_independence_and_append_only(tmp_path):
    s = RecommendationStore(tmp_path / "r.sqlite3")
    rid, _ = _rec(s)
    assert s.state(rid) == "proposed"
    with pytest.raises(ValueError):
        s.record(rid, "reviewer_approved", "rev", "reviewer")           # needs customer acceptance first
    with pytest.raises(PermissionError):
        s.record(rid, "customer_accepted", "other", "customer", merchant_id="OTHER")
    with pytest.raises(PermissionError):
        s.record(rid, "customer_accepted", "M", "reviewer", merchant_id="M")
    s.record(rid, "customer_accepted", "M", "customer", merchant_id="M")
    with pytest.raises(PermissionError):
        s.record(rid, "reviewer_approved", "M", "reviewer")             # reviewer == merchant
    s.record(rid, "reviewer_approved", "rev1", "reviewer")
    assert [h["state"] for h in s.history(rid)] == ["proposed", "customer_accepted", "reviewer_approved"]
    with sqlite3.connect(tmp_path / "r.sqlite3") as c:
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("UPDATE recommendation_events SET state='x'")
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("DELETE FROM recommendations")
    assert s.propose(s.get(rid), now="2025-11-15T00:00:00+00:00") == rid     # idempotent


def test_decline_is_final_and_unpenalised(tmp_path):
    s = RecommendationStore(tmp_path / "r.sqlite3")
    rid, _ = _rec(s)
    s.record(rid, "customer_declined", "M", "customer", merchant_id="M")
    with pytest.raises(ValueError):
        s.record(rid, "customer_accepted", "M", "customer", merchant_id="M")


def test_application_blocked_for_candidates_existing_events_and_past_dates(tmp_path):
    s = RecommendationStore(tmp_path / "r.sqlite3")
    rid, _ = _rec(s)
    s.record(rid, "customer_accepted", "M", "customer", merchant_id="M")
    s.record(rid, "reviewer_approved", "rev", "reviewer")
    r = application_check(s, rid, "2026-01-01", "2026-01-01", "2025-12-01")
    assert not r["may_offer_on_new_term"] and "candidate_band_has_no_registered_contract_version" in r["blocked_reasons"]
    assert r["mutates_active_contract"] is False
    r = application_check(s, rid, "2026-01-01", "2026-01-01", "2025-12-01", registered={"candidate"}, existing_event_entitlement=True)
    assert "existing_event_entitlements_cannot_change" in r["blocked_reasons"]
    rid2, _ = _rec(RecommendationStore(tmp_path / "r2.sqlite3"), "M1_FIXED")
    s2 = RecommendationStore(tmp_path / "r2.sqlite3")
    s2.record(rid2, "customer_accepted", "M", "customer", merchant_id="M"); s2.record(rid2, "reviewer_approved", "rev", "reviewer")
    ok = application_check(s2, rid2, "2026-01-01", "2026-01-01", "2025-12-01")
    assert ok["may_offer_on_new_term"]
    bad = application_check(s2, rid2, "2025-11-01", "2026-01-01", "2025-12-01")
    assert "effective_date_must_be_a_future_new_issue_or_renewal_start" in bad["blocked_reasons"]


def test_unapproved_not_applicable(tmp_path):
    s = RecommendationStore(tmp_path / "r.sqlite3")
    rid, _ = _rec(s, "M1_FIXED")
    assert "not_customer_accepted_and_reviewer_approved" in application_check(s, rid, "2026-01-01", "2026-01-01", "2025-12-01")["blocked_reasons"]
