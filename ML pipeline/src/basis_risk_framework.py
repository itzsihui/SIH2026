"""
basis_risk_framework.py
======================
Team FIN-2 (Singapore-India Hackathon 2026)
Empirical Framework for Estimating Hawker Loss Given Trigger (ELGT),
Basis Risk False-Negative/Positive Rates, and Public Proxy Valuation.

Run:
  .venv/bin/python src/basis_risk_framework.py
"""

import os
import numpy as np
import pandas as pd

def run_basis_risk_analysis():
    np.random.seed(42)
    n_sims = 10000

    # 1. Ranking Public Proxies for Hawker Loss
    proxies = [
        {
            "rank": 1,
            "proxy_name": "LTA DataMall - Carpark Availability (HDB/URA near hawkers)",
            "spatial_granularity": "Micro (Individual Carpark at Hawkers)",
            "temporal_frequency": "Real-time (1-5 min polling)",
            "hawker_directness": "High (Direct proxy for vehicle-based diners & takeaway)",
            "inherent_bias": "Under-represents pedestrian walk-ins; over-indexes destination hawkers",
            "access_method": "LTA DataMall API (Free registered API key)",
            "verdict": "Primary real-time proxy for localized parking demand drop"
        },
        {
            "rank": 2,
            "proxy_name": "LTA DataMall - Bus/Train Origin-Destination Alighting Volume",
            "spatial_granularity": "Precinct (Adjacent Bus Stop / MRT Station)",
            "temporal_frequency": "Monthly aggregated by day-type / hour",
            "hawker_directness": "Medium-High (Measures passenger outflow near food centres)",
            "inherent_bias": "Blends commuters going home with diners; lags by 1 month",
            "access_method": "LTA DataMall Monthly CSV batches",
            "verdict": "Secondary validation proxy for macro pedestrian mobility"
        },
        {
            "rank": 3,
            "proxy_name": "Pasir Panjang Wholesale Centre Daily Produce Volumes",
            "spatial_granularity": "National / Wholesale Market",
            "temporal_frequency": "Daily / Weekly ministerial disclosures",
            "hawker_directness": "High (Hawkers purchase 70%+ of raw vegetables/seafood here)",
            "inherent_bias": "Wholesale orders lag footfall shock by 24-48 hours",
            "access_method": "MSE / SFA Parliamentary Disclosures & Trade Reports",
            "verdict": "Strong macro-economic confirmation (verified 20-30% drop in Oct 2026)"
        },
        {
            "rank": 4,
            "proxy_name": "Google / Apple Community Mobility Reports (Transit & Retail)",
            "spatial_granularity": "National / Regional (Singapore aggregate)",
            "temporal_frequency": "Daily (Historical archive 2020-2022)",
            "hawker_directness": "Medium (Captures retail/recreation avoidance behavior)",
            "inherent_bias": "Discontinued late 2022; historical benchmark only",
            "access_method": "Google COVID-19 Community Mobility Archive",
            "verdict": "Useful for training baseline avoidance elasticities"
        },
        {
            "rank": 5,
            "proxy_name": "SingStat Food & Beverage Services Index (FSI)",
            "spatial_granularity": "National Aggregate (Sub-sectors: Fast Food, Restaurants)",
            "temporal_frequency": "Monthly index (released 5 weeks post-month)",
            "hawker_directness": "VERY LOW (EXCLUDES individual hawkers, coffee shops, and canteens)",
            "inherent_bias": "Severe masking bias: Fast food/mall delivery surges offset hawker drop",
            "access_method": "SingStat Table Builder / data.gov.sg",
            "verdict": "UNSUITABLE as direct hawker proxy; illustrates structural exclusion"
        }
    ]

    proxy_df = pd.DataFrame(proxies)
    out_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(out_dir, exist_ok=True)
    proxy_csv_path = os.path.join(out_dir, "basis_risk_proxies.csv")
    proxy_df.to_csv(proxy_csv_path, index=False)
    print(f"Saved: {proxy_csv_path}")

    # 2. Monte Carlo Estimation of Expected Loss Given Trigger (ELGT)
    # Baseline Hawker Economics (Distribution across 6,000 cooked-food stalls)
    # Daily Gross Revenue: Normal(mean=S$650, sd=S$120), clipped at S$350 to S$1200
    daily_gross = np.clip(np.random.normal(650, 120, n_sims), 350, 1200)
    
    # Food Ingredient Margin (COGS = 30% +/- 5%, so gross margin = 70% +/- 5%)
    gross_margin_rate = np.random.uniform(0.65, 0.75, n_sims)
    
    # Fixed Daily Operating Cost (Rent S$42/day, S&CC + Cleaning S$25/day, Utilities S$35/day, Base Pay S$60/day)
    # Total fixed daily overhead approx S$160 +/- S$30
    fixed_overhead = np.random.normal(160, 30, n_sims)

    # Footfall Loss Elasticities under Trigger Events:
    # A. Rain >= 50mm: Footfall drop Beta distribution scaled to [30%, 65%]
    rain_footfall_drop = np.random.beta(3, 4, n_sims) * 0.35 + 0.30
    # Delivery capture: hawker captures only 10% to 20% of lost footfall
    delivery_recovery = np.random.uniform(0.10, 0.20, n_sims)
    net_rain_revenue_drop = rain_footfall_drop * (1 - delivery_recovery)
    
    # Dollar Loss Given Rain Trigger
    # Dollar Loss = (Gross Revenue * Net Drop * Margin Rate) + unrecoverable prepped perishable food
    food_spoilage = np.random.uniform(25, 60, n_sims)
    dollar_loss_rain = (daily_gross * net_rain_revenue_drop * gross_margin_rate) + food_spoilage
    
    # B. Haze PSI >= 151: Footfall drop scaled to [35%, 70%]
    haze_footfall_drop = np.random.beta(4, 3, n_sims) * 0.35 + 0.35
    net_haze_revenue_drop = haze_footfall_drop  # Delivery suspended / zero capture
    dollar_loss_haze = (daily_gross * net_haze_revenue_drop * gross_margin_rate) + (food_spoilage * 0.6)

    # 3. Parametric Payout Performance & Basis Risk Metrics
    payout_amount = 60.0  # DayCover+ standard daily cash payout

    # Net Economic Protection = Payout / Actual Dollar Loss
    rain_coverage_ratio = payout_amount / dollar_loss_rain
    haze_coverage_ratio = payout_amount / dollar_loss_haze

    # Basis Risk Thresholds:
    # A day is a "True Economic Loss Event" if Dollar Loss >= S$40 (meaningful financial strain)
    # Downside Basis Risk (False Negative): Stall suffered loss >= S$40, but station missed trigger (from task 1: 4.46% for rain)
    # Upside Basis Risk (False Positive): Station triggered, but stall loss < S$40 (e.g. captive indoor hub)
    rain_false_positive_loss_prob = np.mean(dollar_loss_rain < 40.0)

    summary_stats = {
        "metric": [
            "Mean Baseline Daily Gross Turnover (SGD)",
            "Median Baseline Daily Net Margin (SGD)",
            "Mean Net Revenue Drop on Rain Trigger (>=50mm)",
            "Mean Net Revenue Drop on Haze Trigger (PSI>=151)",
            "Expected Loss Given Rain Trigger (ELGT - SGD)",
            "95% CI for Loss Given Rain Trigger (SGD)",
            "Expected Loss Given Haze Trigger (ELGT - SGD)",
            "95% CI for Loss Given Haze Trigger (SGD)",
            "DayCover+ Fixed Payout Amount (SGD)",
            "Mean Protection Ratio on Rain Trigger (% of lost margin covered)",
            "Mean Protection Ratio on Haze Trigger (% of lost margin covered)",
            "Physical False-Negative Rate (Task 1 Empirical Missed Trigger %)",
            "Economic False-Positive Rate (Loss < S$40 on trigger day)"
        ],
        "value": [
            f"S${np.mean(daily_gross):.2f}",
            f"S${np.median(daily_gross * gross_margin_rate - fixed_overhead):.2f}",
            f"{np.mean(net_rain_revenue_drop)*100:.1f}%",
            f"{np.mean(net_haze_revenue_drop)*100:.1f}%",
            f"S${np.mean(dollar_loss_rain):.2f}",
            f"S${np.percentile(dollar_loss_rain, 2.5):.2f} - S${np.percentile(dollar_loss_rain, 97.5):.2f}",
            f"S${np.mean(dollar_loss_haze):.2f}",
            f"S${np.percentile(dollar_loss_haze, 2.5):.2f} - S${np.percentile(dollar_loss_haze, 97.5):.2f}",
            f"S${payout_amount:.2f}",
            f"{np.mean(rain_coverage_ratio)*100:.1f}%",
            f"{np.mean(haze_coverage_ratio)*100:.1f}%",
            "4.46% (Task 1 empirical majority neighbour mesh)",
            f"{rain_false_positive_loss_prob*100:.2f}%"
        ]
    }

    summary_df = pd.DataFrame(summary_stats)
    summary_csv_path = os.path.join(out_dir, "basis_risk_elgt_summary.csv")
    summary_df.to_csv(summary_csv_path, index=False)
    print(f"Saved: {summary_csv_path}")

    print("\n=== BASIS RISK & EXPECTED LOSS GIVEN TRIGGER (ELGT) SUMMARY ===")
    for m, v in zip(summary_df["metric"], summary_df["value"]):
        print(f"  {m:65s}: {v}")

if __name__ == "__main__":
    run_basis_risk_analysis()
