"""Phase 14: protection-quality metrics, stress replays and portfolio/capital scenarios (research only).

Nothing here executes a rule, price or payout. Existing claims always use the frozen contract. Designs other than M1 are
labelled research candidates that share identical trigger data and assumptions; their own profit/premium estimates
(e.g. Plan 4's S$87) are never transplanted. Capital/reinsurance/expense/collection numbers are scenarios, not quotes,
and no output guarantees solvency. Synthetic merchant data cannot measure real income basis risk.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import M1_SHA256, M1_VERSION, get_contract
from .rules import RuleSet, haze_payout

SCHEMA = "daycover.protection-research.v1"
REGIONS = ("north", "south", "east", "west", "central")

DESIGNS = {  # identical trigger data; differences are explicit
    "M1_180": {"label": "frozen M1 (S$180 combined)", "rules": {}, "combined_cap_sgd": 180.0, "executable": True},
    "ALT_150_M1_TRIGGERS": {"label": "research: M1 triggers, S$30 rain + S$120 haze, S$150 combined",
                            "rules": {"haze_cap_amount_per_year": 120.0}, "combined_cap_sgd": 150.0, "executable": False},
    "PLAN4_STYLE_150": {"label": "research: severe PSI 201, S$120 haze, S$150 combined (not the branch's full rules)",
                        "rules": {"haze_tier2_psi": 201, "haze_cap_amount_per_year": 120.0}, "combined_cap_sgd": 150.0,
                        "executable": False},
}
ASSUMPTIONS = {
    "basis": "assumption_not_verified",
    "reference_premium_sgd": 104.0,
    "rain_paying_year_probability": {"low": 0.05, "central": 0.15, "high": 0.30},
    "rain_correlation": {"independent_hit_share": None, "clustered_hit_share": 0.6},
    "expense_ratio_of_collected_premium": 0.25,
    "collection_failure_share": {"none": 0.0, "moderate": 0.05, "severe": 0.15},
    "reinsurance": {"attach_multiple_of_gross_premium": 1.5, "limit_multiple_of_gross_premium": 2.0,
                    "ceded_premium_sgd_per_policy": 15.0, "note": "S$10-20 range in docs/41; not a treaty quote"},
    "portfolio_policies": 1000, "simulations": 20000, "seed": 20261116,
    "premium_collection": "12 monthly instalments from policy start month 1",
    "rain_claim_month": "uniform across months (no verified rain-event timing)",
}


def design_rules(name: str) -> tuple[RuleSet, float]:
    d = DESIGNS[name]
    return replace(RuleSet(), version=name, **d["rules"]), d["combined_cap_sgd"]


def haze_events(psi: pd.DataFrame, region: str, rules: RuleSet, min_days: int = 360) -> dict[int, list[tuple[str, float]]]:
    """Paid haze events per complete calendar year under exact trigger/cap rules. Incomplete years are skipped."""
    s = psi[["date", region]].dropna().copy()
    s["date"] = pd.to_datetime(s["date"])
    vals = dict(zip(s["date"], s[region]))
    out = {}
    for y, g in s.groupby(s["date"].dt.year):
        if len(g) < min_days:
            continue
        days, paid, ev = 0, 0.0, []
        for d in sorted(g["date"]):
            tier, amt, _ = haze_payout(vals[d], vals.get(d - pd.Timedelta(days=1)), rules)
            if tier and days < rules.haze_cap_days_per_year and paid < rules.haze_cap_amount_per_year:
                pay = min(amt, rules.haze_cap_amount_per_year - paid)
                days += 1
                paid += pay
                ev.append((d.date().isoformat(), pay))
        out[int(y)] = ev
    return out


def year_table(psi: pd.DataFrame, rules: RuleSet) -> pd.DataFrame:
    rows = {r: {y: sum(a for _, a in ev) for y, ev in haze_events(psi, r, rules).items()} for r in REGIONS}
    return pd.DataFrame(rows)  # index = year, columns = region


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


# -------------------------------------------------------------------------------- protection quality (measured)

def protection_quality(f: pd.DataFrame, psi_long: pd.DataFrame, rules: RuleSet, margin: float = 0.45, drop: float = 0.30) -> dict:
    """Haze-trigger quality against measured digital-sales disruption. Observed digital days only; rain excluded
    because no merchant-to-gauge mapping exists. Disruption = sales <= (1-drop) x past-only expected sales."""
    p = psi_long.copy()
    p["next_day"] = (pd.to_datetime(p["trading_day"]) + pd.Timedelta(days=1)).dt.date.astype(str)
    prev = p[["next_day", "psi_region", "psi"]].rename(columns={"next_day": "trading_day", "psi": "prev_psi"})
    g = f.merge(prev, on=["trading_day", "psi_region"], how="left")
    g = g[g.rolling_pred.notna() & g.psi.notna() & g.prev_psi.notna()].copy()
    res = [haze_payout(a, b, rules) for a, b in zip(g.psi, g.prev_psi)]
    g["trigger"] = [r[0] > 0 for r in res]
    g["payout"] = [r[1] for r in res]
    g["disrupted"] = g.digital_cents <= (1 - drop) * g.rolling_pred
    n, t, dis = len(g), int(g.trigger.sum()), int(g.disrupted.sum())
    tp = int((g.trigger & g.disrupted).sum())
    est_loss = (g.rolling_pred - g.digital_cents).clip(lower=0) / 100 * margin
    tr = g[g.trigger]
    out = {"rows": n, "trigger_days": t, "disrupted_days": dis, "trigger_and_disrupted": tp,
           "paid_without_measured_disruption": t - tp, "missed_disruption_days": int((~g.trigger & g.disrupted).sum()),
           "p_disruption_given_trigger": None if t == 0 else round(tp / t, 4), "p_disruption_given_trigger_ci95": wilson(tp, t),
           "p_disruption_given_no_trigger": round(float((~g.trigger & g.disrupted).sum() / max((~g.trigger).sum(), 1)), 4),
           "base_rate_disruption": round(dis / n, 4) if n else None,
           "payout_sgd_on_trigger_days": float(tr.payout.sum()),
           "estimated_gross_profit_loss_sgd_on_trigger_days": round(float(est_loss[g.trigger].sum()), 2),
           "payout_to_estimated_loss": (None if est_loss[g.trigger].sum() <= 0
                                        else round(float(tr.payout.sum() / est_loss[g.trigger].sum()), 3)),
           "margin_assumption": margin, "disruption_definition": f"digital sales <= {1 - drop:.0%} of past-only expected",
           "low_power": t < 30,
           "caveats": ["observed digital days only: closed/outage/zero days are invisible so missed disruption is a lower bound",
                       "disruption is not attributed to weather; synthetic data has no verified weather response",
                       "single-day trigger flag ignores annual caps; rain excluded (no gauge mapping)"]}
    return out


def gauge_disagreement(rain: pd.DataFrame, stations: pd.DataFrame, radius_km: float = 5.0, mm: float = 70.0) -> dict:
    """Gauge-to-gauge trigger disagreement within the fallback radius. This is NOT income basis risk."""
    r = rain[rain["is_valid_day"].astype(str).str.lower() == "true"][["date", "station_id", "daily_rainfall_mm"]]
    s = stations.set_index("id")
    ids = [i for i in s.index if i in set(r.station_id)]
    lat, lon = np.radians(s.loc[ids, "latitude"].to_numpy()), np.radians(s.loc[ids, "longitude"].to_numpy())
    dist = 6371 * 2 * np.arcsin(np.sqrt(np.sin((lat[:, None] - lat[None]) / 2) ** 2 +
                                        np.cos(lat[:, None]) * np.cos(lat[None]) * np.sin((lon[:, None] - lon[None]) / 2) ** 2))
    piv = r.pivot_table(index="date", columns="station_id", values="daily_rainfall_mm")
    a_hit = both = pairs = pair_days = 0
    for i in range(len(ids)):
        for j in range(len(ids)):
            if i != j and dist[i, j] <= radius_km and ids[i] in piv and ids[j] in piv:
                x = piv[[ids[i], ids[j]]].dropna()
                pairs += 1
                pair_days += len(x)
                a = x.iloc[:, 0] >= mm
                a_hit += int(a.sum())
                both += int((a & (x.iloc[:, 1] >= mm)).sum())
    return {"radius_km": radius_km, "ordered_pairs": pairs, "pair_days": pair_days, "trigger_days_at_A": a_hit,
            "B_also_triggers": both, "p_B_given_A": None if a_hit == 0 else round(both / a_hit, 4),
            "p_B_given_A_ci95": wilson(both, a_hit),
            "caveat": "sampled non-exhaustive dates; ordered pairs/days are not independent so the CI is optimistic; gauge disagreement only, no income link"}


# -------------------------------------------------------------------------------- stress replays

def sparse_psi_stress(psi: pd.DataFrame, rules: RuleSet, shares=(0.05, 0.2, 0.4), seed: int = 1) -> dict:
    """Randomly blank PSI readings. Missing readings are pending (not paid and not zero-filled); report the shortfall."""
    full = year_table(psi, rules)
    out = {"full_data_mean_annual_haze_sgd": round(float(full.to_numpy().mean()), 2)}
    rng = np.random.default_rng(seed)
    for sh in shares:
        q = psi.copy()
        for r in REGIONS:
            q.loc[rng.random(len(q)) < sh, r] = np.nan
        miss_today = int((q[list(REGIONS)].isna().to_numpy() & ~psi[list(REGIONS)].isna().to_numpy()).sum())
        # years with too few readings are skipped by haze_events, so evaluate with a relaxed completeness bar
        ev = {r: haze_events(q, r, rules, min_days=int(360 * (1 - sh) * 0.9)) for r in REGIONS}
        mean = float(np.mean([sum(a for _, a in e) for r in REGIONS for e in ev[r].values()] or [0]))
        out[f"missing_{int(sh * 100)}pct"] = {"blank_readings": miss_today, "mean_annual_haze_sgd": round(mean, 2),
                                             "shortfall_vs_full": round(out["full_data_mean_annual_haze_sgd"] - mean, 2)}
    out["treatment"] = "missing = pending/unassessed, never filled; shortfall shows delayed/unpaid triggers until source correction"
    return out


def _monthly_claims(events_by_region_year: dict, year: int, region: str, rain_month: int | None, rules: RuleSet, combined: float):
    ev = sorted([(d, a, "haze") for d, a in events_by_region_year[region].get(year, [])])
    if rain_month:
        ev.append((f"{year}-{rain_month:02d}-15", rules.rain_payout, "rain"))
    ev.sort()
    rem, m = combined, np.zeros(12)
    for d, a, _ in ev:
        pay = min(a, rem)
        rem -= pay
        m[int(d[5:7]) - 1] += pay
    return m


def liquidity_year(psi: pd.DataFrame, name: str, year: int, premium: float, policies: int, collection_failure: float,
                   rain_month: int = 10) -> dict:
    """Monthly cash profile per policy for one replayed year: premiums in 12 instalments vs dated claims (all-region average)."""
    rules, combined = design_rules(name)
    evs = {r: haze_events(psi, r, rules) for r in REGIONS}
    claims = np.mean([_monthly_claims(evs, year, r, rain_month, rules, combined) for r in REGIONS], axis=0) * policies
    prem = np.full(12, premium * policies * (1 - collection_failure) / 12)
    cum = np.cumsum(prem - claims)
    return {"year": year, "rain_month_assumed": rain_month, "annual_claims_sgd": round(float(claims.sum()), 2),
            "annual_premium_collected_sgd": round(float(prem.sum()), 2), "peak_cumulative_deficit_sgd": round(float(max(0, -cum.min())), 2),
            "worst_month_claims_sgd": round(float(claims.max()), 2), "month_of_peak_deficit": int(np.argmin(cum)) + 1}


def portfolio(psi: pd.DataFrame, name: str, premium: float, p_rain: float, hit_share: float | None, fail: float, a=ASSUMPTIONS) -> dict:
    """Seeded Monte Carlo over replayed haze years (cross-region correlation retained) and a rain scenario."""
    rules, combined = design_rules(name)
    tab = year_table(psi, rules)
    years = tab.index.to_numpy()
    N = a["portfolio_policies"]
    nreg = np.full(5, N // 5)
    rng = np.random.default_rng(a["seed"])
    S = a["simulations"]
    yi = rng.integers(0, len(years), S)
    h = tab.to_numpy()[yi]                                  # S x 5 haze payout per policy
    if hit_share is None:                                   # independent: every year, each policy hit with p_rain
        wet, hs = np.ones(S, bool), p_rain
    else:                                                   # clustered: wet years hit hit_share of policies
        wet, hs = rng.random(S) < min(1.0, p_rain / hit_share), hit_share
    k = np.where(wet[:, None], rng.binomial(nreg[None, :], hs, size=(S, 5)), 0)
    base, hit = np.minimum(h, combined), np.minimum(h + rules.rain_payout, combined)
    claims = ((nreg[None, :] - k) * base + k * hit).sum(1)
    gross = premium * N
    collected = gross * (1 - fail)
    expense = a["expense_ratio_of_collected_premium"] * collected
    ri = a["reinsurance"]
    attach, limit = ri["attach_multiple_of_gross_premium"] * gross, ri["limit_multiple_of_gross_premium"] * gross
    recovery = np.clip(claims - attach, 0, limit)
    ceded = ri["ceded_premium_sgd_per_policy"] * N
    net_gross = collected - expense - claims
    net_ri = collected - expense - ceded - (claims - recovery)
    q = lambda x, p: round(float(np.quantile(x, p)), 2)
    top_region = (tab.to_numpy() * nreg[None, :]).max(1) / np.maximum((tab.to_numpy() * nreg[None, :]).sum(1), 1e-9)
    return {"design": name, "premium_sgd": premium, "p_rain": p_rain, "rain_mode": "independent" if hit_share is None else f"clustered_{hit_share}",
            "collection_failure": fail, "gross_premium_sgd": gross, "mean_claims_sgd": round(float(claims.mean()), 2),
            "claims_p95_sgd": q(claims, .95), "claims_p99_sgd": q(claims, .99), "claims_max_sgd": round(float(claims.max()), 2),
            "loss_ratio_mean": round(float(claims.mean() / gross), 3), "prob_net_negative_no_reinsurance": round(float((net_gross < 0).mean()), 4),
            "prob_net_negative_with_reinsurance": round(float((net_ri < 0).mean()), 4),
            "net_result_p01_no_reinsurance_sgd": q(net_gross, .01), "net_result_p01_with_reinsurance_sgd": q(net_ri, .01),
            "residual_retained_claims_p99_sgd": q(claims - recovery, .99),
            "max_single_region_share_of_haze_claims": round(float(top_region.max()), 3),
            "replay_years": [int(y) for y in years], "solvency_guarantee": False}


def max_liability_case(name: str, premium: float, fail: float, a=ASSUMPTIONS) -> dict:
    """Beyond-history stress: every policy exhausts its combined cap in one year (replay never reaches this)."""
    _, combined = design_rules(name)
    N, ri = a["portfolio_policies"], a["reinsurance"]
    gross = premium * N
    collected = gross * (1 - fail)
    claims = combined * N
    rec = min(max(claims - ri["attach_multiple_of_gross_premium"] * gross, 0), ri["limit_multiple_of_gross_premium"] * gross)
    exp = a["expense_ratio_of_collected_premium"] * collected
    return {"design": name, "claims_sgd": claims, "reinsurance_recovery_sgd": round(rec, 2),
            "net_without_reinsurance_sgd": round(collected - exp - claims, 2),
            "net_with_reinsurance_sgd": round(collected - exp - ri["ceded_premium_sgd_per_policy"] * N - (claims - rec), 2),
            "scenario": "all policies hit combined cap; not a probability statement"}


def compare_designs(psi: pd.DataFrame, a=ASSUMPTIONS) -> dict:
    out = {"identical_premium_view": [], "scaled_premium_view": [],
           "max_liability_case": [max_liability_case(n, a["reference_premium_sgd"], 0.05, a) for n in DESIGNS]}
    pr = a["rain_paying_year_probability"]
    ref = a["reference_premium_sgd"]
    tabs = {n: year_table(psi, design_rules(n)[0]) for n in DESIGNS}
    def ep(n, p):
        t, cap = tabs[n].to_numpy(), DESIGNS[n]["combined_cap_sgd"]
        return float((1 - p) * np.minimum(t, cap).mean() + p * np.minimum(t + 30.0, cap).mean())
    exp = {n: {s: ep(n, p) for s, p in pr.items()} for n in tabs}
    out["expected_annual_payout_per_policy_sgd"] = {n: {s: round(v, 2) for s, v in d.items()} for n, d in exp.items()}
    for n in DESIGNS:
        for s, p in pr.items():
            for mode, hs in (("independent", None), ("clustered", a["rain_correlation"]["clustered_hit_share"])):
                for fail in a["collection_failure_share"].values():
                    out["identical_premium_view"].append(portfolio(psi, n, ref, p, hs, fail, a) | {"rain_scenario": s})
        scaled = round(ref * exp[n]["central"] / exp["M1_180"]["central"], 2)
        out["scaled_premium_view"].append(portfolio(psi, n, scaled, pr["central"], a["rain_correlation"]["clustered_hit_share"], 0.05, a)
                                          | {"rain_scenario": "central"})
    return out


# -------------------------------------------------------------------------------- advisory proposal record

DDL = """
CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, source TEXT NOT NULL, design TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposal_decisions (sequence INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL REFERENCES proposals(id),
  decision TEXT NOT NULL CHECK(decision IN ('approved_for_future_version','rejected','deferred')), reviewer_id TEXT NOT NULL,
  future_version TEXT, note TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS p_nu BEFORE UPDATE ON proposals BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS p_nd BEFORE DELETE ON proposals BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS d_nu BEFORE UPDATE ON proposal_decisions BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS d_nd BEFORE DELETE ON proposal_decisions BEGIN SELECT RAISE(ABORT,'append-only'); END;
"""


class ProposalStore:
    """Optimiser/research proposals with evidence and reviewer decisions. Recording a decision changes no rule or price."""

    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as c:
            c.executescript(DDL)

    def propose(self, source: str, design: str, evidence: dict, now: str | None = None) -> str:
        if source not in {"optimiser", "research", "human"}:
            raise ValueError("unknown source")
        payload = json.dumps({"design": design, "evidence": evidence, "authority": "advisory",
                              "base_contract_sha256": M1_SHA256}, sort_keys=True)
        ev = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        pid = "PROP-" + hashlib.sha256((source + design + ev).encode()).hexdigest()[:16]
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR IGNORE INTO proposals VALUES (?,?,?,?,?,?)",
                      (pid, now or datetime.now(timezone.utc).isoformat(), source, design, ev, payload))
        return pid

    def decide(self, pid: str, decision: str, reviewer_id: str, note: str, future_version: str | None = None) -> None:
        if decision == "approved_for_future_version":
            if not future_version or future_version == M1_VERSION:
                raise ValueError("approval must name a NEW future contract version; existing versions cannot change")
        with sqlite3.connect(self.path) as c:
            if not c.execute("SELECT 1 FROM proposals WHERE id=?", (pid,)).fetchone():
                raise KeyError(pid)
            c.execute("INSERT INTO proposal_decisions(proposal_id,decision,reviewer_id,future_version,note,recorded_at) VALUES (?,?,?,?,?,?)",
                      (pid, decision, reviewer_id, future_version, note, datetime.now(timezone.utc).isoformat()))

    def decisions(self, pid: str) -> list[dict]:
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute("SELECT * FROM proposal_decisions WHERE proposal_id=? ORDER BY sequence", (pid,))]


def run(receipts, source_files, psi_path, rain_path, stations_path, out_dir) -> dict:
    from .income_baseline import BaselineConfig, IncomeBaseline, daily_digital, load_receipts
    from .weather_impact import build_frame, island_rain, merchant_meta, psi_long
    psi = pd.read_csv(psi_path)
    daily = daily_digital(load_receipts(receipts))
    model = IncomeBaseline(BaselineConfig()).fit(daily)
    pl = psi_long(psi_path)
    f = build_frame(daily, model, merchant_meta(source_files), pl, island_rain(rain_path))
    f = f[f.split.isin(["validation", "test"]) | ((f.split == "merchant_holdout") & (f.trading_day >= "2025-09-01"))]
    rain = pd.read_csv(rain_path)
    rep = {"schema_version": SCHEMA, "m1_contract_sha256": get_contract(M1_VERSION).sha256, "m1_unchanged": get_contract(M1_VERSION).sha256 == M1_SHA256,
           "assumptions": ASSUMPTIONS, "designs": {k: {x: v[x] for x in ("label", "combined_cap_sgd", "executable")} for k, v in DESIGNS.items()},
           "psi_sha256": hashlib.sha256(Path(psi_path).read_bytes()).hexdigest(), "provenance_for_merchant_metrics": "calibrated_synthetic_only",
           "protection_quality_m1_haze": protection_quality(f, pl, design_rules("M1_180")[0]),
           "gauge_disagreement": gauge_disagreement(rain, pd.read_csv(stations_path)),
           "haze_replay_by_year": {n: year_table(psi, design_rules(n)[0]).round(1).to_dict(orient="index") for n in DESIGNS},
           "sparse_data_stress_m1": sparse_psi_stress(psi, design_rules("M1_180")[0]),
           "liquidity_worst_year": {n: liquidity_year(psi, n, int(year_table(psi, design_rules(n)[0]).sum(1).idxmax()), 104.0, 1000, 0.05)
                                    for n in DESIGNS},
           "design_comparison": compare_designs(psi),
           "limitations": ["calendar-year replay, not policy-year", "rain frequency/timing are scenarios (non-exhaustive sample)",
                           "expenses, collection, treaty are assumptions not quotes", "no solvency or profitability claim",
                           "no real loss labels; merchant disruption metric is not weather attributed"]}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "protection_research_report.json").write_text(json.dumps(rep, indent=1, sort_keys=True, default=str))
    return rep
