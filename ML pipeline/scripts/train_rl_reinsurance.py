"""Train and benchmark the RL reinsurance agent against fixed rules.
    python scripts/train_rl_reinsurance.py
Calibrated on the real DayCover claim history (2014-2026) produced by walk_forward.py."""
import json, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "src"))
from pricing.rl_reinsurance import (Env, train, evaluate, fit_haze_probability, decode,
                                    STRUCTURES, STRUCTURE_NAMES, N_STATES, N_ACTIONS)

YEARS = list(range(2014, 2027))
RAIN = [311165, 103915, 278365, 345390, 288105, 231100, 351055, 375800, 318480, 371500, 356685, 375800, 160640]
HAZE = [0, 1706000, 0, 0, 0, 173490, 0, 0, 0, 0, 0, 0, 1651745]
ONI_MJJ = [0.22, 1.19, 0.09, 0.32, 0.13, 0.59, -0.18, -0.31, -0.73, 0.73, 0.18, -0.02, 1.39]
PREMIUM, EXPENSE = 1_067_051, 0.20
STATIC = STRUCTURE_NAMES.index("1.5x / 3x (static rule)")


def main():
    p_haze, coef = fit_haze_probability(ONI_MJJ, [h > 0 for h in HAZE])
    print("P(severe haze season | May-Jul ONI), from 13 real seasons:")
    print(f"   ONI above +0.5 : {coef['severe_high']} severe in {coef['n_high']} seasons -> {coef['p_high_enso']:.0%}")
    print(f"   ONI at or below: {coef['severe_low']} severe in {coef['n_low']} seasons -> {coef['p_low_enso']:.0%}")
    env = Env(PREMIUM, EXPENSE, RAIN, HAZE, p_haze, ONI_MJJ)
    print(f"\nexpected annual claims S${env.EL:,.0f} on S${PREMIUM:,.0f} premium; solvency floor S${env.floor:,.0f}")

    Q, visits = train(env)
    print(f"trained: {int((visits > 0).sum())} of {N_STATES * N_ACTIONS} state-action pairs visited")

    HEAVY, LIGHT = STRUCTURE_NAMES.index("1.0x / 3x"), STRUCTURE_NAMES.index("2.0x / 3x")
    pol = {
        "no reinsurance": lambda s, e: 0,
        "static 1.5x / 3x (current design)": lambda s, e: STATIC,
        "maximum cover every year": lambda s, e: HEAVY,
        "ENSO rule: heavy cover when ONI > 0.5": lambda s, e: HEAVY if e.enso > 0.5 else LIGHT,
        "ENSO rule + no cover in La Nina": lambda s, e: HEAVY if e.enso > 0.5 else (LIGHT if e.enso > -0.3 else 0),
        "CAPITAL rule: heavy cover below 1x premium": lambda s, e: HEAVY if e.capital < e.premium else STATIC,
        "CAPITAL + ENSO rule": lambda s, e: HEAVY if (e.capital < e.premium or e.enso > 0.5) else STATIC,
        "RL agent": lambda s, e: int(Q[s].argmax()),
        "oracle (knows the season in advance)": None,
    }
    res = {}
    for k, f in pol.items():
        if f is None:
            import numpy as _np
            def oracle(s, e, _h=HEAVY, _l=LIGHT):
                return _h if e.rng.random() < e.p_haze(e.enso) else 0   # upper bound only
            f = oracle
        res[k] = evaluate(env, f)
    print(f"\n{'policy':36s} {'10yr profit':>13s} {'worst 5%':>12s} {'P(10yr loss)':>13s} {'P(breach)':>10s} {'yr CVaR5%':>12s}")
    for k, r in res.items():
        print(f"{k:36s} {r['mean_10yr']:13,.0f} {r['p5_10yr']:12,.0f} {r['prob_10yr_loss']:12.1%} "
              f"{r['prob_solvency_breach']:10.1%} {r['cvar5_year']:12,.0f}")

    base, rl = res["static 1.5x / 3x (current design)"], res["RL agent"]
    print(f"\nRL vs the static rule: 10-year profit {rl['mean_10yr'] - base['mean_10yr']:+,.0f} "
          f"({(rl['mean_10yr'] / base['mean_10yr'] - 1):+.1%}), solvency breaches "
          f"{base['prob_solvency_breach']:.1%} -> {rl['prob_solvency_breach']:.1%}, "
          f"worst-5% ten-year outcome {rl['p5_10yr'] - base['p5_10yr']:+,.0f}")

    print("\nLEARNED POLICY (printed in full -- this is the whole model, auditable by an actuary)")
    print(f"{'capital':10s} {'ENSO signal':20s} {'haze history':18s} {'buy':s}")
    seen = set()
    for s in range(N_STATES):
        if visits[s].sum() < 50:
            continue
        cap, enso, quiet = decode(s)
        line = (cap, enso, quiet, STRUCTURE_NAMES[int(Q[s].argmax())])
        if line in seen: continue
        seen.add(line)
        print(f"{cap:10s} {enso:20s} {quiet:18s} {line[3]}")

    print("\nWHAT DRIVES THE AGENT'S CHOICE (mean attachment multiple; lower = more cover bought)")
    for label, pos in (("capital", 0), ("ENSO signal", 1), ("haze history", 2)):
        g = {}
        for s in range(N_STATES):
            att = STRUCTURES[int(Q[s].argmax())][0]
            g.setdefault(decode(s)[pos], []).append(6.0 if not np.isfinite(att) else att)
        spread = max(np.mean(v) for v in g.values()) - min(np.mean(v) for v in g.values())
        print(f"  {label:14s} spread {spread:.2f}   " + "  ".join(f"{k}={np.mean(v):.2f}" for k, v in g.items()))

    json.dump({"haze_model": coef, "expected_claims": env.EL, "premium": PREMIUM,
               "results": res, "policy": {str(s): STRUCTURE_NAMES[int(Q[s].argmax())]
                                          for s in range(N_STATES) if visits[s].sum() >= 50}},
              open(ROOT / "rl_reinsurance_results.json", "w"), indent=1)


if __name__ == "__main__":
    main()
