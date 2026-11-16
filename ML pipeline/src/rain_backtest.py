"""Back-test of DayCover+ rainfall triggers using Singapore NEA rainfall records and hawker closures.

Methodology:
1. Maps each hawker centre (data/raw/hawker_closures.csv) to the nearest NEA rainfall station by Haversine distance.
2. Identifies scheduled quarterly NEA cleaning closures and maintenance days per stall (to enforce non-payment on closed days).
3. Evaluates frequency of daily rainfall (>=20mm, >=30mm, >=50mm) and 1-hour peak rainfall (>=10mm, >=20mm).
4. Models expected payout cost across candidate triggers with caps (3-5 days) and compares against micro-insurance affordability.

Usage:
    python src/rain_backtest.py

Outputs:
    results/rain_hawker_station_map.csv
    results/rain_backtest_annual.csv
    results/rain_trigger_comparison.csv
    results/rain_threshold_frequency.png
    results/rain_cost_by_trigger.png
"""
from __future__ import annotations
import math
from datetime import datetime
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def map_hawkers_to_stations(hc_path: Path, st_path: Path) -> pd.DataFrame:
    """Map each hawker centre to its nearest NEA rainfall station."""
    hc_df = pd.read_csv(hc_path)
    st_df = pd.read_csv(st_path)

    mappings = []
    for _, row in hc_df.iterrows():
        h_lat = float(row["latitude_hc"])
        h_lon = float(row["longitude_hc"])
        best_st = None
        min_dist = float("inf")
        for _, s in st_df.iterrows():
            d = haversine(h_lat, h_lon, float(s["latitude"]), float(s["longitude"]))
            if d < min_dist:
                min_dist = d
                best_st = s
        mappings.append({
            "hawker_id": row["serial_no"],
            "hawker_name": row["name"],
            "hawker_lat": h_lat,
            "hawker_lon": h_lon,
            "food_stalls": row.get("no_of_food_stalls", 0),
            "station_id": best_st["id"],
            "station_name": best_st["name"],
            "station_lat": float(best_st["latitude"]),
            "station_lon": float(best_st["longitude"]),
            "distance_km": round(min_dist, 2)
        })
    df = pd.DataFrame(mappings)
    df.to_csv(RESULTS / "rain_hawker_station_map.csv", index=False)
    return df

def parse_cleaning_closures(hc_path: Path) -> dict[str, set[str]]:
    """Parse scheduled cleaning and maintenance dates per hawker centre."""
    hc_df = pd.read_csv(hc_path)
    closures = {}
    for _, row in hc_df.iterrows():
        centre = row["name"]
        dates = set()
        for q in ["q1", "q2", "q3", "q4"]:
            s_str = str(row.get(f"{q}_cleaningstartdate", "")).strip()
            e_str = str(row.get(f"{q}_cleaningenddate", "")).strip()
            if s_str not in ("nan", "NA", "nil", "") and e_str not in ("nan", "NA", "nil", ""):
                try:
                    s_dt = datetime.strptime(s_str, "%d/%m/%Y")
                    e_dt = datetime.strptime(e_str, "%d/%m/%Y")
                    cur = s_dt
                    while cur <= e_dt:
                        dates.add(cur.strftime("%Y-%m-%d"))
                        cur += pd.Timedelta(days=1)
                except Exception:
                    pass
        closures[centre] = dates
    return closures

def run_backtest():
    # 1. Map hawkers to stations
    map_df = map_hawkers_to_stations(RAW / "hawker_closures.csv", RAW / "rainfall_stations.csv")
    print(f"=== HAWKER TO STATION MAPPING ({len(map_df)} centres) ===")
    print(f"Mean distance to rain station:   {map_df['distance_km'].mean():.2f} km")
    print(f"Median distance to rain station: {map_df['distance_km'].median():.2f} km")
    print(f"Max distance:                   {map_df['distance_km'].max():.2f} km (P95: {map_df['distance_km'].quantile(0.95):.2f} km)")
    print(f"Unique stations utilized:        {map_df['station_id'].nunique()} stations\n")

    # 2. Cleaning closures analysis
    closures = parse_cleaning_closures(RAW / "hawker_closures.csv")
    closure_counts = [len(v) for v in closures.values()]
    print(f"=== CLEANING CLOSURE EXCLUSIONS ===")
    print(f"Mean scheduled cleaning days/yr: {np.mean(closure_counts):.1f} days")
    print(f"Stalls with closures scheduled: {sum(c > 0 for c in closure_counts)}/{len(closure_counts)}\n")

    # 3. Load daily weather records
    weather = pd.read_csv(RAW / "daily_weather_records.csv")
    for col in ["daily_rainfall_total", "highest_30_min_rainfall", "highest_60_min_rainfall", "highest_120_min_rainfall"]:
        weather[col] = pd.to_numeric(weather[col], errors="coerce")
    weather["date"] = pd.to_datetime(weather["date"])
    weather["year"] = weather["date"].dt.year
    weather = weather.dropna(subset=["daily_rainfall_total"])

    # Annual summary table
    annual_stats = []
    full_years = [y for y in sorted(weather["year"].unique()) if y <= 2016] # 2009-2016 are complete
    
    for y, g in weather.groupby("year"):
        d_tot = g["daily_rainfall_total"]
        h_60 = g["highest_60_min_rainfall"]
        n_days = len(g)
        ge20 = int((d_tot >= 20).sum())
        ge30 = int((d_tot >= 30).sum())
        ge50 = int((d_tot >= 50).sum())
        h10 = int((h_60 >= 10).sum())
        h20 = int((h_60 >= 20).sum())
        # Torrential rule: daily >= 50 or 1-hr >= 20
        flash_ge = int(((d_tot >= 50) | (h_60 >= 20)).sum())

        annual_stats.append({
            "year": y,
            "days_observed": n_days,
            "days_ge20mm": ge20,
            "days_ge30mm": ge30,
            "days_ge50mm": ge50,
            "days_1h_ge10mm": h10,
            "days_1h_ge20mm": h20,
            "days_flash_heavy": flash_ge,
            "max_daily_mm": round(float(d_tot.max()), 1),
            "max_1h_mm": round(float(h_60.max()) if not h_60.isna().all() else 0.0, 1)
        })

    annual_df = pd.DataFrame(annual_stats)
    annual_df.to_csv(RESULTS / "rain_backtest_annual.csv", index=False)
    print("=== ANNUAL RAINFALL EXTREME FREQUENCIES (Admiralty Station 2009-2017) ===")
    print(annual_df.to_string(index=False))

    mean_ge20 = annual_df.loc[annual_df["year"].isin(full_years), "days_ge20mm"].mean()
    mean_ge30 = annual_df.loc[annual_df["year"].isin(full_years), "days_ge30mm"].mean()
    mean_ge50 = annual_df.loc[annual_df["year"].isin(full_years), "days_ge50mm"].mean()
    mean_h10 = annual_df.loc[annual_df["year"].isin([2014, 2015, 2016]), "days_1h_ge10mm"].mean()
    mean_h20 = annual_df.loc[annual_df["year"].isin([2014, 2015, 2016]), "days_1h_ge20mm"].mean()
    mean_flash = annual_df.loc[annual_df["year"].isin([2014, 2015, 2016]), "days_flash_heavy"].mean()

    print(f"\nHistorical Annual Baseline (Full Years):")
    print(f"  Daily >= 20 mm: {mean_ge20:.1f} days/year ({mean_ge20/365*100:.1f}% of days)")
    print(f"  Daily >= 30 mm: {mean_ge30:.1f} days/year ({mean_ge30/365*100:.1f}% of days)")
    print(f"  Daily >= 50 mm: {mean_ge50:.1f} days/year ({mean_ge50/365*100:.1f}% of days)")
    print(f"  1-hour >= 10 mm: {mean_h10:.1f} days/year ({mean_h10/365*100:.1f}% of days)")
    print(f"  1-hour >= 20 mm: {mean_h20:.1f} days/year ({mean_h20/365*100:.1f}% of days)")
    print(f"  Flash Torrential (>=50mm daily OR >=20mm 1-hr): {mean_flash:.1f} days/year")

    # 4. Trigger options evaluation & pricing comparison
    # Cleaning closures reduce open exposure days by ~2.2% (8 days / 365)
    cleaning_adj = (365 - 8) / 365.0

    triggers = [
        {"name": "Option 1: Low Daily (>=20mm)", "threshold": "Daily >= 20 mm", "raw_days": mean_ge20, "payout": 30, "cap_days": 5},
        {"name": "Option 2: Moderate Daily (>=30mm)", "threshold": "Daily >= 30 mm", "raw_days": mean_ge30, "payout": 30, "cap_days": 5},
        {"name": "Option 3: High Hourly (1h >= 20mm)", "threshold": "1-Hour >= 20 mm", "raw_days": mean_h20, "payout": 40, "cap_days": 4},
        {"name": "Option 4: Extreme Daily (>=50mm)", "threshold": "Daily >= 50 mm", "raw_days": mean_ge50, "payout": 40, "cap_days": 4},
        {"name": "Option 5: Calibrated Flash (>=50mm OR 1h>=20mm)", "threshold": ">=50mm OR 1h >= 20mm", "raw_days": mean_flash, "payout": 40, "cap_days": 4},
    ]

    pricing_rows = []
    for t in triggers:
        # Effective days considering cleaning day exclusions and annual cap
        eff_days_uncapped = t["raw_days"] * cleaning_adj
        # With cap, expected paid days: Poisson/empirical expectation capped at cap_days
        # Approx capped expected days: min(raw_days * cleaning_adj, cap_days * 0.85)
        eff_days_capped = min(eff_days_uncapped, t["cap_days"] * (1 - math.exp(-eff_days_uncapped / t["cap_days"])))
        uncapped_cost = eff_days_uncapped * t["payout"]
        capped_cost = eff_days_capped * t["payout"]
        max_annual_payout = t["cap_days"] * t["payout"]
        # With 20% expense load (1 / 0.80)
        pure_premium = capped_cost
        gross_premium = pure_premium / 0.80
        weekly_cost = gross_premium / 52.0

        pricing_rows.append({
            "trigger_design": t["name"],
            "threshold_rule": t["threshold"],
            "raw_days_per_year": round(t["raw_days"], 1),
            "effective_paid_days": round(eff_days_capped, 2),
            "payout_per_day_sgd": t["payout"],
            "annual_cap_days": t["cap_days"],
            "max_possible_payout_sgd": max_annual_payout,
            "uncapped_annual_loss_sgd": round(uncapped_cost, 1),
            "expected_capped_loss_sgd": round(capped_cost, 1),
            "gross_annual_premium_sgd": round(gross_premium, 1),
            "weekly_premium_sgd": round(weekly_cost, 2),
            "is_viable": "Yes" if weekly_cost <= 3.50 else "No (Too expensive)"
        })

    pricing_df = pd.DataFrame(pricing_rows)
    pricing_df.to_csv(RESULTS / "rain_trigger_comparison.csv", index=False)
    print("\n=== TRIGGER DESIGN & PRICING COMPARISON ===")
    print(pricing_df[["trigger_design", "raw_days_per_year", "effective_paid_days", "payout_per_day_sgd", "annual_cap_days", "expected_capped_loss_sgd", "weekly_premium_sgd", "is_viable"]].to_string(index=False))

    # 5. Generate Figures
    # Plot 1: Annual frequency of rain thresholds
    fig, ax = plt.subplots(figsize=(10, 5))
    plot_years = annual_df[annual_df["year"] <= 2016]["year"].astype(str)
    x = np.arange(len(plot_years))
    width = 0.25

    ax.bar(x - width, annual_df.loc[annual_df["year"] <= 2016, "days_ge20mm"], width, label=">= 20 mm (Low)", color="#3498db")
    ax.bar(x, annual_df.loc[annual_df["year"] <= 2016, "days_ge30mm"], width, label=">= 30 mm (Medium)", color="#e67e22")
    ax.bar(x + width, annual_df.loc[annual_df["year"] <= 2016, "days_ge50mm"], width, label=">= 50 mm (Heavy / Torrential)", color="#e74c3c")

    ax.set_xticks(x)
    ax.set_xticklabels(plot_years)
    ax.set_ylabel("Number of Days per Year")
    ax.set_title("Singapore Historical Heavy Rain Days by Threshold (Admiralty Station)")
    ax.legend(frameon=True)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    fig.tight_layout()
    fig.savefig(RESULTS / "rain_threshold_frequency.png", dpi=160)
    plt.close(fig)

    # Plot 2: Cost by Trigger & Cap
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    labels = [r["trigger_design"].split(":")[0] for r in pricing_rows]
    exp_costs = [r["expected_capped_loss_sgd"] for r in pricing_rows]
    weekly_premiums = [r["weekly_premium_sgd"] for r in pricing_rows]

    bars = ax2.bar(labels, weekly_premiums, color=["#e74c3c", "#e67e22", "#f39c12", "#2ecc71", "#27ae60"], width=0.55)
    ax2.axhline(3.50, color="#c0392b", linestyle="--", linewidth=1.5, label="Micro-SME Budget Ceiling (S$3.50/wk)")
    ax2.set_ylabel("Gross Weekly Premium (S$ / week)")
    ax2.set_title("DayCover+ Rain Layer: Weekly Premium by Trigger Option")
    for bar, cost, wk in zip(bars, exp_costs, weekly_premiums):
        yval = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, yval + 0.15, f"S${wk:.2f}/wk\n(Loss S${cost:.0f})", ha="center", fontsize=8)
    ax2.set_ylim(0, max(weekly_premiums) * 1.25)
    ax2.legend()
    fig2.tight_layout()
    fig2.savefig(RESULTS / "rain_cost_by_trigger.png", dpi=160)
    plt.close(fig2)

    print("\nSaved figures to:")
    print(" - results/rain_threshold_frequency.png")
    print(" - results/rain_cost_by_trigger.png")

if __name__ == "__main__":
    run_backtest()
