"""Read-only historical loss-ratio backtest on REAL NEA data, via the locked engine (src/daycover).

Output: public/data/backtest_results.json for the insurer dashboard.
Premium is an ASSUMPTION (--weekly, default S$2.00), not a priced product.
Haze: full-year replay 2015-2025. Rain: the committed data covers a calendar-stratified sample.
  lower = observed payouts from the sampled dates under the replay rules.
  upper = pooled Poisson scenario: annual hits = sampled open-day hit rate x 365, P(>=1)=1-exp(-lambda).
          The scenario assumes independent days and homogeneous exposure. The two values are not a confidence interval.
"""
import argparse, json, math, collections
from dataclasses import replace
from datetime import date
from src.daycover import data
from src.daycover.engine import rain_observation, replay
from src.daycover.rules import DEFAULT_RULES, HAZE_DAY_DEFINITION, rain_daily


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", type=float, default=2.0)
    ap.add_argument("--haze-money-cap", type=float, default=DEFAULT_RULES.haze_cap_amount_per_year)
    ap.add_argument("--rain-mm", type=float, default=DEFAULT_RULES.rain_daily_mm)
    ap.add_argument("--out", default="public/data/backtest_results.json")
    a = ap.parse_args()
    if any(not math.isfinite(v) or v <= 0 for v in (a.weekly, a.haze_money_cap, a.rain_mm)):
        ap.error("premium, haze monetary cap, and rain threshold must be finite and positive")
    rules = replace(DEFAULT_RULES, haze_cap_amount_per_year=a.haze_money_cap, rain_daily_mm=a.rain_mm)

    stalls = data.load_stalls("haze+rain")
    n = len(stalls)
    prem = a.weekly * 52
    years_h = list(range(2015, 2026))
    ev = replay(stalls, date(2015, 1, 1), date(2025, 12, 31), rules)

    # --- haze: paid events per stall-year, per day accumulation
    haze_y = dict.fromkeys(years_h, 0.0)
    rain_paid = collections.Counter()
    per_day = collections.defaultdict(lambda: [0, 0.0])
    for e in ev:
        if e.status != "paid":
            continue
        y = int(e.date[:4])
        if e.peril == "haze":
            haze_y[y] += e.amount
            per_day[e.date][0] += 1
            per_day[e.date][1] += e.amount
        elif e.peril == "rain":
            rain_paid[y] += e.amount

    # --- rain: sample-based range
    sampled = collections.defaultdict(list)
    for d in sorted(data.rain_dates()):
        if d.year in years_h:
            sampled[d.year].append(d)
    rain_y = {}
    for y, ds in sampled.items():
        hits = obs = 0
        for s in stalls:
            for d in ds:
                if d in s.closures:
                    continue
                reading = rain_observation(s, d, rules)
                if reading:
                    obs += 1
                    hits += rain_daily(reading[1]["mm"], rules)[0]
        lo = rain_paid[y]
        lam = hits / max(obs, 1) * 365
        hi = n * rules.rain_payout * (1 - math.exp(-lam))
        rain_y[y] = {"claims_lower": round(lo, 2), "claims_upper": round(hi, 2), "sampled_days": len(ds)}

    rows = []
    for y in years_h:
        gwp = n * prem
        r = rain_y.get(y)
        row = {"year": y, "gwp": round(gwp, 2), "haze_claims": round(haze_y[y], 2),
               "haze_loss_ratio": round(haze_y[y] / gwp, 4)}
        if r:
            row.update(rain_claims_lower=r["claims_lower"], rain_claims_upper=r["claims_upper"], rain_sampled_days=r["sampled_days"],
                       total_loss_ratio_lower=round((haze_y[y] + r["claims_lower"]) / gwp, 4),
                       total_loss_ratio_upper=round((haze_y[y] + r["claims_upper"]) / gwp, 4))
        rows.append(row)

    top = sorted(per_day.items(), key=lambda kv: -kv[1][1])[:15]
    haze_tot = sum(haze_y.values())
    gwp_tot_h = n * prem * len(years_h)
    ry = [r for r in rows if "rain_claims_lower" in r]
    out = {
        "meta": {"basis": "real NEA data through src/daycover engine (read-only); NOT synthetic", "rule_version": rules.version,
                 "stalls": n, "stall_definition": "one representative stall per NEA hawker centre (123)",
                 "premium_assumption_weekly_sgd": a.weekly, "premium_note": "assumption, not a priced product",
                 "haze_money_cap_sgd": rules.haze_cap_amount_per_year,
                 "haze_day_cap": rules.haze_cap_days_per_year, "haze_day_definition": HAZE_DAY_DEFINITION,
                 "rain_trigger_mm": rules.rain_daily_mm, "rain_sample_dates": len(data.rain_dates()),
                 "rain_claims_method": "Observed sampled-date payouts and pooled Poisson scenario, not statistical bounds",
                 "haze_years": [years_h[0], years_h[-1]], "rain_years": [ry[0]["year"], ry[-1]["year"]] if ry else None,
                 "limits": ["Rain uses a calendar-stratified sample: observed payouts and a pooled Poisson scenario",
                            "PSI region = nearest region centre (approximation)",
                            "Caps reset per calendar year; no reinsurance or expenses modelled",
                            "123 stalls is a portfolio proxy, not a book of business"]},
        "annual": rows,
        "haze_total": {"claims": round(haze_tot, 2), "gwp": round(gwp_tot_h, 2), "loss_ratio": round(haze_tot / gwp_tot_h, 4)},
        "rain_total": {"loss_ratio_lower": round(sum(r["rain_claims_lower"] for r in ry) / (n * prem * len(ry)), 4) if ry else None,
                       "loss_ratio_upper": round(sum(r["rain_claims_upper"] for r in ry) / (n * prem * len(ry)), 4) if ry else None},
        "accumulation_top_haze_days": [{"date": d, "stalls_paid": v[0], "share_of_portfolio": round(v[0] / n, 3), "payout_sgd": v[1]} for d, v in top],
        "worst_haze_year": max(rows, key=lambda r: r["haze_claims"])["year"],
    }
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("haze_total", "rain_total", "worst_haze_year")}, indent=1))
    for r in rows: print(r)


if __name__ == "__main__":
    main()
