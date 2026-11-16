"""Train and validate the rain trigger model. python scripts/train_rain.py [--processed DIR]"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.config import RULES, TRAIN_YEARS
from pricing.rain_model import centre_months, loyo, Model


def load_oni(path):
    o = pd.read_fwf(path); o.columns = ["seas", "yr", "total", "anom"]
    ond = o[o.seas == "OND"].set_index("yr").anom
    return pd.DataFrame({"year": ond.index + 1, "oni_prev_ond": ond.values})


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--processed", default=str(ROOT / "data/processed"))
    ap.add_argument("--oni", default=str(ROOT / "data/raw/full/indices/oni.txt"))
    a = ap.parse_args(); P = Path(a.processed); out = P / "model"; out.mkdir(exist_ok=True)
    cd = pd.read_csv(P / "centre_day.csv.gz", parse_dates=["date"], usecols=["centre_id", "date", "rain"])
    cd = cd[cd.date.dt.year.isin(TRAIN_YEARS)]
    centres = pd.read_csv(P / "centres.csv")
    cm = centre_months(cd, centres, load_oni(a.oni), RULES["rain_daily_mm"])
    kinds = ["island", "season", "centre", "glm", "glm+enso", "gbm"]
    # choose ridge strength for the GLM by the same leave-one-year-out test
    tune = {al: loyo(cm, ["glm"], TRAIN_YEARS, al).deviance.mean() for al in (1e-4, 1e-3, 1e-2, 3e-2)}
    best_alpha = min(tune, key=tune.get)
    res = loyo(cm, kinds, TRAIN_YEARS, best_alpha)
    summ = res.groupby("model").agg(mean_deviance=("deviance", "mean"),
                                    worse_years=("deviance", "count")).reindex(kinds)
    base = res[res.model == "season"].set_index("year").deviance
    for k in kinds:
        summ.loc[k, "beats_season_in_years"] = int((res[res.model == k].set_index("year").deviance < base).sum())
    summ = summ.drop(columns="worse_years")
    cal = res.pivot(index="year", columns="model", values="pred_days_per_centre").round(2)
    cal["actual"] = res.groupby("year").actual_days_per_centre.first().round(2)
    print("ridge alpha tuning (mean LOYO deviance):", {k: round(v, 5) for k, v in tune.items()}, "-> alpha", best_alpha)
    print("\nLeave-one-year-out, centre-month Poisson deviance (lower is better):")
    print(summ.round(5).to_string())
    print("\nPredicted vs actual 70 mm days per centre, each year held out:")
    print(cal[["island", "season", "glm", "glm+enso", "gbm", "actual"]].to_string())
    res.to_csv(out / "rain_loyo.csv", index=False)
    json.dump({"alpha": best_alpha, "tuning": tune, "summary": summ.reset_index().to_dict("records")},
              open(out / "rain_validation.json", "w"), indent=1)


if __name__ == "__main__":
    main()
