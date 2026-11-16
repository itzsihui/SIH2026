"""Frozen product and pricing settings for the 2026 out-of-sample test. Change here only, never in code."""
RULES = {
    "version": "train-2026.11-v1",
    "haze_t1_psi": 101, "haze_t1_consecutive_days": 2, "haze_t1_units": 1.0,
    "haze_t2_psi": 151, "haze_t2_units": 2.0,          # severe haze day pays double
    "haze_cap_days": 5,
    "rain_daily_mm": 70.0, "rain_units": 1.0, "rain_cap_days": 2,
    "total_cap_days": 6,
    "exclude_closures": True,
}
TRAIN_YEARS = list(range(2010, 2026))     # rain
HAZE_TRAIN_YEARS = list(range(2015, 2026))  # PSI starts Apr 2014: first full year 2015
TEST_YEAR = 2026
TEST_END = "2026-10-31"                   # last day with daily rain files
PRICING = {
    "expense_ratio": 0.20,                # brief: expenses within ~20% of premium
    "margin": 0.05,
    "stoploss_attach_x_expected": 1.5,    # aggregate stop-loss attaches at 150% of expected annual claims
    "stoploss_limit_x_expected": 3.0,
    "stoploss_price_x_expected_layer": 1.6,   # reinsurer charges 1.6 x expected layer loss (assumption, team App. C)
    "fair_spread_cap": 1.5,               # riskiest centre rate <= 1.5 x cheapest
}
COVER = {
    "bands": [20, 30, 45, 60, 90], "payout_share_of_loss": 0.60,
    "default_drop": 0.20, "credibility_k_days": 10,   # shrink a stall's measured drop toward the default
    "assumed_margin": 0.50, "max_declared_cash_share": 0.95,   # cash share declared at sale, spot-checked
    "lite_band": 20, "lite_max_share_of_loss": 0.80,           # S$20 Lite only if it stays <= 80% of the stall's loss
    "active_days_before_event": 7,                             # must have QR sales in the 7 days before a trigger
}
# Typical share of sales lost on a TRIGGER day by a stall of average sensitivity (k = 1).
# rain: learned from QR history (pooled curve, 70-100 mm band). haze: no haze in 2023-25 QR history, so taken from
# 2026 reports (Tekka -30% to -60% at PSI ~200-230; team loss model 20/30/45%) until a haze season is observed.
IMPACT = {"rain_trigger_drop": None, "haze_t1_drop": 0.08, "haze_t2_drop": 0.27}
