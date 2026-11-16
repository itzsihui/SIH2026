"""Phase 12: leakage-aware weather-impact audit and advisory model comparison (digital sales only).

Target (precise): ``log_deviation = ln(observed digital sales / baseline expected digital sales)`` for an observed
merchant-day. It is NOT gross-profit disruption (no verified margin), NOT trigger frequency (rules decide) and NOT
total/cash income. Weather features come only from official PSI-by-region and sampled station rain; a missing
reading stays missing. Synthetic data cannot establish real-world weather response. Models are advisory and are
adopted only if a paired bootstrap shows an improvement over the baseline on forward AND merchant-holdout windows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .income_baseline import BaselineConfig, IncomeBaseline, daily_digital, load_receipts

SCHEMA = "daycover.weather-impact.v1"
NS = "daycover_supplied_synthetic_v01:"
RAIN_BINS = [-0.1, 10, 30, 50, 1e9]
PSI_BINS = [0, 50, 100, 150, 1e9]
SOURCE_COLS = ["stall_id", "psi_region", "stall_type"]  # never read payment/margin columns


def merchant_meta(source_files) -> pd.DataFrame:
    parts = [pd.read_csv(f, usecols=SOURCE_COLS).drop_duplicates() for f in source_files]
    m = pd.concat(parts).drop_duplicates()
    if m.stall_id.duplicated().any():
        raise ValueError("merchant has inconsistent psi_region/stall_type in source")
    m["merchant_id"] = NS + m.stall_id
    return m.drop(columns="stall_id")


def island_rain(path) -> pd.DataFrame:
    """Island-mean rain on dates in the (stratified, non-exhaustive) station sample; valid station-days only."""
    r = pd.read_csv(path)
    r = r[r["is_valid_day"].astype(str).str.lower() == "true"]
    g = r.groupby("date").agg(rain_mm=("daily_rainfall_mm", "mean"), rain_stations=("station_id", "nunique"))
    return g.reset_index().rename(columns={"date": "trading_day"})


def psi_long(path) -> pd.DataFrame:
    p = pd.read_csv(path).melt(id_vars="date", var_name="psi_region", value_name="psi")
    return p.rename(columns={"date": "trading_day"})


def build_frame(daily: pd.DataFrame, model: IncomeBaseline, meta, psi, rain) -> pd.DataFrame:
    f = daily.merge(meta, on="merchant_id", how="left").merge(psi, on=["trading_day", "psi_region"], how="left") \
        .merge(rain, on="trading_day", how="left")
    pr = model.predict(f)
    f["expected"] = pr["pred_cents"].to_numpy()
    roll = model.rolling_predict(f).rename(columns={"pred_cents": "rolling_pred"})[["merchant_id", "trading_day", "rolling_pred"]]
    f = f.merge(roll, on=["merchant_id", "trading_day"], how="left")
    f["log_dev"] = np.log(f["digital_cents"] / f["expected"])
    f["log_dev_roll"] = np.log(f["digital_cents"] / f["rolling_pred"])
    f["rain_missing"] = f["rain_mm"].isna()
    f["psi_missing"] = f["psi"].isna()
    return f


def audit(f: pd.DataFrame) -> dict:
    out = {"target": "log(observed digital sales / baseline expected digital sales), observed days only",
           "weather_coverage_by_split": {}, "confounders_not_controlled": [
               "public holidays/school calendar: no verified calendar in repo",
               "stall closures: only digital-receipt presence is known; absent days are unknown, not closed",
               "payment outages: no outage log for supplied data",
               "trading hours: not in digital receipts"],
           "leakage_findings": [
               "legacy scripts/train_impact.py fills missing rain with 0 and PSI with 50 and needs absent qr_history/centre_day inputs: NOT reused",
               "legacy model fits 2023-24 and tests 2025 on a world generated with the same weather response: circular; NOT reused",
               "merchant baselines use train days only; holdout merchants never in fit; rolling comparator is past-only",
               "rain sample is stratified (non-exhaustive); selection into the rain sample may correlate with wet days"]}
    for s, g in f.groupby("split"):
        out["weather_coverage_by_split"][s] = {"rows": int(len(g)), "psi_known": float((~g.psi_missing).mean()),
                                                "rain_known": float((~g.rain_missing).mean()),
                                                "psi_gt_100_rows": int((g.psi > 100).sum()),
                                                "rain_ge_30_rows": int((g.rain_mm >= 30).sum())}
    return out


def features(f: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame({"psi": f["psi"], "rain_mm": f["rain_mm"], "weekday": f["weekday"]})
    return X  # NaN preserved: HistGradientBoosting treats it as missing, never as 0


def fit_band_effects(f: pd.DataFrame, target="log_dev_roll", shrink_n: int = 30) -> dict:
    """Pooled mean log deviation per PSI/rain band relative to the clear reference band, shrunk toward 0."""
    tr = f[(f.split == "train") & f[target].notna()]
    eff = {}
    for name, col, bins in (("psi", "psi", PSI_BINS), ("rain", "rain_mm", RAIN_BINS)):
        b = pd.cut(tr[col], bins, labels=False, right=True, include_lowest=True)
        ref = tr.loc[b == 0, target].mean() if (b == 0).any() else 0.0
        eff[name] = {}
        for k in sorted(b.dropna().unique()):
            x = tr.loc[b == k, target]
            eff[name][int(k)] = float((x.mean() - ref) * len(x) / (len(x) + shrink_n))
    return eff


def apply_band(f: pd.DataFrame, eff: dict) -> np.ndarray:
    adj = np.zeros(len(f))
    for name, col, bins in (("psi", "psi", PSI_BINS), ("rain", "rain_mm", RAIN_BINS)):
        b = pd.cut(f[col], bins, labels=False, right=True, include_lowest=True)
        adj += b.map(lambda k: eff[name].get(int(k), 0.0) if pd.notna(k) else 0.0).to_numpy(float)
    return adj


def fit_gbm(f: pd.DataFrame, seed: int, target="log_dev_roll", cols=None):
    from sklearn.ensemble import HistGradientBoostingRegressor
    tr = f[(f.split == "train") & f[target].notna()]
    m = HistGradientBoostingRegressor(max_iter=100, learning_rate=0.05, max_depth=3, min_samples_leaf=50, random_state=seed)
    X = features(tr)
    return m.fit(X[cols] if cols else X, tr[target].clip(-2, 2))


def wape(y, p):
    return float(np.sum(np.abs(y - p)) / np.sum(y))


def paired_bootstrap(y, p0, p1, groups, seed, n=300):
    """Improvement in WAPE (baseline minus candidate) with merchant-cluster bootstrap CI; >0 means candidate better."""
    rng = np.random.default_rng(seed)
    ug = np.unique(groups)
    idx = {g: np.flatnonzero(groups == g) for g in ug}
    diffs = []
    for _ in range(n):
        pick = rng.choice(ug, len(ug))
        i = np.concatenate([idx[g] for g in pick])
        diffs.append(wape(y[i], p0[i]) - wape(y[i], p1[i]))
    return {"improvement": wape(y, p0) - wape(y, p1), "ci95": [float(np.quantile(diffs, .025)), float(np.quantile(diffs, .975))]}


def compare(f: pd.DataFrame, seed: int) -> dict:
    eff = fit_band_effects(f)
    gbm = fit_gbm(f, seed)
    ctrl = fit_gbm(f, seed, cols=["weekday"])  # ablation control: same learner, no weather
    res = {"band_effects_train_only": eff, "windows": {}}
    wins = {"validation_forward": f.split == "validation", "test_forward": f.split == "test",
            "merchant_holdout_future": (f.split == "merchant_holdout") & (f.trading_day >= "2025-11-01")}
    for name, sel in wins.items():
        g = f[sel & f.rolling_pred.notna()].copy()
        if g.empty:
            res["windows"][name] = {"rows": 0}
            continue
        y = g.digital_cents.to_numpy(float)
        p0 = g.rolling_pred.to_numpy(float)  # baseline: past-only rolling median (works for holdout merchants too)
        cands = {"band_effects": p0 * np.exp(apply_band(g, eff)),
                 "gbm_weekday_only_control": p0 * np.exp(ctrl.predict(features(g)[["weekday"]])),
                 "gbm": p0 * np.exp(gbm.predict(features(g)))}
        w = {"rows": int(len(g)), "baseline_wape": wape(y, p0), "weather_rows_exposed": int(((g.psi > 100) | (g.rain_mm >= 30)).sum())}
        for c, p in cands.items():
            w[c] = {"wape": wape(y, p), **paired_bootstrap(y, p0, p, g.merchant_id.to_numpy(), seed)}
        for c in ("band_effects", "gbm"):  # weather value over a no-weather control with the same learner/baseline
            ctl = cands["gbm_weekday_only_control"] if c == "gbm" else p0
            w[c]["vs_no_weather_control"] = paired_bootstrap(y, ctl, cands[c], g.merchant_id.to_numpy(), seed)
        # exposed-days-only comparison, where a weather model could matter
        ex = ((g.psi > 100) | (g.rain_mm >= 30)).to_numpy()
        if ex.sum() >= 30:
            w["exposed_days"] = {"rows": int(ex.sum()), "baseline_wape": wape(y[ex], p0[ex]),
                                 **{c: wape(y[ex], p[ex]) for c, p in cands.items()}}
        res["windows"][name] = w
    sub = {}
    g = f[(f.split == "test") & f.rolling_pred.notna()]
    for col in ("stall_type", "psi_region"):
        sub[col] = {str(k): {"rows": int(len(x)), "baseline_wape": wape(x.digital_cents.to_numpy(float), x.rolling_pred.to_numpy(float))}
                    for k, x in g.groupby(col)}
    cnt = f[f.split == "train"].groupby("merchant_id").size()
    tier = pd.qcut(cnt.rank(method="first"), 3, labels=["low_history", "mid_history", "high_history"])
    g = g.assign(hist=g.merchant_id.map(tier))
    sub["train_history_tercile"] = {str(k): {"rows": int(len(x)), "baseline_wape": wape(x.digital_cents.to_numpy(float), x.rolling_pred.to_numpy(float))}
                                    for k, x in g.groupby("hist", observed=True)}
    res["subgroups_test_baseline"] = sub
    res["candidate_adoption"] = {}
    for c in ("band_effects", "gbm"):
        need = ("test_forward", "merchant_holdout_future")
        exposed = all(res["windows"][n].get("weather_rows_exposed", 0) >= 30 for n in need)
        ok = exposed and all(res["windows"][n][c]["vs_no_weather_control"]["ci95"][0] > 0 for n in need)
        res["candidate_adoption"][c] = ("adopt_advisory" if ok else
                                        "reject_retain_baseline:insufficient_weather_exposure" if not exposed
                                        else "reject_retain_baseline")
    return res


def run(receipts_path, source_files, psi_path, rain_path, out_dir, seed: int = 20261116) -> dict:
    rp = Path(receipts_path)
    manifest = json.loads(rp.with_name("manifest.json").read_text()) if rp.with_name("manifest.json").exists() else {}
    daily = daily_digital(load_receipts(rp))
    model = IncomeBaseline(BaselineConfig()).fit(daily)
    f = build_frame(daily, model, merchant_meta(source_files), psi_long(psi_path), island_rain(rain_path))
    rep = {"schema_version": SCHEMA, "dataset_build_id": manifest.get("build_id"),
           "receipts_sha256": hashlib.sha256(rp.read_bytes()).hexdigest(), "seed": seed,
           "feature_set_version": "psi_region+island_rain+weekday.v1", "model_status": "advisory_only",
           "cash_features": False, "missing_weather_filled": False, "real_world_accuracy_claim": False,
           "provenance": "calibrated_synthetic_only", "audit": audit(f), "comparison": compare(f, seed),
           "failure_modes": ["synthetic data may contain no weather response", "island-mean rain ignores gauge/centre location",
                             "psi_region label is synthetic and unmapped to real centres", "rain sample non-exhaustive",
                             "rain timestamp convention unresolved (Phase 5 gate)", "foreign data not transferred"],
           "rollback": "retain income_baseline (Phase 11); a rejected candidate is never wired into any rule or price"}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "weather_impact_report.json").write_text(json.dumps(rep, indent=1, sort_keys=True, default=str))
    return rep
