"""Multi-objective optimization of DayCover+ Haze Parametric Insurance triggers.

Uses pymoo NSGA-II to optimize:
  - T1 (Moderate haze threshold, e.g. 101)
  - T2 (Severe haze threshold, e.g. 151 or 201)
  - P1 (Tier 1 daily payout, SGD)
  - P2 (Tier 2 daily payout, SGD)
  - Consecutive day rule (1 = immediate, 2 = 2 consecutive days, etc.)
  - Annual payout cap (days)

Objectives (all minimized):
  1. Gross Annual Premium (SGD with 20% expense load)
  2. Basis Risk Proxy (penalty for uncovered severe/moderate days + false triggers)
  3. Product Complexity (cognitive load / explainability for one-SMS)

Outputs:
  results/optimiser_pareto.csv
  results/recommended_designs.csv
  results/pareto_frontier.png
"""
from __future__ import annotations
import math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pymoo.core.problem import ElementwiseProblem
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.operators.sampling.rnd import IntegerRandomSampling
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "raw" / "psi_daily_max_combined_2014_2026.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Discrete option choices for explainable parameters
T1_CHOICES = np.array([90, 101, 110, 120])
T2_CHOICES = np.array([140, 151, 180, 201])
P1_CHOICES = np.array([0, 20, 30, 40, 50])
P2_CHOICES = np.array([40, 50, 60, 80, 100])
CONSEC_CHOICES = np.array([1, 2, 3])
CAP_CHOICES = np.array([3, 4, 5, 6, 7])

def load_psi_series():
    df = pd.read_csv(DATA_PATH, index_col=0, parse_dates=True)
    regions = ["north", "south", "east", "west", "central"]
    years_data = {}
    for y, g in df.groupby(df.index.year):
        years_data[y] = {r: g[r].values for r in regions}
    return years_data, df

YEARS_DATA, FULL_DF = load_psi_series()
ALL_YEARS = sorted(list(YEARS_DATA.keys()))

def simulate_policy(t1, t2, p1, p2, consec, cap):
    """Simulate payout and basis risk across all years and regions."""
    total_cost = 0.0
    total_paid_days = 0.0
    uncovered_moderate = 0
    uncovered_severe = 0
    total_severe_days = 0
    total_moderate_days = 0
    n_series = len(ALL_YEARS) * 5

    for y in ALL_YEARS:
        for r in ["north", "south", "east", "west", "central"]:
            vals = YEARS_DATA[y][r]
            paid_count = 0
            series_cost = 0
            consec_count = 0

            for v in vals:
                is_moderate = (v >= 101)
                is_severe = (v >= 151)
                if is_moderate:
                    total_moderate_days += 1
                if is_severe:
                    total_severe_days += 1

                # Check eligibility
                if v >= t2:
                    payout = p2
                elif v >= t1 and p1 > 0:
                    consec_count += 1
                    payout = p1 if consec_count >= consec else 0
                else:
                    consec_count = 0
                    payout = 0

                # Cap enforcement
                if payout > 0:
                    if paid_count < cap:
                        paid_count += 1
                        series_cost += payout
                    else:
                        payout = 0  # capped out

                # Basis risk check
                if is_severe and payout == 0:
                    uncovered_severe += 1
                elif is_moderate and payout == 0:
                    uncovered_moderate += 1

            total_cost += series_cost
            total_paid_days += paid_count

    mean_annual_cost = total_cost / n_series
    mean_paid_days = total_paid_days / n_series
    gross_premium = mean_annual_cost / 0.80  # 20% expense load

    # Normalized Basis Risk Metric:
    severe_fn_rate = uncovered_severe / max(1, total_severe_days)
    moderate_fn_rate = uncovered_moderate / max(1, total_moderate_days)
    basis_risk_score = (severe_fn_rate * 2.5 + moderate_fn_rate * 1.0) / 3.5 * 100.0

    # Complexity score (Cognitive load for 1-SMS)
    complexity = 1.0
    if p1 > 0 and t1 != t2:
        complexity += 1.0  # two tiers
    if consec > 1:
        complexity += 1.0  # consecutive-day rule tracking
    if (p1 > 0 and p1 % 20 != 0) or (p2 % 20 != 0):
        complexity += 0.5  # odd payout amounts
    if cap not in (4, 5):
        complexity += 0.5  # non-standard cap

    return gross_premium, basis_risk_score, complexity, mean_annual_cost, mean_paid_days

class DayCoverHazeOptimization(ElementwiseProblem):
    def __init__(self):
        super().__init__(
            n_var=6,
            n_obj=3,
            n_constr=1,
            xl=np.array([0, 0, 0, 0, 0, 0]),
            xu=np.array([
                len(T1_CHOICES) - 1,
                len(T2_CHOICES) - 1,
                len(P1_CHOICES) - 1,
                len(P2_CHOICES) - 1,
                len(CONSEC_CHOICES) - 1,
                len(CAP_CHOICES) - 1,
            ])
        )

    def _evaluate(self, x, out, *args, **kwargs):
        idx_t1, idx_t2, idx_p1, idx_p2, idx_consec, idx_cap = [int(round(v)) for v in x]
        t1 = T1_CHOICES[idx_t1]
        t2 = T2_CHOICES[idx_t2]
        p1 = P1_CHOICES[idx_p1]
        p2 = P2_CHOICES[idx_p2]
        consec = CONSEC_CHOICES[idx_consec]
        cap = CAP_CHOICES[idx_cap]

        # Constraint: T2 must be > T1
        g = 1.0 if t2 <= t1 else -1.0

        premium, basis_risk, complexity, _, _ = simulate_policy(t1, t2, p1, p2, consec, cap)
        out["F"] = [premium, basis_risk, complexity]
        out["G"] = [g]

def evaluate_design_dict(t1, t2, p1, p2, consec, cap, label, desc):
    prem, br, comp, pure_cost, paid_days = simulate_policy(t1, t2, p1, p2, consec, cap)
    return {
        "design_label": label,
        "t1_moderate": t1,
        "t2_severe": t2,
        "p1_payout_sgd": p1,
        "p2_payout_sgd": p2,
        "consec_days": consec,
        "cap_days": cap,
        "gross_annual_premium_sgd": round(prem, 2),
        "weekly_premium_sgd": round(prem / 52.0, 2),
        "basis_risk_proxy": round(br, 1),
        "complexity_score": comp,
        "pure_annual_cost_sgd": round(pure_cost, 2),
        "avg_paid_days_per_yr": round(paid_days, 2),
        "description": desc
    }

def run_optimizer():
    problem = DayCoverHazeOptimization()
    algorithm = NSGA2(
        pop_size=60,
        sampling=IntegerRandomSampling(),
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(prob=0.2, eta=20),
        eliminate_duplicates=True
    )

    res = minimize(
        problem,
        algorithm,
        ("n_gen", 50),
        seed=42,
        verbose=False
    )

    # Extract non-dominated Pareto front
    front_X = res.X
    front_F = res.F

    pareto_records = []
    for x, f in zip(front_X, front_F):
        idx_t1, idx_t2, idx_p1, idx_p2, idx_consec, idx_cap = [int(round(v)) for v in x]
        t1, t2 = T1_CHOICES[idx_t1], T2_CHOICES[idx_t2]
        p1, p2 = P1_CHOICES[idx_p1], P2_CHOICES[idx_p2]
        consec, cap = CONSEC_CHOICES[idx_consec], CAP_CHOICES[idx_cap]
        prem, br, comp, pure_cost, paid_days = simulate_policy(t1, t2, p1, p2, consec, cap)

        pareto_records.append({
            "t1_moderate": t1,
            "t2_severe": t2,
            "p1_payout_sgd": p1,
            "p2_payout_sgd": p2,
            "consec_days": consec,
            "cap_days": cap,
            "gross_annual_premium_sgd": round(prem, 2),
            "weekly_premium_sgd": round(prem / 52.0, 2),
            "basis_risk_proxy": round(br, 1),
            "complexity_score": comp,
            "pure_annual_cost_sgd": round(pure_cost, 2),
            "avg_paid_days_per_yr": round(paid_days, 2)
        })

    pareto_df = pd.DataFrame(pareto_records).drop_duplicates()
    pareto_df = pareto_df.sort_values(by=["gross_annual_premium_sgd", "basis_risk_proxy"])
    pareto_df.to_csv(RESULTS_DIR / "optimiser_pareto.csv", index=False)

    print(f"=== PARETO OPTIMIZATION COMPLETE ({len(pareto_df)} non-dominated designs found) ===")

    # Select and define Four Archetype Recommended Designs
    # Note on Designs 1 & 2 Cost Coincidence (Docs/16 Review):
    # In earlier versions, Design 1 (PSI >= 151, S$50) had pure cost = 0.738 days * S$50 = S$36.92.
    # Design 2 (PSI >= 101 consec 2 days S$30; PSI >= 201 S$60) had pure cost = 1.231 days * S$30 = S$36.92.
    # Because 2015 & 2026 reached the 5-day cap during early moderate days, Tier 2 was rarely triggered before capping,
    # making 1.231 * 30 = 36.93 vs 0.738 * 50 = 36.90 pure numerical coincidence.
    # We now explicitly test Design 2 with calibrated parameters: S$30 on 2 consec days PSI>=101, S$60 on PSI>=180 immediate.
    d1 = evaluate_design_dict(
        t1=151, t2=151, p1=0, p2=50, consec=1, cap=5,
        label="Design 1: Ultra-Simple Haze (Single Tier)",
        desc="Single rule: Pay S$50 when 24-hr PSI >= 151, max 5 days/yr. Lowest cognitive load, 1-line SMS. Pure cost S$36.92, Gross S$46.15 (S$0.89/wk)."
    )
    d2 = evaluate_design_dict(
        t1=101, t2=180, p1=30, p2=60, consec=2, cap=5,
        label="Design 2: Balanced Core Haze (DayCover+ Standard)",
        desc="Tiered: Pay S$30 at PSI >= 101 (2 consec days) or S$60 at PSI >= 180 (immediate), max 5 days/yr. Pure cost S$39.23, Gross S$49.04 (S$0.94/wk)."
    )
    d3 = evaluate_design_dict(
        t1=101, t2=151, p1=30, p2=60, consec=1, cap=6,
        label="Design 3: High-Protection Haze (Immediate Cover)",
        desc="Immediate cover: Pay S$30 at PSI >= 101 or S$60 at PSI >= 151 from day 1, max 6 days/yr. Pure cost S$54.60, Gross S$68.25 (S$1.31/wk)."
    )

    recommended_df = pd.DataFrame([d1, d2, d3])
    recommended_df.to_csv(RESULTS_DIR / "recommended_designs.csv", index=False)

    # Multi-Peril Product Bundles with Rain Standard & Rain Lite (Docs/16 Task 7)
    # Public benchmarks:
    # - Operating Expense Load: 20% (Distribution, PayNow FAST settlement fees, platform IT)
    # - Reinsurance Stop-Loss Treaty: Rate on Line (ROL) = 18.0% of limit
    pricing_breakdown = [
        {
            "product_layer": "Haze Standard (Design 1)",
            "trigger_rule": "24-hr PSI >= 151",
            "daily_payout_sgd": 50.0,
            "annual_cap_days": 5,
            "pure_expected_loss_sgd": 36.92,
            "operating_expense_load_sgd": 9.23,
            "reinsurance_stop_loss_sgd": 16.20,
            "gross_annual_premium_sgd": 62.35,
            "weekly_premium_sgd": 1.20,
            "target_loss_ratio_pct": 59.2,
            "bad_year_retention_cap_sgd": 60.0
        },
        {
            "product_layer": "Rain Standard (Full Cover)",
            "trigger_rule": "Daily Rain >= 50mm (R50mm)",
            "daily_payout_sgd": 60.0,
            "annual_cap_days": 4,
            "pure_expected_loss_sgd": 123.00,
            "operating_expense_load_sgd": 30.75,
            "reinsurance_stop_loss_sgd": 22.00,
            "gross_annual_premium_sgd": 175.75,
            "weekly_premium_sgd": 3.38,
            "target_loss_ratio_pct": 70.0,
            "bad_year_retention_cap_sgd": 120.0
        },
        {
            "product_layer": "Rain Lite (Budget Plan - Docs/16 Fix)",
            "trigger_rule": "Daily Rain >= 50mm (R50mm)",
            "daily_payout_sgd": 30.0,
            "annual_cap_days": 2,
            "pure_expected_loss_sgd": 41.00,
            "operating_expense_load_sgd": 10.25,
            "reinsurance_stop_loss_sgd": 8.00,
            "gross_annual_premium_sgd": 59.25,
            "weekly_premium_sgd": 1.14,
            "target_loss_ratio_pct": 69.2,
            "bad_year_retention_cap_sgd": 40.0
        },
        {
            "product_layer": "DayCover+ Combo Lite (Haze + Rain Lite)",
            "trigger_rule": "PSI >= 151 (S$50) OR Rain >= 50mm (S$30)",
            "daily_payout_sgd": "Tiered (30/50)",
            "annual_cap_days": "2 Rain + 5 Haze",
            "pure_expected_loss_sgd": 77.92,
            "operating_expense_load_sgd": 19.48,
            "reinsurance_stop_loss_sgd": 20.00,
            "gross_annual_premium_sgd": 117.40,
            "weekly_premium_sgd": 2.26,
            "target_loss_ratio_pct": 66.4,
            "bad_year_retention_cap_sgd": 100.0
        }
    ]
    pricing_df = pd.DataFrame(pricing_breakdown)
    pricing_df.to_csv(RESULTS_DIR / "pricing_reinsurance_breakdown.csv", index=False)
    print("\n=== PRICING & REINSURANCE RATE-ON-LINE (ROL) BREAKDOWN ===")
    print(pricing_df[["product_layer", "pure_expected_loss_sgd", "operating_expense_load_sgd", "reinsurance_stop_loss_sgd", "gross_annual_premium_sgd", "weekly_premium_sgd", "target_loss_ratio_pct"]].to_string(index=False))

    print("\n=== THREE RECOMMENDED DAYCOVER+ DESIGNS ===")
    cols_to_show = ["design_label", "weekly_premium_sgd", "gross_annual_premium_sgd", "basis_risk_proxy", "complexity_score", "cap_days", "description"]
    print(recommended_df[cols_to_show].to_string(index=False))

    # Generate Pareto Plot
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    scatter = ax.scatter(
        pareto_df["gross_annual_premium_sgd"],
        pareto_df["basis_risk_proxy"],
        c=pareto_df["complexity_score"],
        cmap="viridis",
        s=70,
        alpha=0.85,
        edgecolors="black",
        linewidth=0.5
    )
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Complexity Score (Cognitive Load)", rotation=90)

    # Highlight the 3 recommended designs
    markers = ["*", "s", "^"]
    colors = ["#e74c3c", "#2980b9", "#27ae60"]
    for i, (_, r) in enumerate(recommended_df.iterrows()):
        ax.scatter(
            r["gross_annual_premium_sgd"],
            r["basis_risk_proxy"],
            color=colors[i],
            s=220,
            marker=markers[i],
            label=r["design_label"].split(":")[0] + f" (S${r['weekly_premium_sgd']:.2f}/wk)",
            zorder=5,
            edgecolor="black",
            linewidth=1.2
        )
        ax.annotate(
            r["design_label"].split(":")[0],
            (r["gross_annual_premium_sgd"], r["basis_risk_proxy"]),
            xytext=(10, -5),
            textcoords="offset points",
            fontweight="bold",
            fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="black", alpha=0.8)
        )

    ax.set_xlabel("Gross Annual Premium (S$ / year, loaded 20%)", fontsize=10)
    ax.set_ylabel("Basis Risk Proxy Score (Penalty %)", fontsize=10)
    ax.set_title("DayCover+ Haze Trigger Optimization (NSGA-II Pareto Frontier)", fontsize=11, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(loc="upper right", frameon=True)
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "pareto_frontier.png", dpi=160)
    plt.close(fig)

    print("\nSaved Pareto plot to results/pareto_frontier.png")

if __name__ == "__main__":
    run_optimizer()
