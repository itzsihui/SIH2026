"""Back-test of the DayCover haze rule on real NEA 24-hour PSI data (2014-2026).

Rule (from Sumit's proposal, all thresholds are placeholders to be tuned):
  - PSI >= 201 on a day            -> pays the FULL-day amount
  - PSI 101-200 on 2 days in a row -> pays the HALF-day amount from the 2nd day onward
  - at most CAP payable haze days per calendar year
Usage:  python src/haze_backtest.py            (reads data/raw/psi_daily_max_combined_2014_2026.csv)
Outputs: results/haze_backtest.csv, results/haze_days_by_year.png
"""
import pandas as pd
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
HALF, FULL, CAP = 30, 60, 5

def payout_year(values, half=HALF, full=FULL, cap=CAP):
    days = cost = 0
    prev = 0
    for v in values:
        amt = full if v >= 201 else (half if (v >= 101 and prev >= 101) else 0)
        if amt and days < cap:
            days += 1
            cost += amt
        prev = v
    return cost, days

def main():
    d = pd.read_csv(ROOT / "data/raw/psi_daily_max_combined_2014_2026.csv", index_col=0, parse_dates=True)
    regions = ["north", "south", "east", "west", "central"]
    rows = []
    for y, g in d.groupby(d.index.year):
        any_max = g[regions].max(axis=1)
        row = {"year": y, "days_observed": len(g),
               "days_any_ge101": int((any_max >= 101).sum()), "days_any_ge151": int((any_max >= 151).sum()),
               "days_any_ge201": int((any_max >= 201).sum()), "peak_psi": int(any_max.max())}
        for r in regions:
            c, n = payout_year(g[r].values)
            row[f"{r}_cost_sgd"], row[f"{r}_paid_days"] = c, n
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "results/haze_backtest.csv", index=False)
    full_years = out[out.year >= 2015]
    print(out.to_string(index=False))
    for r in regions:
        col = f"{r}_cost_sgd"
        print(f"{r:8s} mean S${full_years[col].mean():5.1f}/yr  median S${full_years[col].median():4.0f}  "
              f"years at cap: {(full_years[f'{r}_paid_days'] >= CAP).sum()}/{len(full_years)}")
    fig, ax = plt.subplots(figsize=(9, 4.2))
    colors = ["#c0392b" if v >= 30 else "#e67e22" if v >= 10 else "#7f8c8d" for v in out.days_any_ge101]
    ax.bar(out.year.astype(str), out.days_any_ge101, color=colors)
    ax.set_ylabel("Days with 24-hr PSI >= 101 (any region)")
    ax.set_title("Singapore haze days per year (NEA data, 2026 to 7 Nov)")
    for i, v in enumerate(out.days_any_ge101):
        ax.text(i, v + 0.8, str(v), ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "results/haze_days_by_year.png", dpi=160)

if __name__ == "__main__":
    main()
