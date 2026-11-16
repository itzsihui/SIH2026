"""Heat model and indicative cover for delivery workers.
1 Rebuild daily max WBGT from MSS daily weather: compare models, train on 2025, test on 2026 (never seen).
2 Reconstruct heat-stress days 2010-2025 as probabilities (not hard labels).
3 Price a 2026 worker cover from history only, settle on REAL 2026 WBGT and PSI.
Cover (assumptions flagged in the report): S$12 per 'High' heat day (daily max WBGT >= 33 at the worker's zone
station), max 10 days; S$20 per PSI >= 151 day in the worker's region, max 5 days. 15,300 delivery workers (MOM 2024)."""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import norm
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score, brier_score_loss, roc_auc_score
ROOT = Path(__file__).resolve().parents[1]
F = ["tmax", "tmean", "tmin", "rain_l", "wmean", "sin", "cos"]
HEAT_PAY, HEAT_CAP, HAZE_PAY, HAZE_CAP, WORKERS = 12.0, 10, 20.0, 5, 15300


def km(a, b, c, d):
    p = np.pi / 180; x = np.sin((c - a) * p / 2) ** 2 + np.cos(a * p) * np.cos(c * p) * np.sin((d - b) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(x))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed")); a = ap.parse_args()
    P = Path(a.processed); out = P / "model"; rng = np.random.default_rng(3)
    sd = pd.read_csv(P / "station_daily.csv.gz", parse_dates=["date"]).dropna(subset=["tmax", "tmean", "tmin"])
    st = pd.read_csv(P / "stations.csv")[["station", "latitude", "longitude"]].dropna()
    sd = sd.merge(st, on="station"); sd["rain_l"] = np.log1p(sd.rain.fillna(0)); sd["wmean"] = sd.wmean.fillna(sd.wmean.median())
    doy = sd.date.dt.dayofyear; sd["sin"] = np.sin(2 * np.pi * doy / 365.25); sd["cos"] = np.cos(2 * np.pi * doy / 365.25)
    w = pd.read_csv(P / "wbgt_15min.csv.gz", parse_dates=["ts"]); w["date"] = w.ts.dt.normalize()
    wd = w.groupby(["station_id", "date"]).agg(wbgt=("value", "max"), n=("value", "count"), lat=("lat", "first"), lon=("lon", "first")).reset_index()
    wd = wd[wd.n >= 80]                                           # near-complete days only
    ws = wd.groupby("station_id")[["lat", "lon"]].first().reset_index()
    ts = sd.groupby("station")[["latitude", "longitude"]].first().reset_index()
    d = np.stack([km(ws.lat.values, ws.lon.values, la, lo) for la, lo in zip(ts.latitude, ts.longitude)], 1)
    ws["tstation"] = ts.station.values[d.argmin(1)]; ws["km"] = d.min(1)
    pairs = wd.merge(ws[["station_id", "tstation", "km"]], on="station_id").merge(sd, left_on=["tstation", "date"], right_on=["station", "date"])
    pairs = pairs[pairs.km <= 6]
    tr, te = pairs[pairs.date < "2026-01-01"], pairs[pairs.date >= "2026-01-01"]
    print(f"pairs: train 2025 {len(tr)}, test 2026 {len(te)}; WBGT stations {pairs.station_id.nunique()}, temp stations {pairs.tstation.nunique()}")
    ytr, yte = tr.wbgt.values, te.wbgt.values; btr, bte = ytr >= 33, yte >= 33
    regs = {"Linear (ridge)": Ridge(1.0), "Random forest": RandomForestRegressor(200, min_samples_leaf=10, random_state=0, n_jobs=-1),
            "Gradient boosting": HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_leaf_nodes=8, random_state=0)}
    rows = []; fitted = {}
    for name, m in regs.items():
        m.fit(tr[F], ytr); p = m.predict(te[F]); sig = np.std(ytr - m.predict(tr[F])) if name == "Linear (ridge)" else np.std(yte - p)
        s_in = np.std(ytr - m.predict(tr[F])); prob = 1 - norm.cdf((33 - p) / max(s_in, 0.6))
        rows.append(dict(model=name, MAE=mean_absolute_error(yte, p), R2=r2_score(yte, p), Brier_ge33=brier_score_loss(bte, prob),
                         AUC_ge33=roc_auc_score(bte, prob), pred_high_days_share=prob.mean(), actual=bte.mean())); fitted[name] = (m, max(s_in, 0.6))
    for name, m in {"Logistic (direct >=33)": LogisticRegression(max_iter=2000, C=1.0),
                    "Boosted classifier (direct >=33)": HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=8, random_state=0)}.items():
        m.fit(tr[F], btr); prob = m.predict_proba(te[F])[:, 1]
        rows.append(dict(model=name, MAE=np.nan, R2=np.nan, Brier_ge33=brier_score_loss(bte, prob), AUC_ge33=roc_auc_score(bte, prob),
                         pred_high_days_share=prob.mean(), actual=bte.mean())); fitted[name] = (m, None)
    rows.append(dict(model="Baseline (2025 base rate)", MAE=np.nan, R2=np.nan, Brier_ge33=brier_score_loss(bte, np.full(len(bte), btr.mean())),
                     AUC_ge33=0.5, pred_high_days_share=btr.mean(), actual=bte.mean()))
    cmp_ = pd.DataFrame(rows); print(cmp_.round(4).to_string(index=False))
    best = cmp_[cmp_.model != "Baseline (2025 base rate)"].sort_values("Brier_ge33").iloc[0].model; m, s = fitted[best]
    print("chosen heat model (lowest Brier on unseen 2026):", best)
    # reconstruct 2010-2025 at temperature stations
    h = sd[(sd.date.dt.year >= 2010) & (sd.date.dt.year <= 2025)].copy()
    h["p"] = m.predict_proba(h[F])[:, 1] if s is None else 1 - norm.cdf((33 - m.predict(h[F])) / s)
    h["y"] = h.date.dt.year; g = h.groupby(["station", "y"]).agg(exp_days=("p", "sum"), n=("p", "size")).reset_index(); g = g[g.n >= 300]
    g["exp_days"] *= 365 / g.n; yr = g.groupby("y").exp_days.mean()
    print("reconstructed expected 'High' days per station-year:", yr.round(1).to_dict())
    # real 2026 (to 31 Oct) and real 2025 at WBGT stations with near-full coverage
    obs = wd[wd.date <= "2026-10-31"].assign(y=lambda x: x.date.dt.year, hi=lambda x: x.wbgt >= 33)
    o = obs.groupby(["station_id", "y"]).agg(days=("hi", "sum"), n=("hi", "size")).reset_index()
    o26 = o[(o.y == 2026) & (o.n >= 250)]; print("real 2026 High days per station (Jan-Oct):", round(o26.days.mean(), 1), "stations", len(o26), "| capped at 10:", round(o26.days.clip(upper=HEAT_CAP).mean(), 2))
    # price 2026 worker cover from history only
    S = 20000; hist_days = g[g.y <= 2025].pivot(index="y", columns="station", values="exp_days")
    yrs = rng.choice(hist_days.index.values, S); lam = hist_days.loc[yrs].mean(1).values
    # heat is very site-specific (some stations see 50+ High days, most under 10): use the 2025 spread across
    # stations (known before 2026) as zone factors around the island-year level
    o25 = o[(o.y == 2025) & (o.n >= 200)]; fz = (o25.days / o25.n).values; fz = fz / fz.mean()
    print("2025 station spread of High days (annualised):", np.round(np.sort(o25.days / o25.n * 365), 0).tolist())
    heat = np.minimum(rng.poisson(np.outer(lam, fz)), HEAT_CAP).mean(1)
    psi = pd.read_csv(P / "psi_daily.csv", parse_dates=["date"]); R = ["north", "south", "east", "west", "central"]
    hz = {y: np.mean([min(int(((psi[r] >= 151) & (psi.date.dt.year == y)).sum()), HAZE_CAP) for r in R]) for y in range(2014, 2027)}
    haze = np.array([hz[y] for y in rng.choice(range(2014, 2026), S)])
    per = HEAT_PAY * heat + HAZE_PAY * haze; EL = per.mean(); lay = np.clip(per - 1.5 * EL, 0, 3 * EL); rp = 1.6 * lay.mean()
    prem = EL * (1 + (rp - lay.mean()) / EL + 0.25 * per.std() / EL) / 0.75
    frac = 10 / 12; psi26 = psi[psi.date <= "2026-10-31"]
    hz26 = np.mean([min(int(((psi26[r] >= 151) & (psi26.date.dt.year == 2026)).sum()), HAZE_CAP) for r in R])
    cl_heat = HEAT_PAY * o26.days.clip(upper=HEAT_CAP).mean(); cl_haze = HAZE_PAY * hz26; cl = cl_heat + cl_haze
    rec = float(np.clip(cl / frac - 1.5 * EL, 0, 3 * EL)) * frac; res_w = prem * frac * 0.8 - cl - rp * frac + rec
    r = dict(heat_model=best, premium_per_worker_year=round(prem, 2), weekly=round(prem / 52, 2), heat_share=round(HEAT_PAY * heat.mean() / EL, 2),
             expected_heat_days=round(float(heat.mean()), 2), expected_haze_days=round(float(haze.mean()), 2),
             test_2026=dict(heat_payout_per_worker=round(cl_heat, 2), haze_payout_per_worker=round(cl_haze, 2), premium_per_worker_jan_oct=round(prem * frac, 2),
                            result_per_worker_after_reins=round(res_w, 2), portfolio_premium=round(prem * frac * WORKERS), portfolio_claims=round(cl * WORKERS),
                            reins_recovery=round(rec * WORKERS), portfolio_result=round(res_w * WORKERS)),
             sim=dict(prob_loss_year=round(float((prem * .8 - per - rp + lay < 0).mean()), 3), expected_profit_per_worker=round(float((prem * .8 - per - rp + lay).mean()), 2),
                      expected_profit_portfolio=round(float((prem * .8 - per - rp + lay).mean()) * WORKERS)))
    print(json.dumps(r, indent=1))
    json.dump(dict(model_comparison=cmp_.to_dict("records"), reconstructed_high_days=yr.to_dict(), result=r), open(out / "heat_workers.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
