"""Price the DayCover+ pilot scenarios from the committed trigger replay."""
import argparse
import json
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from pathlib import Path
from statistics import mean

from src.daycover.rules import DEFAULT_RULES


CENT = Decimal("0.01")
WEEKS = 52
MONTHS = 12
WEEKLY_GRID = tuple(map(Decimal, ("1.50", "2.00", "2.50", "3.00")))
BASE_WEEKLY = Decimal("2.00")
EXPENSE = Decimal("0.20")
TARGET = Decimal("0.10")
SUCCESS_FEES = tuple(map(Decimal, ("0.05", "0.20", "0.50")))
BASE_FEE = Decimal("0.20")
FAILED_FEE = Decimal("1.00")
FAILURE_SHARE = Decimal("0.05")
ATTACHMENT = Decimal("9594")
LAYER_LIMIT = Decimal("10000")
CEDED_RATES = tuple(map(Decimal, ("10", "15", "20")))
BASE_CEDED = Decimal("15")
SUBSIDY_PER_MONTH = Decimal("2")
SUBSIDY_MONTHS = 6
RAIN_COLUMNS = {"sample_observed": "rain_claims_lower", "pooled_poisson": "rain_claims_upper"}


def money(amount):
    return float(amount.quantize(CENT, rounding=ROUND_HALF_UP))


def collection_cost(debits, success_fee=BASE_FEE):
    return debits * (success_fee + FAILURE_SHARE * FAILED_FEE)


def recovery(loss):
    return min(LAYER_LIMIT, max(Decimal(0), loss - ATTACHMENT))


def price_scenarios(rows, stalls):
    scenarios = {}
    for name, key in RAIN_COLUMNS.items():
        matched = [row["haze_claims"] + row[key] for row in rows if key in row]
        mean_rain = mean(row[key] for row in rows if key in row)
        full = [row["haze_claims"] + row.get(key, mean_rain) for row in rows]
        scenarios[name] = {
            "overlap_claims_per_policy_sgd": money(mean(matched) / stalls),
            "mean_rain_imputation_per_portfolio_sgd": money(mean_rain),
            "full_claims_per_policy_sgd": money(mean(full) / stalls),
            "mean_recovery_per_policy_sgd": money(mean(map(recovery, full)) / stalls),
            "quote_sensitivity": [],
            "premium_grid": [],
        }
        result = scenarios[name]
        gross_claims = mean(full) / stalls
        mean_recovery = mean(map(recovery, full)) / stalls
        for ceded in CEDED_RATES:
            net_cost = ceded - mean_recovery
            annual = (gross_claims + collection_cost(MONTHS) + net_cost) / (1 - EXPENSE - TARGET)
            result["quote_sensitivity"].append({"ceded_per_policy_sgd": money(ceded),
                                                 "net_reinsurance_cost_per_policy_sgd": money(net_cost),
                                                 "weekly_price_at_target_sgd": float((annual / WEEKS).quantize(CENT, rounding=ROUND_CEILING))})
        for weekly in WEEKLY_GRID:
            annual = weekly * WEEKS
            before = annual * (1 - EXPENSE) - gross_claims - collection_cost(MONTHS)
            after = before - BASE_CEDED + mean_recovery
            result["premium_grid"].append({"weekly_sgd": money(weekly), "annual_sgd": money(annual),
                                           "expense_per_policy_sgd": money(annual * EXPENSE),
                                           "contribution_before_reinsurance_sgd": money(before),
                                           "contribution_after_ceded_premium_without_recovery_sgd": money(before - BASE_CEDED),
                                           "contribution_after_reinsurance_sgd": money(after),
                                           "contribution_after_reinsurance_pct": money(100 * after / annual)})
    return scenarios


def stress_tests(rows, stalls):
    by_year = {r["year"]: r for r in rows}
    max_rain = stalls * Decimal(str(DEFAULT_RULES.rain_payout)) * DEFAULT_RULES.rain_cap_days_per_year
    cases = {
        "2015_haze_only": by_year[2015]["haze_claims"],
        "2015_haze_plus_max_rain": by_year[2015]["haze_claims"] + max_rain,
        "2019_with_observed_rain": by_year[2019]["haze_claims"] + by_year[2019][RAIN_COLUMNS["sample_observed"]],
        "2019_with_pooled_rain": by_year[2019]["haze_claims"] + by_year[2019][RAIN_COLUMNS["pooled_poisson"]],
    }
    available = stalls * (BASE_WEEKLY * WEEKS * (1 - EXPENSE) - collection_cost(MONTHS))
    return {label: {"gross_claims_sgd": money(loss), "recovery_sgd": money(recovery(loss)),
                    "retained_claims_sgd": money(loss - recovery(loss)),
                    "result_without_reinsurance_sgd": money(available - loss),
                    "result_with_reinsurance_sgd": money(available - loss + recovery(loss) - stalls * BASE_CEDED)}
            for label, loss in cases.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest", type=Path, default=Path("public/data/backtest_results.json"))
    parser.add_argument("--out", type=Path, default=Path("results/pilot_pricing.json"))
    args = parser.parse_args()
    data = json.loads(args.backtest.read_text(), parse_float=Decimal)
    meta = data["meta"]
    if (meta["rule_version"], meta["rain_trigger_mm"], meta["haze_money_cap_sgd"], meta["haze_day_definition"]) != (
        DEFAULT_RULES.version, DEFAULT_RULES.rain_daily_mm, DEFAULT_RULES.haze_cap_amount_per_year, DEFAULT_RULES.haze_day_definition
    ):
        parser.error("backtest metadata must match the published DayCover+ rules")
    rows, stalls = data["annual"], meta["stalls"]
    max_haze = Decimal(str(DEFAULT_RULES.haze_cap_amount_per_year))
    max_rain = Decimal(str(DEFAULT_RULES.rain_payout)) * DEFAULT_RULES.rain_cap_days_per_year
    output = {
        "rule_version": meta["rule_version"], "representative_stalls": stalls,
        "maximum_annual_portfolio_payout_sgd": money(stalls * (max_haze + max_rain)),
        "expense_share": float(EXPENSE), "target_contribution_share": float(TARGET),
        "illustrative_reinsurance": {"annual_aggregate_attachment_sgd": money(ATTACHMENT), "annual_limit_sgd": money(LAYER_LIMIT),
                                      "base_ceded_premium_per_policy_sgd": money(BASE_CEDED)},
        "collection_assumptions": {"base_success_fee_sgd": money(BASE_FEE), "failed_fee_sgd": money(FAILED_FEE),
                                   "share_with_one_recovered_failure": float(FAILURE_SHARE)},
        "collection_sensitivity": [{"success_fee_sgd": money(fee), "weekly_collection_annual_cost_sgd": money(collection_cost(WEEKS, fee)),
                                    "monthly_collection_annual_cost_sgd": money(collection_cost(MONTHS, fee))} for fee in SUCCESS_FEES],
        "pricing": price_scenarios(rows, stalls),
        "stress_at_base_weekly_premium": {"weekly_sgd": money(BASE_WEEKLY), "cases": stress_tests(rows, stalls)},
        "subsidy": {"credit_per_month_sgd": money(SUBSIDY_PER_MONTH), "months": SUBSIDY_MONTHS,
                    "budget_sgd": {str(n): money(n * SUBSIDY_PER_MONTH * SUBSIDY_MONTHS) for n in (50, 100, 200)}},
    }
    args.out.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
