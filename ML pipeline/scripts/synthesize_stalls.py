"""Synthetic hawker-stall population and QR-sales panel, driven by REAL weather.

Why synthetic: no public data exists on stall sales, QR transactions or weather losses (see DATA_CARD).
What it is for: testing the cover-sizing, premium-collection and basis-risk logic end to end, and
showing how results change when the unknown behaviour assumptions change.
What it must NOT be used for: claiming how much hawkers really lose. Only a pilot with consented QR
data can measure that. Every output row carries the world id and the parameter file used.

Inputs (from scripts/build_dataset.py): data/processed/centres.csv, centre_day.csv.gz
Outputs (data/processed/synthetic/<world>/):
  stalls.csv                 one row per cooked-food stall (attributes below)
  stall_cover_inputs.csv     what a stall would show at onboarding on 1 Jan 2026 (trailing QR history)
  stall_day_2026.csv.gz      daily customers / QR sales per stall, 1 Jan - 31 Oct 2026 (the test year)
  params.json                the exact parameters and seed used

    python scripts/synthesize_stalls.py                    # central world
    python scripts/synthesize_stalls.py --world low_loss   # see WORLDS below
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Every parameter: value + basis. "anchor" = taken from a cited public figure; "assumption" = team choice.
CENTRAL = {
    "seed": 2026,
    "owner_age_mean": (60, "anchor: median cooked-food stallholder age 60 (MSE written reply, 5 Oct 2021)"),
    "owner_age_sd": (11, "assumption: spread so ~70% are over 50 (Hawkers' Productivity Grant: >70% of applicants over 50)"),
    "customers_median": (120, "assumption: gives ~S$360/day gross profit at S$6 x 50%, matching the team notebook's S$300/day stall case"),
    "customers_sigma": (0.45, "assumption: 90% of stalls 57-250 customers/day; busy tail reaches ~500 (Tekka stall, The Star 19 Oct 2026)"),
    "ticket_median": (6.0, "assumption: cooked-food meal price; e-payment average ticket was S$8.33 (EnterpriseSG MR049/23: S$45m / 5.4m transactions, Aug 2023), which includes coffee-shop baskets"),
    "ticket_sigma": (0.20, "assumption"),
    "gross_margin": ((0.40, 0.60), "assumption: uniform range for cooked food; no official margin data exists"),
    "qr_share_mean": (0.25, "anchor+assumption: Aug 2023 e-payments were 5.4m tx/month across >11,000 F&B stallholders = ~19 tx per stall per trading day (EnterpriseSG MR049/23), i.e. ~15% of ~120 customers; 0.25 allows for growth to 2026. Key uncertainty: tested in worlds low_qr / high_qr"),
    "qr_share_age_slope": (-0.015, "assumption: older owners take less QR (per year of age above 60)"),
    "trading_days_per_week": (6, "assumption: one rest day a week"),
    "weekend_uplift": (0.10, "assumption"),
    "centre_sd": (0.15, "assumption: centre-level demand differences (log scale)"),
    "daily_noise_cv": (0.12, "assumption: day-to-day variation in customers"),
    # weather response (share of customers lost); stall sensitivity multiplies these
    "haze_drop": ({100: 0.0, 150: 0.20, 200: 0.35, 300: 0.50}, "anchor: Tekka stalls reported -30% to -60% at PSI ~200-230 (The Star, 19 Oct 2026); team loss model 20/30/45%"),
    "rain_drop_max": (0.45, "anchor: team loss model 25% (>=50 mm) to 40% (>=80 mm); 2026 flood reports 20-60%"),
    "rain_drop_scale_mm": (70.0, "assumption: drop = max x (1 - exp(-rain/scale)); 50 mm -> 23%, 80 mm -> 31%"),
    "rain_timing_beta": ((2.0, 1.5), "assumption: share of the day's rain falling in trading hours; replaced by 5-minute data where available"),
    "heat_drop_high": (0.05, "assumption: small; customers are mostly under roof. NUS HeatSafe's 24% loss is for outdoor WORKERS, not diners"),
    "stall_sensitivity_sigma": (0.30, "assumption: some stalls lose more (open-air seating, walkway flooding, elderly customers)"),
    "delivery_share": (0.30, "assumption: share of stalls on delivery platforms"),
    "delivery_offset": (0.15, "assumption: delivery orders rise in bad weather and offset 15% of the walk-in drop (team proposal: 'delivery orders can rise in bad weather')"),
}
WORLDS = {
    "central": {},
    "low_loss": {"rain_drop_max": 0.25, "haze_drop": {100: 0.0, 150: 0.10, 200: 0.20, 300: 0.30}},
    "high_loss": {"rain_drop_max": 0.60, "haze_drop": {100: 0.0, 150: 0.30, 200: 0.50, 300: 0.65}},
    "low_qr": {"qr_share_mean": 0.15},
    "high_qr": {"qr_share_mean": 0.50},
}


def value(p, k):
    v = p[k]
    return v[0] if isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], str) else v


def haze_drop(psi, table):
    xs, ys = zip(*sorted(table.items()))
    return np.interp(np.nan_to_num(psi, nan=0.0), xs, ys, left=0.0, right=ys[-1])


def make_stalls(centres, p, rng):
    rows = []
    for _, c in centres.iterrows():
        n = int(c.stalls)
        rows.append(pd.DataFrame({"centre_id": c.centre_id, "stall_no": np.arange(1, n + 1)}))
    s = pd.concat(rows, ignore_index=True)
    n = len(s)
    s.insert(0, "stall_id", [f"{a}-{b:03d}" for a, b in zip(s.centre_id, s.stall_no)])
    s["owner_age"] = np.clip(rng.normal(value(p, "owner_age_mean"), value(p, "owner_age_sd"), n), 25, 85).round()
    centre_eff = {cid: rng.normal(0, value(p, "centre_sd")) for cid in s.centre_id.unique()}
    s["customers_per_day"] = np.round(value(p, "customers_median") * np.exp(
        rng.normal(0, value(p, "customers_sigma"), n) + s.centre_id.map(centre_eff).to_numpy()))
    s["avg_ticket_sgd"] = np.round(value(p, "ticket_median") * np.exp(rng.normal(0, value(p, "ticket_sigma"), n)), 2)
    lo, hi = value(p, "gross_margin")
    s["gross_margin"] = rng.uniform(lo, hi, n).round(3)
    q = value(p, "qr_share_mean") + value(p, "qr_share_age_slope") * (s.owner_age - 60) + rng.normal(0, 0.12, n)
    s["qr_share"] = np.clip(q, 0.05, 0.95).round(3)
    s["weather_sensitivity"] = np.round(np.exp(rng.normal(-0.5 * value(p, "stall_sensitivity_sigma") ** 2,
                                                          value(p, "stall_sensitivity_sigma"), n)), 3)
    s["on_delivery_platform"] = rng.random(n) < value(p, "delivery_share")
    s["rest_weekday"] = rng.integers(0, 7, n)   # 0 = Monday
    return s


def simulate(stalls, cd, p, rng, start, end):
    """Daily customers and QR sales for every stall, start..end, using real centre weather."""
    w = cd[(cd.date >= start) & (cd.date <= end)].copy()
    dates = pd.DatetimeIndex(sorted(w.date.unique()))
    cids = stalls.centre_id.unique()
    piv = {k: w.pivot(index="date", columns="centre_id", values=k).reindex(index=dates, columns=cids)
           for k in ("rain", "psi")}
    closed = (w.assign(c=w["closure"].notna()) if "closure" in w else w.assign(c=False)
              ).pivot(index="date", columns="centre_id", values="c").reindex(index=dates, columns=cids).fillna(False)
    a, b = value(p, "rain_timing_beta")
    timing = rng.beta(a, b, size=piv["rain"].shape)                       # shared by all stalls at a centre that day
    rain_drop = value(p, "rain_drop_max") * (1 - np.exp(-np.nan_to_num(piv["rain"].to_numpy()) /
                                                        value(p, "rain_drop_scale_mm"))) * timing
    hz = haze_drop(piv["psi"].to_numpy(), value(p, "haze_drop"))
    centre_drop = 1 - (1 - rain_drop) * (1 - hz)                          # combined share lost, centre level
    col = {c: i for i, c in enumerate(cids)}
    ci = stalls.centre_id.map(col).to_numpy()
    sens = stalls.weather_sensitivity.to_numpy() * np.where(stalls.on_delivery_platform, 1 - value(p, "delivery_offset"), 1)
    drop = np.clip(centre_drop[:, ci] * sens[None, :], 0, 0.95)          # days x stalls
    dow = dates.dayofweek.to_numpy()[:, None]
    trading = (dow != stalls.rest_weekday.to_numpy()[None, :]) & ~closed.to_numpy()[:, ci]
    base = stalls.customers_per_day.to_numpy()[None, :] * (1 + value(p, "weekend_uplift") * (dow >= 5))
    mean = base * (1 - drop) * trading
    noise = np.exp(rng.normal(0, value(p, "daily_noise_cv"), mean.shape))
    customers = rng.poisson(mean * noise)
    qr = rng.binomial(customers, stalls.qr_share.to_numpy()[None, :])
    return dates, customers, qr, drop, trading, centre_drop[:, ci]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="central", choices=list(WORLDS))
    ap.add_argument("--processed", default=str(ROOT / "data" / "processed"))
    a = ap.parse_args(argv)
    p = {**CENTRAL, **{k: (v, CENTRAL[k][1]) for k, v in WORLDS[a.world].items()}}
    rng = np.random.default_rng(value(p, "seed"))
    proc = Path(a.processed)
    out = proc / "synthetic" / a.world
    out.mkdir(parents=True, exist_ok=True)
    centres = pd.read_csv(proc / "centres.csv")
    cd = pd.read_csv(proc / "centre_day.csv.gz", parse_dates=["date"], low_memory=False)

    stalls = make_stalls(centres, p, rng)
    stalls.to_csv(out / "stalls.csv", index=False)

    # onboarding view on 1 Jan 2026: last 12 weeks of QR sales and 2023-2025 bad-day history
    dates, cust, qr, drop, trading, cdrop = simulate(stalls, cd, p, rng, "2023-01-01", "2025-12-31")
    last12 = dates >= pd.Timestamp("2025-10-08")
    td = trading & last12[:, None]
    qr_avg = np.where(td.sum(0) > 0, (qr * td).sum(0) / np.maximum(td.sum(0), 1), np.nan)
    bad = (cdrop >= 0.15) & trading                       # days the weather (not the stall) cut demand by >=15%
    norm = (cdrop < 0.02) & trading
    bad_qr = np.where(bad.sum(0) > 0, (qr * bad).sum(0) / np.maximum(bad.sum(0), 1), np.nan)
    norm_qr = (qr * norm).sum(0) / np.maximum(norm.sum(0), 1)
    inputs = pd.DataFrame({"stall_id": stalls.stall_id, "qr_tx_per_trading_day_12wk": np.round(qr_avg, 1),
                           "bad_days_seen_2023_2025": bad.sum(0),
                           "measured_drop_on_bad_days": np.round(1 - bad_qr / np.maximum(norm_qr, 1e-9), 3),
                           "true_expected_drop_on_bad_days": np.round((drop * bad).sum(0) / np.maximum(bad.sum(0), 1), 3)})
    inputs.to_csv(out / "stall_cover_inputs.csv", index=False)
    # onboarding QR history (what an insurer would see with consent), for the stall impact model
    np.savez_compressed(out / "qr_history_2023_2025.npz", qr=qr.astype(np.int16), trading=trading,
                        dates=dates.values.astype("datetime64[D]"), stall_id=stalls.stall_id.values.astype(str),
                        true_drop=drop.astype(np.float32))

    dates, cust, qr, drop, trading, _ = simulate(stalls, cd, p, rng, "2026-01-01", "2026-10-31")
    n_days, n_st = cust.shape
    panel = pd.DataFrame({"stall_id": np.tile(stalls.stall_id.to_numpy(), n_days),
                          "date": np.repeat(dates, n_st), "trading": trading.ravel(),
                          "customers": cust.ravel(), "qr_tx": qr.ravel(), "weather_drop": drop.ravel().round(3)})
    panel.to_csv(out / "stall_day_2026.csv.gz", index=False)
    json.dump({"world": a.world, "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items()}},
              open(out / "params.json", "w"), indent=1, default=str)

    gp = stalls.customers_per_day * stalls.avg_ticket_sgd * stalls.gross_margin
    print(f"[{a.world}] stalls {len(stalls)}; gross profit/day median S${gp.median():.0f} "
          f"(p10 {gp.quantile(.1):.0f}, p90 {gp.quantile(.9):.0f}); QR tx/day median {np.nanmedian(qr_avg):.0f}")
    print(f"  measured vs true bad-day drop: corr {inputs[['measured_drop_on_bad_days','true_expected_drop_on_bad_days']].corr().iloc[0,1]:.2f}; "
          f"stalls with <3 bad days seen: {(inputs.bad_days_seen_2023_2025 < 3).mean():.0%}")
    print(f"  2026 panel rows {len(panel):,}")


if __name__ == "__main__":
    main()
