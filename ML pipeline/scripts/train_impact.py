"""Train and validate the stall impact model on QR history (train 2023-24, test 2025), then refit on 2023-25.
python scripts/train_impact.py [--processed DIR] [--world central]"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.impact_model import baseline, pooled_curves, stall_sensitivity
from sklearn.ensemble import HistGradientBoostingRegressor


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed"))
    ap.add_argument("--world", default="central")
    a = ap.parse_args(); P = Path(a.processed); W = P / "synthetic" / a.world; out = P / "model"
    z = np.load(W / "qr_history_2023_2025.npz", allow_pickle=False)
    qr, trading, dates, sid = z["qr"].astype(float), z["trading"], pd.DatetimeIndex(z["dates"]), z["stall_id"]
    stalls = pd.read_csv(W / "stalls.csv").set_index("stall_id").loc[sid].reset_index()
    cd = pd.read_csv(P / "centre_day.csv.gz", parse_dates=["date"], usecols=["centre_id", "date", "rain", "psi"])
    cd = cd[cd.date.isin(dates)]
    cids = stalls.centre_id.unique(); ci = pd.Series(range(len(cids)), cids)[stalls.centre_id].values
    rain = cd.pivot(index="date", columns="centre_id", values="rain").reindex(index=dates, columns=cids).fillna(0).values[:, ci]
    psi = cd.pivot(index="date", columns="centre_id", values="psi").reindex(index=dates, columns=cids).fillna(50).values[:, ci]
    dow = dates.dayofweek.values
    clean = (rain < 5) & (psi <= 100)
    tr_mask, te_mask = dates.year.values <= 2024, dates.year.values == 2025

    def fit(mask):
        base = baseline(qr, trading, clean, dow, mask)
        valid = trading & mask[:, None] & (base >= 3)
        ratio = np.where(valid, qr / np.maximum(base, 1e-9), np.nan)
        curves, rb, pb = pooled_curves(ratio, valid, rain, psi)
        p_rain, p_haze = curves["rain"][rb], curves["haze"][pb]
        kr = stall_sensitivity(ratio, valid & (psi <= 100), p_rain)
        kh = stall_sensitivity(ratio, valid & (rain < 10), p_haze)
        return base, curves, p_rain, p_haze, kr, kh

    base, curves, p_rain, p_haze, kr, kh = fit(tr_mask)
    # test on 2025 bad days: predicted vs observed sales ratio
    valid = trading & te_mask[:, None] & (base >= 3)
    obs = np.where(valid, qr / np.maximum(base, 1e-9), np.nan)
    bad = valid & ((p_rain >= 0.03) | (p_haze >= 0.03))
    feats = pd.DataFrame({"qr_level": np.nanmedian(np.where(tr_mask[:, None] & trading, qr, np.nan), 0),
                          "ticket": stalls.avg_ticket_sgd, "lat_c": ci})
    gbm = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, random_state=0)
    okr = np.isfinite(kr[0])
    gbm.fit(feats[okr], np.clip(kr[0][okr], -1, 3))
    k_gbm = gbm.predict(feats)
    cands = {"pooled (k=1)": (np.ones(len(sid)), np.ones(len(sid))),
             "no pooling (raw k)": (np.nan_to_num(kr[0], nan=1.0), np.nan_to_num(kh[0], nan=1.0)),
             "partial pooling (EB)": (kr[1], kh[1]),
             "GBM on stall features": (k_gbm, np.ones(len(sid)))}
    rows = []
    true_k = stalls.weather_sensitivity.values * np.where(stalls.on_delivery_platform, 0.85, 1.0)
    for name, (k_r, k_h) in cands.items():
        pred = 1 - (1 - (1 - k_r[None, :] * p_rain) * (1 - k_h[None, :] * p_haze))
        err = np.abs(np.where(bad, pred - obs, np.nan))
        rows.append({"model": name, "MAE_on_2025_bad_days": float(np.nanmean(err)),
                     "corr_with_true_sensitivity (synthetic truth)": float(np.corrcoef(np.clip(k_r, -5, 5), true_k)[0, 1])})
    res = pd.DataFrame(rows)
    print("Pooled dose-response (share of sales lost), trained 2023-24:")
    print("  rain bands", dict(zip(["0-10", "10-30", "30-50", "50-70", "70-100", "100+"], curves["rain"].round(3))))
    print("  PSI bands ", dict(zip(["<=100", "101-150", "151-200", ">200"], curves["haze"].round(3))))
    print(f"\nStall sensitivity spread (EB): rain k p10-p90 {np.percentile(kr[1],10):.2f}-{np.percentile(kr[1],90):.2f}; "
          f"haze k {np.percentile(kh[1],10):.2f}-{np.percentile(kh[1],90):.2f}; shrink weight median rain {np.median(kr[2]):.2f}, haze {np.median(kh[2]):.2f}")
    print("\nValidation (train 2023-24, test 2025):"); print(res.round(4).to_string(index=False))
    # refit on all of 2023-2025 for 2026 pricing
    all_mask = dates.year.values <= 2025
    base, curves, p_rain, p_haze, kr, kh = fit(all_mask)
    pd.DataFrame({"stall_id": sid, "k_rain": kr[1].round(3), "k_haze": kh[1].round(3),
                  "rain_bad_days": kr[3], "haze_bad_days": kh[3], "w_rain": kr[2].round(3), "w_haze": kh[2].round(3)}
                 ).to_csv(out / f"stall_sensitivity_{a.world}.csv", index=False)
    json.dump({"curves": {k: v.tolist() for k, v in curves.items()}, "rain_bins": [-0.1, 10, 30, 50, 70, 100, "inf"],
               "psi_bins": [0, 100, 150, 200, "inf"], "validation": rows}, open(out / f"impact_model_{a.world}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
