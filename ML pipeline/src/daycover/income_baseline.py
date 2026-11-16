"""Phase 11: digital-sales statistical baseline and labelled scenario simulator.

Scope guards (see AGENTS.md / prompts.md):
* Input is only the Phase 10 digital receipt file; cash, cash share and total income are never modelled.
* Days with no digital receipt are UNKNOWN (not zero) unless a caller supplies verified trading evidence.
* Everything is fitted on ``split == 'train'`` rows. Validation/test/holdout rows are only scored.
* Output is advisory research. It is not weather-loss ground truth and not real-world accuracy evidence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = "daycover.income-baseline.v1"
TRAIN = "train"
QUANTILES = (0.1, 0.5, 0.9)  # nominal 80% central interval
TIERS = ("merchant_weekday", "merchant_pooled", "centre_weekday", "global_weekday")
STATES = ("observed_sales", "verified_zero", "closed", "outage_missing", "unrecorded")


@dataclass(frozen=True)
class BaselineConfig:
    min_merchant_weekday_days: int = 4   # observed train days for the merchant+weekday tier
    min_merchant_days: int = 14          # observed train days for the merchant tier
    min_centre_days: int = 30
    rolling_days: int = 28
    rolling_min_days: int = 8
    seed: int = 20261116


def load_receipts(path: str | Path) -> pd.DataFrame:
    cols = ["merchant_id", "centre_id", "trading_day", "amount_cents", "payment_method", "split", "merchant_split"]
    df = pd.read_csv(path, usecols=cols)
    if df["payment_method"].str.contains("cash", case=False).any():
        raise ValueError("cash receipts must never reach the Phase 11 baseline")
    if (df["amount_cents"] <= 0).any():
        raise ValueError("non-positive digital amounts are not allowed")
    return df


def daily_digital(receipts: pd.DataFrame) -> pd.DataFrame:
    """One row per merchant-day that has at least one digital receipt (observed days only)."""
    g = receipts.groupby(["merchant_id", "centre_id", "trading_day", "split", "merchant_split"], sort=True)
    out = g.agg(digital_cents=("amount_cents", "sum"), digital_receipts=("amount_cents", "size")).reset_index()
    out["date"] = pd.to_datetime(out["trading_day"])
    out["weekday"] = out["date"].dt.day_of_week
    out["day_state"] = "observed_sales"
    return out


class IncomeBaseline:
    """Weekday/pooled digital-sales medians with empirical log-ratio intervals, fitted on train only."""

    def __init__(self, cfg: BaselineConfig | None = None):
        self.cfg = cfg or BaselineConfig()
        self.fitted = False

    def fit(self, daily: pd.DataFrame) -> "IncomeBaseline":
        tr = daily[daily["split"] == TRAIN]
        if tr.empty:
            raise ValueError("no training rows")
        if (daily.loc[daily["merchant_split"] == "holdout", "split"] == TRAIN).any():
            raise ValueError("holdout merchants must not be in training")
        c = self.cfg
        self.mw = tr.groupby(["merchant_id", "weekday"]).digital_cents.agg(["median", "size"])
        self.m = tr.groupby("merchant_id").digital_cents.agg(["median", "size"])
        self.cw = tr.groupby(["centre_id", "weekday"]).digital_cents.agg(["median", "size"])
        self.c = tr.groupby("centre_id").digital_cents.agg(["median", "size"])
        self.gw = tr.groupby("weekday").digital_cents.median()
        self.g = float(tr.digital_cents.median())
        pred, tier = self._point(tr, use_self=True)
        lr = np.log(tr["digital_cents"].to_numpy() / pred)
        # interval offsets per tier from training residuals (in-sample, so slightly optimistic; checked out of sample)
        self.offsets = {}
        for t in ("merchant_weekday", "merchant_pooled"):
            x = lr[tier == t]
            if len(x) >= 50:
                self.offsets[t] = tuple(float(v) for v in np.quantile(x, QUANTILES))
        # cold-start tiers: leave-one-merchant-out residuals, so a merchant never helps predict itself
        cold = []
        for mid, g in tr.groupby("merchant_id"):
            rest = tr[tr["merchant_id"] != mid]
            cm = rest.groupby(["centre_id", "weekday"]).digital_cents.median()
            gm = rest.groupby("weekday").digital_cents.median()
            key = pd.MultiIndex.from_frame(g[["centre_id", "weekday"]])
            ref = cm.reindex(key).to_numpy()
            ref = np.where(np.isnan(ref), g["weekday"].map(gm).to_numpy(), ref)
            cold.append(np.log(g["digital_cents"].to_numpy() / ref))
        cold = np.concatenate(cold)
        cold_off = tuple(float(v) for v in np.quantile(cold, QUANTILES))
        self.offsets["centre_weekday"] = self.offsets["global_weekday"] = cold_off
        allx = lr
        fallback = tuple(float(v) for v in np.quantile(allx, QUANTILES))
        for t in TIERS:
            self.offsets.setdefault(t, fallback)
        self.train_rows = int(len(tr))
        self.fitted = True
        return self

    def _point(self, df: pd.DataFrame, use_self: bool = False):
        c = self.cfg
        n = len(df)
        pred = np.full(n, self.g)
        tier = np.array(["global_weekday"] * n, dtype=object)
        gw = df["weekday"].map(self.gw).to_numpy()
        ok = ~np.isnan(gw)
        pred[ok] = gw[ok]
        for name, idx_cols, table, min_n, series in (
            ("centre_weekday", ["centre_id", "weekday"], self.cw, c.min_centre_days, None),
            ("merchant_pooled", ["merchant_id"], self.m, c.min_merchant_days, None),
            ("merchant_weekday", ["merchant_id", "weekday"], self.mw, c.min_merchant_weekday_days, None),
        ):
            key = pd.MultiIndex.from_frame(df[idx_cols]) if len(idx_cols) > 1 else pd.Index(df[idx_cols[0]])
            t = table.reindex(key)
            med, cnt = t["median"].to_numpy(), t["size"].to_numpy()
            m = ~np.isnan(med) & (np.nan_to_num(cnt) >= min_n)
            if name == "merchant_pooled":
                # a merchant-level median is scaled by the global weekday shape to keep weekday seasonality
                shape = gw / self.g if self.g else 1.0
                med = med * np.where(ok, shape, 1.0)
            pred[m] = med[m]
            tier[m] = name
        return np.maximum(pred, 1.0), tier

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted:
            raise ValueError("fit first")
        pred, tier = self._point(df)
        lo = np.array([self.offsets[t][0] for t in tier])
        md = np.array([self.offsets[t][1] for t in tier])
        hi = np.array([self.offsets[t][2] for t in tier])
        out = df[["merchant_id", "trading_day"]].copy()
        out["tier"] = tier
        out["pred_cents"] = np.round(pred * np.exp(md)).astype(np.int64)
        out["lo_cents"] = np.round(pred * np.exp(lo)).astype(np.int64)
        out["hi_cents"] = np.round(pred * np.exp(hi)).astype(np.int64)
        return out

    def rolling_predict(self, daily: pd.DataFrame) -> pd.DataFrame:
        """Median of the merchant's own observed digital days in the prior window; past-only, no fitting."""
        c = self.cfg
        out = []
        for mid, g in daily.sort_values("date").groupby("merchant_id", sort=False):
            s = g.set_index("date")["digital_cents"]
            prior = s.rolling(f"{c.rolling_days}D", closed="left")
            m = prior.median()
            n = prior.count()
            r = pd.DataFrame({"merchant_id": mid, "trading_day": g["trading_day"].to_numpy(),
                              "pred_cents": m.to_numpy(), "n": n.to_numpy()})
            out.append(r[r["n"] >= c.rolling_min_days])
        return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["merchant_id", "trading_day", "pred_cents", "n"])


def score(daily: pd.DataFrame, pred: pd.DataFrame) -> dict:
    """Metrics on observed digital days only. Unknown days are counted elsewhere, never scored as zero."""
    j = daily.merge(pred, on=["merchant_id", "trading_day"], how="inner")
    if j.empty:
        return {"rows": 0}
    y, p = j["digital_cents"].to_numpy(float), j["pred_cents"].to_numpy(float)
    res = {"rows": int(len(j)), "mae_cents": float(np.mean(np.abs(y - p))),
           "wape": float(np.sum(np.abs(y - p)) / np.sum(y)), "bias_ratio": float(np.sum(p) / np.sum(y))}
    if "lo_cents" in j:
        cov = (y >= j["lo_cents"]) & (y <= j["hi_cents"])
        res["interval_nominal"] = 0.8
        res["interval_coverage"] = float(cov.mean())
        res["mean_interval_width_cents"] = float((j["hi_cents"] - j["lo_cents"]).mean())
        res["coverage_by_tier"] = {t: {"rows": int((j.tier == t).sum()), "coverage": float(cov[j.tier == t].mean())}
                                    for t in TIERS if (j.tier == t).any()}
    return res


def missing_day_summary(daily: pd.DataFrame) -> dict:
    """Calendar gaps between a merchant's first/last observed day. They are 'unknown', not zero sales."""
    gaps = 0
    spans = 0
    for _, g in daily.groupby("merchant_id"):
        d = g["date"]
        spans += (d.max() - d.min()).days + 1
        gaps += (d.max() - d.min()).days + 1 - d.nunique()
    return {"merchant_calendar_days": int(spans), "days_without_digital_receipt": int(gaps),
            "treatment": "unknown_not_zero; no closure/outage/trading evidence supplied"}


# ----------------------------------------------------------------------------- scenario simulator

# Every value is a labelled ASSUMPTION unless noted. None is a verified Singapore observation.
SCENARIOS = {
    "train_calibrated": {"label": "calibrated to training-split digital aggregates only", "volume_mult": 1.0,
                         "outage_rate": 0.01, "closure_rate": 0.03, "unrecorded_rate": 0.02, "refund_rate": 0.01,
                         "basis": "assumption", "zero_sales_rate_of_open_days": 0.0},
    "low_digital_volume": {"label": "assumed low digital adoption", "volume_mult": 0.4, "outage_rate": 0.01,
                           "closure_rate": 0.03, "unrecorded_rate": 0.03, "refund_rate": 0.01, "basis": "assumption",
                           "zero_sales_rate_of_open_days": 0.08},
    "high_digital_volume": {"label": "assumed high digital adoption", "volume_mult": 2.0, "outage_rate": 0.01,
                            "closure_rate": 0.03, "unrecorded_rate": 0.01, "refund_rate": 0.01, "basis": "assumption",
                            "zero_sales_rate_of_open_days": 0.0},
    "sparse_records": {"label": "assumed sparse digital records", "volume_mult": 1.0, "outage_rate": 0.05,
                       "closure_rate": 0.05, "unrecorded_rate": 0.25, "refund_rate": 0.02, "basis": "assumption",
                       "zero_sales_rate_of_open_days": 0.02},
    "payment_outage_heavy": {"label": "assumed frequent payment outages", "volume_mult": 1.0, "outage_rate": 0.15,
                             "closure_rate": 0.03, "unrecorded_rate": 0.02, "refund_rate": 0.01, "basis": "assumption",
                             "zero_sales_rate_of_open_days": 0.0},
}
MARGIN_ASSUMPTIONS = {"low": 0.30, "central": 0.45, "high": 0.60}  # labelled assumptions, no verified margin data
WEATHER_RESPONSE_PLACEHOLDER = {"applied": False, "note": "No verified weather-sales response exists; the simulator "
                                "applies none. Any weather-loss scenario must be a separately labelled assumption."}


def calibrate(daily: pd.DataFrame) -> dict:
    """Pool training-only per-day log digital sales and weekday multipliers per merchant."""
    tr = daily[daily["split"] == TRAIN]
    logs = np.log(tr["digital_cents"].to_numpy(float))
    wd = tr.groupby("weekday").digital_cents.median()
    m = tr.groupby("merchant_id").digital_cents.median()
    return {"merchant_log_median_mean": float(np.log(m).mean()), "merchant_log_median_sd": float(np.log(m).std()),
            "within_merchant_log_sd": float(np.sqrt(np.mean(np.square(
                np.log(tr["digital_cents"].to_numpy(float)) - np.log(tr["merchant_id"].map(m).to_numpy(float)))))),
            "weekday_multiplier": {int(k): float(v / tr.digital_cents.median()) for k, v in wd.items()},
            "mean_receipt_cents": float(np.mean(tr["digital_cents"] / tr["digital_receipts"])), "train_days": int(len(tr))}


def simulate(cal: dict, scenario: str, merchants: int = 30, days: int = 120, start: str = "2026-01-01",
             seed: int = 20261116, version: str = "sim-v1") -> pd.DataFrame:
    """Seeded labelled scenario panel with explicit day states. Digital sales only; no weather effect applied."""
    sc = SCENARIOS[scenario]
    h = int(hashlib.sha256(f"{seed}:{scenario}:{version}".encode()).hexdigest()[:12], 16)
    rng = np.random.default_rng(h)
    dates = pd.date_range(start, periods=days, freq="D")
    base = np.exp(rng.normal(cal["merchant_log_median_mean"], cal["merchant_log_median_sd"], merchants)) * sc["volume_mult"]
    rows = []
    wm = cal["weekday_multiplier"]
    for i in range(merchants):
        for d in dates:
            u = rng.random()
            if u < sc["closure_rate"]:
                state, sales, rec = "closed", 0, 0
            elif u < sc["closure_rate"] + sc["outage_rate"]:
                state, sales, rec = "outage_missing", None, None
            elif u < sc["closure_rate"] + sc["outage_rate"] + sc["unrecorded_rate"]:
                state, sales, rec = "unrecorded", None, None
            elif rng.random() < sc["zero_sales_rate_of_open_days"]:
                state, sales, rec = "verified_zero", 0, 0
            else:
                mu = base[i] * wm.get(int(d.day_of_week), 1.0)
                sales = int(max(1, round(mu * np.exp(rng.normal(0, cal["within_merchant_log_sd"])))))
                rec = int(max(1, round(sales / max(cal["mean_receipt_cents"], 1))))
                state = "observed_sales"
            refund = int(round(sales * 0.5 * rng.random())) if state == "observed_sales" and rng.random() < sc["refund_rate"] else 0
            rows.append((f"{scenario}-M{i:03d}", d.date().isoformat(), state, sales, rec, refund))
    out = pd.DataFrame(rows, columns=["merchant_id", "trading_day", "day_state", "digital_cents", "digital_receipts",
                                      "refund_cents"])
    out["net_digital_cents"] = out["digital_cents"] - out["refund_cents"]
    out["scenario"], out["provenance"] = scenario, "simulated_assumption"
    return out


def margin_scenarios(sim: pd.DataFrame) -> dict:
    """Illustrative gross profit on DIGITAL sales only; margins are labelled assumptions, not observations."""
    s = float(sim.loc[sim.day_state == "observed_sales", "net_digital_cents"].sum())
    return {"basis": "assumption_not_verified", "applies_to": "digital_sales_only_not_total_income",
            "gross_profit_on_digital_sales_cents": {k: round(s * v) for k, v in MARGIN_ASSUMPTIONS.items()}}


def run(receipts_path: str | Path, out_dir: str | Path, cfg: BaselineConfig | None = None, sim_merchants: int = 30,
        sim_days: int = 120) -> dict:
    cfg = cfg or BaselineConfig()
    rp = Path(receipts_path)
    manifest_path = rp.with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    daily = daily_digital(load_receipts(rp))
    model = IncomeBaseline(cfg).fit(daily)
    report = {"schema_version": SCHEMA, "dataset_build_id": manifest.get("build_id"),
              "receipts_sha256": hashlib.sha256(rp.read_bytes()).hexdigest(), "config": cfg.__dict__,
              "fit_split": TRAIN, "train_merchant_days": model.train_rows,
              "cash_included": False, "zero_sales_imputed": False, "weather_response_applied": False,
              "real_world_accuracy_claim": False, "provenance": "calibrated_synthetic_only",
              "interval_offsets_log_ratio": model.offsets, "evaluation": {}}
    for name, sel in (("validation_forward", daily.split == "validation"), ("test_forward", daily.split == "test"),
                      ("merchant_holdout_future", (daily.split == "merchant_holdout") & (daily.trading_day >= "2025-11-01"))):
        part = daily[sel]
        ev = {"statistical_baseline": score(part, model.predict(part))}
        roll = model.rolling_predict(daily)
        ev["rolling_28d_median"] = score(part, roll)
        gw = part[["merchant_id", "trading_day"]].assign(
            pred_cents=part["weekday"].map(model.gw).round().astype(np.int64).to_numpy())
        ev["global_weekday_only"] = score(part, gw)
        report["evaluation"][name] = ev
    report["missing_days"] = missing_day_summary(daily)
    cal = calibrate(daily)
    report["simulator_calibration"] = cal
    scen = {}
    sims = []
    for k in SCENARIOS:
        sim = simulate(cal, k, sim_merchants, sim_days, seed=cfg.seed)
        sims.append(sim)
        st = sim.day_state.value_counts().to_dict()
        scen[k] = {**{x: SCENARIOS[k][x] for x in ("label", "basis")}, "day_states": {s: int(st.get(s, 0)) for s in STATES},
                   "margin_assumptions": margin_scenarios(sim)}
    report["scenarios"] = scen
    report["weather_response"] = WEATHER_RESPONSE_PLACEHOLDER
    # sparse-history fallback: tier usage for holdout merchants (never penalise merchants with no own history)
    hold = daily[daily.merchant_split == "holdout"]
    report["sparse_fallback_tier_counts_holdout"] = model.predict(hold)["tier"].value_counts().to_dict()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.concat(sims).to_csv(out / "scenario_panels.csv", index=False)
    (out / "baseline_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, default=str))
    return report
