"""Train and validate the haze model. python scripts/train_haze.py [--processed DIR] [--oni FILE]"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.config import RULES, HAZE_TRAIN_YEARS, TEST_END
from pricing.haze_model import haze_units, region_year_table, credibility_mean, loyo
from sklearn.linear_model import PoissonRegressor


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed"))
    ap.add_argument("--oni", default=str(ROOT / "data/raw/full/indices/oni.txt"))
    a = ap.parse_args(); P = Path(a.processed); out = P / "model"; out.mkdir(exist_ok=True)
    psi = pd.read_csv(P / "psi_daily.csv", parse_dates=["date"])
    days = haze_units(psi, RULES, end=TEST_END)
    tab = region_year_table(days, RULES["haze_cap_days"], HAZE_TRAIN_YEARS)
    print("Paid haze units per region-year (cap 5 days; tier-2 day = 2 units):")
    print(tab.pivot(index="year", columns="region", values="units").to_string())
    cred, z = credibility_mean(tab)
    print(f"\nCredibility weight on a region's own mean: z = {z:.2f}")
    print("Expected units per year (annual price input):", cred.round(3).to_dict())
    v = loyo(tab)
    print("\nLeave-one-year-out mean absolute error (units per region):")
    print(v.groupby("model").abs_err.mean().round(3).to_string())
    # mid-year model: annual island-mean units vs May-Jul ONI
    o = pd.read_fwf(a.oni); o.columns = ["seas", "yr", "total", "anom"]
    mjj = o[o.seas == "MJJ"].set_index("yr").anom
    yr = tab.groupby("year").units.mean().reset_index()
    yr["oni_mjj"] = yr.year.map(mjj)
    preds = []
    for y in yr.year:
        tr = yr[yr.year != y]
        m = PoissonRegressor(alpha=1e-3, max_iter=2000).fit(tr[["oni_mjj"]], tr.units)
        preds.append(float(m.predict(yr[yr.year == y][["oni_mjj"]])[0]))
    yr["midyear_pred_loyo"] = np.round(preds, 2)
    full = PoissonRegressor(alpha=1e-3, max_iter=2000).fit(yr[["oni_mjj"]], yr.units)
    print("\nMid-year signal (May-Jul ONI), each year held out:")
    print(yr.round(2).to_string(index=False))
    print(f"2026 May-Jul ONI = {mjj.get(2026)}: mid-year model expects {full.predict([[mjj.get(2026)]])[0]:.2f} units/region "
          f"(annual price assumed {cred.mean():.2f})")
    tab.to_csv(out / "haze_region_year.csv", index=False)
    json.dump({"credibility_z": z, "expected_units": cred.to_dict(), "loyo_mae": v.groupby("model").abs_err.mean().to_dict(),
               "midyear_coef": float(full.coef_[0]), "midyear_intercept": float(full.intercept_),
               "oni_mjj_2026": mjj.get(2026)}, open(out / "haze_model.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
