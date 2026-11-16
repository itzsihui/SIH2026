"""Phase 12: weather-impact audit guards (no invented weather, train-only fits, honest adoption)."""
import numpy as np
import pandas as pd
import pytest
from src.daycover.weather_impact import (NS, apply_band, compare, features, fit_band_effects, island_rain, merchant_meta,
                                         paired_bootstrap, psi_long, wape)


def frame(n=600, effect=0.0, seed=0, rain_known=1.0):
    rng = np.random.default_rng(seed)
    d = pd.date_range("2025-01-01", periods=n)
    rows = []
    for m in range(6):
        for i, day in enumerate(d):
            rain = rng.choice([0.0, 5.0, 40.0], p=[.6, .2, .2])
            ld = rng.normal(0, 0.1) + (effect * -1 if rain >= 30 else 0)
            exp = 10000.0
            split = "train" if i < 300 else "validation" if i < 400 else "test"
            if m >= 4:
                split = "merchant_holdout"
            rows.append(dict(merchant_id=f"M{m}", trading_day=day.date().isoformat(), split=split, weekday=day.day_of_week,
                             psi=60.0, rain_mm=rain if rng.random() < rain_known else np.nan, psi_region="north",
                             stall_type="x", digital_cents=exp * np.exp(ld), rolling_pred=exp,
                             log_dev_roll=ld))
    return pd.DataFrame(rows)


def test_missing_weather_stays_missing_and_is_not_zero():
    f = frame(rain_known=0.5)
    assert f.rain_mm.isna().any()
    X = features(f)
    assert X.rain_mm.isna().sum() == f.rain_mm.isna().sum()


def test_band_effects_use_train_only():
    f = frame(effect=0.3)
    e1 = fit_band_effects(f)
    g = f.copy()
    g.loc[g.split != "train", "log_dev_roll"] += 5
    assert e1 == fit_band_effects(g)
    assert e1["rain"][2] < -0.2


def test_paired_bootstrap_detects_improvement_and_null():
    rng = np.random.default_rng(1)
    y = rng.uniform(5, 15, 400)
    g = np.repeat(np.arange(20), 20)
    good = paired_bootstrap(y, y * 1.5, y * 1.01, g, 1, 100)
    assert good["ci95"][0] > 0
    null = paired_bootstrap(y, y * 1.1, y * 1.1, g, 1, 100)
    assert null["improvement"] == 0 and null["ci95"] == [0.0, 0.0]


def test_no_weather_effect_not_adopted_even_with_exposure():
    r = compare(frame(effect=0.0), seed=3)
    assert r["candidate_adoption"]["gbm"].startswith("reject")
    assert r["candidate_adoption"]["band_effects"].startswith("reject")


def test_real_effect_with_exposure_is_adoptable():
    r = compare(frame(effect=0.3), seed=3)
    assert r["candidate_adoption"]["gbm"] == "adopt_advisory"


def test_insufficient_exposure_rejects():
    f = frame(effect=0.3)
    f["rain_mm"] = 0.0
    r = compare(f, seed=3)
    assert r["candidate_adoption"]["gbm"].endswith("insufficient_weather_exposure")


def test_meta_only_reads_non_financial_columns_and_rejects_conflicts(tmp_path):
    p = tmp_path / "s.csv"
    pd.DataFrame({"stall_id": ["A", "A", "B"], "psi_region": ["n", "n", "s"], "stall_type": ["t", "t", "u"],
                  "payment_method": ["CASH_SIM", "X", "Y"]}).to_csv(p, index=False)
    m = merchant_meta([p])
    assert set(m.columns) == {"psi_region", "stall_type", "merchant_id"} and m.merchant_id.iloc[0].startswith(NS)
    q = tmp_path / "t.csv"
    pd.DataFrame({"stall_id": ["A"], "psi_region": ["e"], "stall_type": ["t"]}).to_csv(q, index=False)
    with pytest.raises(ValueError):
        merchant_meta([p, q])


def test_rain_only_valid_days_and_psi_long(tmp_path):
    p = tmp_path / "r.csv"
    pd.DataFrame({"date": ["2025-01-01"] * 2, "station_id": ["a", "b"], "daily_rainfall_mm": [10.0, 99.0],
                  "is_valid_day": [True, False]}).to_csv(p, index=False)
    assert island_rain(p).rain_mm.iloc[0] == 10.0
    q = tmp_path / "p.csv"
    pd.DataFrame({"date": ["2025-01-01"], "north": [50], "south": [60]}).to_csv(q, index=False)
    assert len(psi_long(q)) == 2
