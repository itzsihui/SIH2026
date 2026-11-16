"""Phase 13: advisory benefit-band recommendations. Never mutates a contract, term, price or entitlement.

* Digital sales only: normal earnings come from digital receipts; they are NOT total income, cash income or net income.
* Estimated loss uses labelled assumption scenarios (no verified weather response exists); uncertainty stays separate.
* The fixed-cover M1 default needs no transaction history/consent; refusing to share data is never penalised.
* Candidate bands are not registered contracts. ``application_check`` can only allow M1 or a registered, enrolable version.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import M1_VERSION
from .rules import RuleSet, haze_payout

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "recommendation-bands-v1.json"
SCHEMA = "daycover.recommendation.v1"


def load_config(path=CONFIG) -> dict:
    return json.loads(Path(path).read_text())


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def band_rules(band: dict) -> RuleSet:
    return replace(RuleSet(), version=band.get("registered_contract") or "candidate", **band["rules"])


def haze_year_payouts(psi: pd.DataFrame, region: str, rules: RuleSet, combined_cap: float | None = None) -> list[float]:
    """Exact annual haze payout per replayed calendar year under this band's trigger/cap rules (days + amount caps)."""
    s = psi[["date", region]].dropna().copy()
    s["date"] = pd.to_datetime(s["date"])
    s = s.sort_values("date")
    vals = dict(zip(s["date"], s[region]))
    out = []
    for y, g in s.groupby(s["date"].dt.year):
        if g["date"].nunique() < 300:   # incomplete years are skipped, never zero-filled
            continue
        days = paid = 0.0
        for d in g["date"]:
            tier, amt, _ = haze_payout(vals[d], vals.get(d - pd.Timedelta(days=1)), rules)
            if tier and days < rules.haze_cap_days_per_year and paid < rules.haze_cap_amount_per_year:
                pay = min(amt, rules.haze_cap_amount_per_year - paid)
                days += 1
                paid += pay
        out.append(paid)
    return out


def expected_payout(haze_years: list[float], rules: RuleSet, combined_cap: float, p_rain: float) -> float:
    """E[min(haze + rain, combined cap)] with rain paying at most once per term (rain cap 1 day) and independent of haze."""
    if not haze_years:
        raise ValueError("no complete haze replay years")
    h = np.array(haze_years)
    return float((1 - p_rain) * np.minimum(h, combined_cap).mean()
                 + p_rain * np.minimum(h + rules.rain_payout, combined_cap).mean())


def price_bands(cfg: dict, psi: pd.DataFrame, region: str) -> dict:
    a = cfg["assumptions"]
    ref = cfg["reference_annual_premium_cents"]
    res = {}
    for scen, p in a["rain_paying_year_probability"].items():
        base = None
        for bid, b in cfg["bands"].items():
            r = band_rules(b)
            ep = expected_payout(haze_year_payouts(psi, region, r), r, b["combined_cap_sgd"], p)
            if bid == "M1_FIXED":
                base = ep
            res.setdefault(bid, {})[scen] = {"expected_annual_payout_sgd": round(ep, 2)}
        for bid in cfg["bands"]:
            ep = res[bid][scen]["expected_annual_payout_sgd"]
            price = ref if bid == "M1_FIXED" else round(ref * ep / base) if base else None
            res[bid][scen]["indicative_annual_premium_cents"] = price
    return res


def earnings_profile(daily: pd.DataFrame, merchant_id: str, as_of: str, cfg: dict) -> dict | None:
    """Past-only observed digital days. Gaps are unknown, never zero. Returns None when history is insufficient."""
    a = cfg["assumptions"]
    d = daily[(daily.merchant_id == merchant_id) & (daily.trading_day < as_of)]
    lo = (pd.Timestamp(as_of) - pd.Timedelta(days=a["history_window_days"])).date().isoformat()
    d = d[d.trading_day >= lo]
    if len(d) < a["min_observed_days"]:
        return None
    q = np.quantile(d.digital_cents.to_numpy(float), [0.1, 0.5, 0.9])
    # observed-day rate scales to a year; unrecorded days are not assumed closed, so this is conservative for burden
    annual_days = len(d) / a["history_window_days"] * 365
    return {"observed_days": int(len(d)), "daily_digital_cents": {"p10": int(q[0]), "p50": int(q[1]), "p90": int(q[2])},
            "annual_digital_sales_cents": {k: int(v * annual_days) for k, v in zip(("low", "central", "high"), q)},
            "scope": "digital_sales_only_not_total_or_cash_or_net_income"}


def recommend(merchant_id: str, region: str, as_of: str, daily: pd.DataFrame, psi: pd.DataFrame, consent: bool,
              cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    a = cfg["assumptions"]
    prof = earnings_profile(daily, merchant_id, as_of, cfg) if consent else None
    pricing = price_bands(cfg, psi, region)
    out = {"schema_version": SCHEMA, "model_version": cfg["version"], "config_sha256": config_hash(cfg),
           "merchant_id": merchant_id, "as_of": as_of, "base_contract": cfg["reference_contract"],
           "consent_to_use_digital_sales": bool(consent), "advisory_only": True, "assumption_basis": a["basis"],
           "applies_to_existing_terms": False, "pricing_by_band": pricing, "earnings_profile": prof}
    fixed = {"band": "M1_FIXED", "mode": "fixed_cover_default", "reason": "no_consent" if not consent else "insufficient_digital_history",
             "penalty": False}
    if prof is None:
        out["recommendation"] = fixed
        return out
    central = "central"
    daily_gp = prof["daily_digital_cents"]["p50"] / 100 * a["margin_scenarios"]["central"]
    loss_day = daily_gp * a["assumed_weather_sales_drop"]["central"]
    rows = {}
    for bid, b in cfg["bands"].items():
        prem = pricing[bid][central]["indicative_annual_premium_cents"]
        burden = prem / max(prof["annual_digital_sales_cents"]["low"], 1)
        rows[bid] = {"premium_share_of_low_digital_sales": round(burden, 4),
                     "affordable": burden <= a["max_premium_share_of_low_digital_sales"],
                     "cushion_loss_days": round(b["combined_cap_sgd"] / loss_day, 2) if loss_day > 0 else None}
    out["affordability"] = rows
    out["normal_earnings_cents_per_day"] = prof["daily_digital_cents"]
    out["estimated_loss_per_weather_day_sgd"] = {  # assumption scenarios: separate from earnings and from uncertainty
        "basis": "assumption_not_verified",
        "range": {k: round(prof["daily_digital_cents"]["p50"] / 100 * a["margin_scenarios"][m] * a["assumed_weather_sales_drop"][d_], 2)
                  for k, (m, d_) in {"low": ("low", "low"), "central": ("central", "central"), "high": ("high", "high")}.items()}}
    ok = [(bid, r) for bid, r in rows.items() if r["affordable"]]
    target = a["target_cushion_loss_days"]
    meets = sorted([x for x in ok if (x[1]["cushion_loss_days"] or 0) >= target],
                   key=lambda x: pricing[x[0]][central]["indicative_annual_premium_cents"])
    if meets:
        pick, why = meets[0][0], "cheapest_affordable_band_meeting_cushion_target"
    elif ok:
        pick, why = max(ok, key=lambda x: x[1]["cushion_loss_days"] or 0)[0], "best_cushion_among_affordable_bands"
    else:
        out["recommendation"] = {**fixed, "reason": "no_band_passes_affordability_test_review_needed", "penalty": False}
        return out
    out["recommendation"] = {"band": pick, "mode": "data_informed", "reason": why, "penalty": False,
                             "registered_contract": cfg["bands"][pick]["registered_contract"]}
    return out


# ------------------------------------------------------------------ append-only decision record (separate store)

EVENTS = {"proposed": {"customer_accepted", "customer_declined", "withdrawn"},
          "customer_accepted": {"reviewer_approved", "reviewer_rejected", "withdrawn"},
          "customer_declined": set(), "reviewer_approved": {"withdrawn"}, "reviewer_rejected": set(), "withdrawn": set()}
ROLE = {"customer_accepted": "customer", "customer_declined": "customer", "withdrawn": "customer",
        "reviewer_approved": "reviewer", "reviewer_rejected": "reviewer"}
DDL = """
CREATE TABLE IF NOT EXISTS recommendations (id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, created_at TEXT NOT NULL,
  model_version TEXT NOT NULL, config_sha256 TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recommendation_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, recommendation_id TEXT NOT NULL
  REFERENCES recommendations(id), state TEXT NOT NULL, actor_id TEXT NOT NULL, actor_role TEXT NOT NULL, note TEXT NOT NULL,
  recorded_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS reco_no_update BEFORE UPDATE ON recommendations BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS reco_no_delete BEFORE DELETE ON recommendations BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS reco_ev_no_update BEFORE UPDATE ON recommendation_events BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS reco_ev_no_delete BEFORE DELETE ON recommendation_events BEGIN SELECT RAISE(ABORT,'append-only'); END;
"""


class RecommendationStore:
    """Separate advisory store (not the policy ledger). Records rationale, model version, choice and approval state."""

    def __init__(self, path):
        self.path = str(path)
        with self._c() as c:
            c.executescript(DDL)

    def _c(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def propose(self, rec: dict, now: str | None = None) -> str:
        if not rec.get("advisory_only") or rec.get("applies_to_existing_terms"):
            raise ValueError("only advisory, new-term recommendations can be recorded")
        payload = json.dumps(rec, sort_keys=True)
        rid = "RECO-" + hashlib.sha256((rec["merchant_id"] + rec["as_of"] + payload).encode()).hexdigest()[:20]
        now = now or datetime.now(timezone.utc).isoformat()
        with self._c() as c:
            c.execute("INSERT OR IGNORE INTO recommendations VALUES (?,?,?,?,?,?)",
                      (rid, rec["merchant_id"], now, rec["model_version"], rec["config_sha256"], payload))
            if not c.execute("SELECT 1 FROM recommendation_events WHERE recommendation_id=?", (rid,)).fetchone():
                c.execute("INSERT INTO recommendation_events(recommendation_id,state,actor_id,actor_role,note,recorded_at) "
                          "VALUES (?,?,?,?,?,?)", (rid, "proposed", "engine", "system", "advisory proposal", now))
        return rid

    def state(self, rid: str) -> str:
        with self._c() as c:
            r = c.execute("SELECT state FROM recommendation_events WHERE recommendation_id=? ORDER BY sequence DESC LIMIT 1", (rid,)).fetchone()
        if not r:
            raise KeyError(rid)
        return r["state"]

    def record(self, rid: str, state: str, actor_id: str, actor_role: str, note: str = "", merchant_id: str | None = None,
               now: str | None = None) -> None:
        cur = self.state(rid)
        if state not in EVENTS.get(cur, set()):
            raise ValueError(f"illegal transition {cur} -> {state}")
        if ROLE.get(state) != actor_role:
            raise PermissionError(f"{state} requires role {ROLE.get(state)}")
        with self._c() as c:
            owner = c.execute("SELECT merchant_id FROM recommendations WHERE id=?", (rid,)).fetchone()["merchant_id"]
            if actor_role == "customer" and merchant_id != owner:
                raise PermissionError("customer may act only on own recommendation")
            if state.startswith("reviewer_") and actor_id == owner:
                raise PermissionError("reviewer must be independent of the merchant")
            c.execute("INSERT INTO recommendation_events(recommendation_id,state,actor_id,actor_role,note,recorded_at) VALUES (?,?,?,?,?,?)",
                      (rid, state, actor_id, actor_role, note, now or datetime.now(timezone.utc).isoformat()))

    def history(self, rid: str) -> list[dict]:
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM recommendation_events WHERE recommendation_id=? ORDER BY sequence", (rid,))]

    def get(self, rid: str) -> dict:
        with self._c() as c:
            return json.loads(c.execute("SELECT payload FROM recommendations WHERE id=?", (rid,)).fetchone()["payload"])


def application_check(store: RecommendationStore, rid: str, effective_from: str, new_term_start: str, today: str,
                      registered: dict | None = None, existing_event_entitlement: bool = False) -> dict:
    """Read-only. Returns whether a decided recommendation could be offered on a NEW issue/renewal. Never writes."""
    from .contracts import catalogue  # read-only registry
    enrolable = registered if registered is not None else {c["version"] for c in catalogue() if c.get("simulation_enrolment_allowed")}
    rec = store.get(rid)
    band = rec["recommendation"]
    reasons = []
    if store.state(rid) != "reviewer_approved":
        reasons.append("not_customer_accepted_and_reviewer_approved")
    if existing_event_entitlement:
        reasons.append("existing_event_entitlements_cannot_change")
    if effective_from < new_term_start or effective_from < today:
        reasons.append("effective_date_must_be_a_future_new_issue_or_renewal_start")
    target = band.get("registered_contract")
    if not target:
        reasons.append("candidate_band_has_no_registered_contract_version")
    elif target not in enrolable:
        reasons.append("contract_version_not_enrolable")
    return {"may_offer_on_new_term": not reasons, "blocked_reasons": reasons, "mutates_active_contract": False,
            "target_contract": target}
