"""Illustrative simulation: collecting a FIXED annual premium through a per-transaction levy over a long period.

The levy is a collection METHOD, not the price. Price (S$104/yr, indicative) comes from docs/41_pilot_pricing_and_billing.md.
Sales profiles are ASSUMPTIONS (no real transaction data exists); results show mechanics, not a forecast.
Run: python3 -m scripts.premium_accrual_sim
"""
import random, statistics, json

ANNUAL = 104.0
TARGETS = [8.67] * 8 + [8.66] * 4          # monthly instalments, sum S$104
TICKET = 5.0
PROFILES = {"light (6 QR sales/day)": 6, "medium (14/day)": 14, "busy (30/day)": 30}
DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
BAD_DAY_P = 0.10          # share of days hit by rain/haze (sales fall)
BAD_DAY_FACTOR = 0.5      # sales on those days relative to normal
MAX_CARRY = 1.0           # carry-forward allowed before a bank top-up is needed, in months of premium


def poisson(lam, rng):
    # Knuth; fine for small lambda, normal approx above 30
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, lam ** 0.5))))
    L, k, p = pow(2.718281828, -lam), 0, 1.0
    while p > L:
        k += 1; p *= rng.random()
    return k - 1


def run(mean_daily, rng, declared_factor=1.0):
    carry = 0.0; hist = []; out = []
    for m, days in enumerate(DAYS):
        target = TARGETS[m]
        # expected monthly QR sales: declared at onboarding, then trailing 3-month average
        exp_sales = (mean_daily * declared_factor * days * TICKET) if len(hist) < 1 else statistics.mean(hist[-3:])
        rate = (target + carry) / exp_sales            # calibrated levy rate for the month
        due = target + carry; collected = 0.0; sales = 0.0
        for d in range(days):
            f = BAD_DAY_FACTOR if rng.random() < BAD_DAY_P else 1.0
            n = poisson(mean_daily * f, rng)
            for _ in range(n):
                sales += TICKET
                if collected < due:
                    c = min(rate * TICKET, due - collected); collected += c      # stops when the month's instalment is met
        hist.append(sales)
        short = due - collected
        topup = 0.0
        if short > 1e-9:
            keep = min(short, MAX_CARRY * target)         # carried to next month
            topup = short - keep; carry = keep
        else:
            carry = 0.0
        out.append(dict(m=m + 1, rate_pct=100 * rate, levy=collected, topup=topup, met=short <= 1e-9, sales=sales))
    out[-1]['topup'] += carry              # year-end true-up: any remaining shortfall is collected by bank debit
    return out


def main():
    rng = random.Random(2026)
    res = {}
    print(f"{'profile':26s} {'levy share':>10s} {'months met':>11s} {'avg top-up/yr':>14s} {'avg levy rate':>14s} {'cents/S$5 sale':>15s}")
    for name, md in PROFILES.items():
        runs = [run(md, rng) for _ in range(500)]
        levy = statistics.mean(sum(x['levy'] for x in r) for r in runs)
        top = statistics.mean(sum(x['topup'] for x in r) for r in runs)
        met = statistics.mean(sum(x['met'] for x in r) / 12 for r in runs)
        rate = statistics.mean(x['rate_pct'] for r in runs for x in r)
        res[name] = dict(levy_share=levy / ANNUAL, months_met=met, topup=top, rate_pct=rate)
        print(f"{name:26s} {levy / ANNUAL:10.1%} {met:11.1%} {'S$%.2f' % top:>14s} {rate:13.2f}% {rate * TICKET:14.2f}c")
    # over-optimistic onboarding declaration (stall says 14/day, really does 7)
    runs = [run(7, rng, declared_factor=2.0) for _ in range(500)]
    print("\nStall declares 14/day but really sells 7/day (first month mis-calibrated):")
    ls = statistics.mean(sum(x["levy"] for x in r) for r in runs) / ANNUAL
    tu = statistics.mean(sum(x["topup"] for x in r) for r in runs)
    mm = statistics.mean(sum(x["met"] for x in r) / 12 for r in runs)
    print(f"  levy share {ls:.1%}, top-up S${tu:.2f}/yr, months met by levy alone {mm:.1%}")
    json.dump(res, open("results/premium_accrual_sim.json", "w"), indent=1)


if __name__ == "__main__":
    main()
