"""Phase 11: digital-only baseline, train-only fitting, unknown-vs-zero, seeded scenarios."""
import numpy as np
import pandas as pd
import pytest
from src.daycover.income_baseline import (BaselineConfig, IncomeBaseline, SCENARIOS, calibrate, daily_digital,
                                          load_receipts, margin_scenarios, missing_day_summary, run, score, simulate)


def receipts(path, cash=False, hold_in_train=False):
    rows = []
    rng = np.random.default_rng(1)
    for mi in range(6):
        hold = mi >= 4
        for d in pd.date_range("2025-01-01", "2025-12-31"):
            if d.day % 7 == 3 and mi == 0:
                continue  # unrecorded gap for one merchant
            split = "train" if d < pd.Timestamp("2025-09-01") else "validation" if d < pd.Timestamp("2025-11-01") else "test"
            if hold:
                split = "merchant_holdout"
                if hold_in_train and d.month == 1:
                    split = "train"
            for k in range(3):
                rows.append((f"M{mi}", f"C{mi % 2}", d.date().isoformat(), int(200 + 100 * mi + rng.integers(0, 50)),
                             "CASH_SIM" if cash and k == 0 else "simulated_sgqr_nets", split, "holdout" if hold else "development"))
    pd.DataFrame(rows, columns=["merchant_id", "centre_id", "trading_day", "amount_cents", "payment_method", "split",
                                "merchant_split"]).to_csv(path, index=False)
    return path


def test_cash_rows_rejected(tmp_path):
    with pytest.raises(ValueError, match="cash"):
        load_receipts(receipts(tmp_path / "r.csv", cash=True))


def test_holdout_in_training_rejected(tmp_path):
    d = daily_digital(load_receipts(receipts(tmp_path / "r.csv", hold_in_train=True)))
    with pytest.raises(ValueError, match="holdout"):
        IncomeBaseline().fit(d)


def test_fit_uses_train_only(tmp_path):
    d = daily_digital(load_receipts(receipts(tmp_path / "r.csv")))
    m = IncomeBaseline().fit(d)
    assert m.train_rows == int((d.split == "train").sum())
    d2 = d.copy()
    d2.loc[d2.split != "train", "digital_cents"] *= 100  # changing future rows must not change the fit
    m2 = IncomeBaseline().fit(d2)
    assert m.offsets == m2.offsets and m.g == m2.g


def test_missing_days_are_unknown_not_zero(tmp_path):
    d = daily_digital(load_receipts(receipts(tmp_path / "r.csv")))
    assert (d.digital_cents > 0).all()  # no invented zero rows
    s = missing_day_summary(d)
    assert s["days_without_digital_receipt"] > 0 and "unknown_not_zero" in s["treatment"]


def test_holdout_merchant_uses_cold_start_tier_and_interval_ordered(tmp_path):
    d = daily_digital(load_receipts(receipts(tmp_path / "r.csv")))
    m = IncomeBaseline(BaselineConfig()).fit(d)
    h = d[d.merchant_split == "holdout"]
    p = m.predict(h)
    assert set(p.tier) <= {"centre_weekday", "global_weekday"}
    assert (p.lo_cents <= p.pred_cents).all() and (p.pred_cents <= p.hi_cents).all()
    dev = m.predict(d[(d.merchant_id == "M1") & (d.split == "test")])
    assert set(dev.tier) == {"merchant_weekday"}
    assert score(h, p)["rows"] == len(h)


def test_rolling_is_past_only(tmp_path):
    d = daily_digital(load_receipts(receipts(tmp_path / "r.csv")))
    m = IncomeBaseline().fit(d)
    r = m.rolling_predict(d)
    d3 = d.copy()
    d3.loc[d3.trading_day >= "2025-06-01", "digital_cents"] *= 50
    r3 = m.rolling_predict(d3)
    early = r.trading_day < "2025-06-01"
    a = r[early].merge(r3[r3.trading_day < "2025-06-01"], on=["merchant_id", "trading_day"])
    assert (a.pred_cents_x == a.pred_cents_y).all()


def test_scenarios_seeded_labelled_and_states_distinct(tmp_path):
    d = daily_digital(load_receipts(receipts(tmp_path / "r.csv")))
    cal = calibrate(d)
    a = simulate(cal, "sparse_records", 8, 60, seed=7)
    b = simulate(cal, "sparse_records", 8, 60, seed=7)
    assert a.equals(b)
    assert not a.equals(simulate(cal, "sparse_records", 8, 60, seed=8))
    assert set(a.provenance) == {"simulated_assumption"}
    assert {"observed_sales", "unrecorded"} <= set(a.day_state)
    assert a.loc[a.day_state.isin(["unrecorded", "outage_missing"]), "digital_cents"].isna().all()
    assert (a.loc[a.day_state.isin(["closed", "verified_zero"]), "digital_cents"] == 0).all()
    assert (a.net_digital_cents.dropna() <= a.digital_cents.dropna()).all()
    mg = margin_scenarios(a)
    assert mg["basis"] == "assumption_not_verified" and "not_total_income" in mg["applies_to"]
    assert set(SCENARIOS) >= {"low_digital_volume", "payment_outage_heavy"}


def test_run_report_flags_and_no_cash_columns(tmp_path):
    r = run(receipts(tmp_path / "r.csv"), tmp_path / "out", sim_merchants=5, sim_days=30)
    assert r["cash_included"] is False and r["zero_sales_imputed"] is False
    assert r["real_world_accuracy_claim"] is False and r["weather_response_applied"] is False
    assert r["fit_split"] == "train"
    for e in r["evaluation"].values():
        assert e["statistical_baseline"]["rows"] > 0
    cols = pd.read_csv(tmp_path / "out" / "scenario_panels.csv").columns
    assert not any("cash" in c.lower() for c in cols)
