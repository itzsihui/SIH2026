"""Reproduce the rain threshold and haze definition/cap comparisons for issue #4."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from random import Random
from statistics import median, quantiles

from src.daycover import data
from src.daycover.engine import rain_observation, replay
from src.daycover.rules import DEFAULT_RULES, rain_daily


HAZE_START = date(2015, 1, 1)
HAZE_END = date(2025, 12, 31)
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 42
TRIGGER_STATES = ((True, True), (True, False), (False, True), (False, False))


def error_rates(counts):
    both, false, missed, _ = counts
    return (100 * false / (both + false) if both + false else None,
            100 * missed / (both + missed) if both + missed else None)


def bootstrap_rates(daily_counts):
    """Resample whole dates within each calendar month, preserving sample sizes."""
    by_month = defaultdict(list)
    for day, counts in daily_counts.items():
        by_month[day.month].append(counts)
    rng = Random(BOOTSTRAP_SEED)
    estimates = [[], []]
    for _ in range(BOOTSTRAP_DRAWS):
        sample = [counts for month in by_month.values() for counts in rng.choices(month, k=len(month))]
        for rates, estimate in zip(estimates, error_rates(tuple(map(sum, zip(*sample))))):
            if estimate is not None:
                rates.append(estimate)
    intervals = []
    for rates in estimates:
        if len(rates) < 2:
            intervals.append(None)
            continue
        bounds = quantiles(rates, n=40, method="inclusive")
        intervals.append([round(bounds[0], 2), round(bounds[-1], 2)])
    return intervals


def rain_comparison(stalls):
    dates = sorted(data.rain_dates())
    readings = data.rain_daily_table()
    radius = DEFAULT_RULES.gauge_fallback_km
    neighbours = {s.id: [g for g, km in data.nearest_gauges(s.lat, s.lon, len(data.gauges())) if km <= radius]
                  for s in stalls}
    results = []
    for threshold in (70.0, 80.0):
        rules = replace(DEFAULT_RULES, rain_daily_mm=threshold)
        daily = {day: Counter() for day in dates}
        observed_stall_years = set()
        qualifying_stall_years = set()
        open_observations = hits = fallback_observations = proxy_fallback_observations = 0
        for day in dates:
            for stall in stalls:
                if day in stall.closures:
                    continue
                observation = rain_observation(stall, day, rules)
                if observation is None:
                    continue
                gauge, reading, fallback = observation
                hit, _ = rain_daily(reading["mm"], rules)
                open_observations += 1
                hits += hit
                fallback_observations += fallback
                observed_stall_years.add((stall.id, day.year))
                if hit:
                    qualifying_stall_years.add((stall.id, day.year))
                nearby = [row["mm"] for other in neighbours[stall.id] if other != gauge
                          if (row := readings.get((day, other))) and row["valid"]]
                if len(nearby) >= 2:
                    proxy_fallback_observations += fallback
                    proxy_hit = median(nearby) >= threshold
                    daily[day][hit, proxy_hit] += 1

        daily_counts = {day: tuple(counts[state] for state in TRIGGER_STATES) for day, counts in daily.items()}
        counts = tuple(map(sum, zip(*daily_counts.values())))
        false, missed = error_rates(counts)
        false_ci, missed_ci = bootstrap_rates(daily_counts)
        results.append({
            "threshold_mm": threshold,
            "open_stall_days_with_reading": open_observations,
            "open_stall_days_qualifying": hits,
            "annualised_trigger_days_per_stall": round(hits / open_observations * 365.25, 2),
            "open_stall_days_using_fallback": fallback_observations,
            "observed_stall_years": len(observed_stall_years),
            "observed_stall_years_with_payout": len(qualifying_stall_years),
            "observed_payout_sgd": len(qualifying_stall_years) * rules.rain_payout,
            "paired_stall_days": sum(counts),
            "paired_stall_days_using_fallback": proxy_fallback_observations,
            "paired_counts": dict(zip(("both", "policy_only", "proxy_only", "neither"), counts)),
            "false_trigger_pct": round(false, 2) if false is not None else None,
            "false_trigger_ci95_pct": false_ci,
            "missed_trigger_pct": round(missed, 2) if missed is not None else None,
            "missed_trigger_ci95_pct": missed_ci,
        })
    return {
        "dates": len(dates),
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "dates_by_month": dict(sorted(Counter(day.month for day in dates).items())),
        "proxy": f"Median of at least two other valid gauges within {radius:g} km of the stall",
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED, "block": "date, within calendar month"},
        "comparison": results,
    }


def hourly_psi():
    daily_max, noon = defaultdict(dict), defaultdict(dict)
    with (data.RAW / "psi_24hr_history.csv").open(newline="") as source:
        for row in csv.DictReader(source):
            day_text, clock = row["24hr_psi"].split()
            day = date.fromisoformat(day_text) if "-" in day_text else datetime.strptime(day_text, "%d/%m/%Y").date()
            hour, minute, *_ = map(int, clock.split(":"))  # also handles the source's 010:00:00 row
            if not HAZE_START - timedelta(days=1) <= day <= HAZE_END:
                continue
            for region in data.REGION_CENTROIDS:
                if not row[region].strip():
                    continue
                value = float(row[region])
                daily_max[day][region] = max(value, daily_max[day].get(region, value))
                if hour == 12 and minute == 0:
                    noon[day][region] = value
    return daily_max, noon


def haze_result(stalls, history, cap):
    rules = replace(DEFAULT_RULES, haze_cap_amount_per_year=cap)
    annual = dict.fromkeys(range(HAZE_START.year, HAZE_END.year + 1), 0.0)
    paid_by_stall_year = Counter()
    by_day = Counter()
    paid_days = 0
    for event in replay(stalls, HAZE_START, HAZE_END, rules, psi_history=history):
        if event.peril == "haze" and event.status == "paid":
            year = int(event.date[:4])
            annual[year] += event.amount
            by_day[event.date] += event.amount
            paid_by_stall_year[(event.stall_id, year)] += event.amount
            paid_days += 1
    return {"cap_sgd": cap, "total_payout_sgd": sum(annual.values()), "annual_payout_sgd": annual,
            "paid_stall_days": paid_days, "days_with_payout": len(by_day),
            "stall_years_reaching_money_cap": sum(total >= cap for total in paid_by_stall_year.values()),
            "largest_payout_day": dict(by_day.most_common(1))}


def haze_comparison(stalls):
    daily_max, noon = hourly_psi()
    sources = {"highest_hourly_24hr_psi": daily_max, "noon_24hr_psi": noon,
               "committed_daily_max_24hr_psi": data.psi_daily()}
    matched = {name: defaultdict(dict) for name in sources}
    paired = differences = 0
    coverage = Counter()
    for offset in range((HAZE_END - HAZE_START).days + 2):
        day = HAZE_START - timedelta(days=1) + timedelta(days=offset)
        for region in data.REGION_CENTROIDS:
            values = {name: history.get(day, {}).get(region) for name, history in sources.items()}
            for name, value in values.items():
                coverage[name] += value is not None
            if any(value is None for value in values.values()):
                continue
            paired += 1
            differences += values["highest_hourly_24hr_psi"] != values["committed_daily_max_24hr_psi"]
            for name, value in values.items():
                matched[name][day][region] = value
    return {
        "first_date": HAZE_START.isoformat(), "last_date": HAZE_END.isoformat(),
        "region_day_coverage_with_prior_day": dict(coverage),
        "matched_region_days_with_prior_day": paired,
        "matched_region_days_where_maxima_differ": differences,
        "matched_definition_comparison": {name: [haze_result(stalls, history, cap) for cap in (150.0, 300.0)]
                                          for name, history in matched.items()},
        "cap_comparison_on_full_committed_series": [haze_result(stalls, sources["committed_daily_max_24hr_psi"], cap)
                                                   for cap in (150.0, 300.0)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("results/trigger_calibration.json"))
    args = parser.parse_args()
    stalls = data.load_stalls()
    result = {"stalls": len(stalls), "rule_version": DEFAULT_RULES.version, "rain": rain_comparison(stalls),
              "haze": haze_comparison(stalls)}
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
