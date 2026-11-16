"""Mock transaction-linked premium collection: four-week schedule, weekly cap, accrual vs confirmed funds.

Four distinct amounts are kept apart: contractual premium owed, scheduled instalment, accrued contributions (authorised, not
yet money) and mock-CONFIRMED receipts. Digital sales only; cash and unconsented events never accrue. This is a collection
method over the issued premium, never a premium change, and it never touches claim decisions. All events are simulated.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

CONFIG = json.loads((Path(__file__).resolve().parents[2] / "configs" / "collection-v1.json").read_text())
def schedule(start: date, annual_cents: int, cfg: dict = CONFIG) -> dict:
    n, wpc = cfg["cycles_per_year"], cfg["weeks_per_cycle"]
    base, extra = divmod(annual_cents, n)
    cycles = [{"index": i, "start": str(date.fromordinal(start.toordinal() + i * 7 * wpc)),
               "end": str(date.fromordinal(start.toordinal() + (i + 1) * 7 * wpc - 1)),
               "instalment_cents": base + (1 if i >= n - extra else 0)} for i in range(n)]  # remainder lands on the last cycles
    return {"annual_cents": annual_cents, "cycles": cycles, "weekly_cap_cents": math.ceil(annual_cents / 52),
            "sum_check": sum(c["instalment_cents"] for c in cycles)}


def _now():
    return datetime.now(timezone.utc).isoformat()


class AccrualStore:
    """Append-only mock collection ledger inside the canonical ledger (schema v8): same SQLite/PostgreSQL backends and backups."""

    def __init__(self, repository):
        self.repo = repository

    def _c(self):
        return self.repo.transaction()

    @staticmethod
    def _lock(c, term_key):
        if c.backend == "postgres":  # serialise concurrent caps/confirmations for one term (SQLite is already serialised)
            c.execute("SELECT pg_advisory_xact_lock(hashtext(?))", ("collection:" + term_key,))

    def _sum(self, c, term_key, kinds, **where):
        q = f"SELECT COALESCE(SUM(amount_cents),0) AS s FROM collection_accrual_entries WHERE term_key=? AND kind IN ({','.join('?' * len(kinds))})"
        args = [term_key, *kinds]
        for k, v in where.items():
            q += f" AND {k}=?"
            args.append(v)
        return int(c.execute(q, args).fetchone()["s"])

    def _ignore(self, c, term_key, txn, reason):
        sha = hashlib.sha256(json.dumps({k: txn.get(k) for k in ("provider_event_id", "kind")}, sort_keys=True).encode()).hexdigest()
        c.execute("INSERT INTO collection_ignored_events(term_key,event_sha256,reason,recorded_at) VALUES (?,?,?,?) ON CONFLICT DO NOTHING", (term_key, sha, reason, _now()))
        return {"outcome": "ignored", "reason": reason, "accrued_cents": 0}

    def ingest(self, term_key: str, start: date, end: date, annual_cents: int, txn: dict, consent: bool, cfg: dict = CONFIG) -> dict:
        """Process one simulated transaction event. Idempotent by provider_event_id. Returns the accrual outcome."""
        for k in ("provider_event_id", "kind", "channel", "timestamp_sgt", "amount_cents"):
            if k not in txn:
                raise ValueError(f"missing {k}")
        if txn["kind"] not in ("sale", "refund") or not isinstance(txn["amount_cents"], int) or txn["amount_cents"] <= 0:
            raise ValueError("invalid transaction")
        day = datetime.fromisoformat(txn["timestamp_sgt"]).date()
        sched = schedule(start, annual_cents, cfg)
        with self._c() as c:
            self._lock(c, term_key)
            if not consent:
                return self._ignore(c, term_key, txn, "no_consent")
            if txn["channel"] not in cfg["digital_channels"]:
                return self._ignore(c, term_key, txn, "cash_or_unlisted_channel_excluded")
            if not (start <= day <= end):
                return self._ignore(c, term_key, txn, "outside_policy_term")
            eid = txn["provider_event_id"]
            dup = c.execute("SELECT amount_cents,reason FROM collection_accrual_entries WHERE term_key=? AND kind IN ('accrual','accrual_reversal') AND event_id=?",
                            (term_key, eid)).fetchone()
            if dup:
                return {"outcome": "duplicate", "accrued_cents": dup["amount_cents"], "reason": dup["reason"]}
            week = (day - start).days // 7
            cycle = min(week // cfg["weeks_per_cycle"], cfg["cycles_per_year"] - 1)
            if txn["kind"] == "refund":
                orig = c.execute("SELECT * FROM collection_accrual_entries WHERE term_key=? AND kind='accrual' AND event_id=?", (term_key, txn.get("original_event_id"))).fetchone()
                if not orig:
                    return self._ignore(c, term_key, txn, "refund_without_known_original")
                already = -self._sum(c, term_key, ["accrual_reversal"], ref_event_id=orig["event_id"])
                rev = min(orig["amount_cents"] - already, orig["amount_cents"] * min(txn["amount_cents"], orig["txn_amount_cents"]) // max(orig["txn_amount_cents"], 1))
                rev = max(rev, 0)
                c.execute("INSERT INTO collection_accrual_entries(term_key,kind,event_id,ref_event_id,week_index,cycle_index,amount_cents,txn_amount_cents,reason,recorded_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?)", (term_key, "accrual_reversal", eid, orig["event_id"], orig["week_index"], orig["cycle_index"], -rev,
                                                          txn["amount_cents"], "refund_reverses_accrual", _now()))
                return {"outcome": "reversed", "accrued_cents": -rev}
            want = txn["amount_cents"] * cfg["contribution_bps"] // 10000
            wk_room = sched["weekly_cap_cents"] - self._sum(c, term_key, ["accrual", "accrual_reversal"], week_index=week)
            cy_room = sched["cycles"][min(cycle, len(sched["cycles"]) - 1)]["instalment_cents"] - self._sum(c, term_key, ["accrual", "accrual_reversal"], cycle_index=cycle)
            yr_room = annual_cents - self._sum(c, term_key, ["accrual", "accrual_reversal"])
            got = max(0, min(want, wk_room, cy_room, yr_room))
            reason = "full" if got == want else "weekly_cap" if got == max(0, wk_room) else "cycle_instalment" if got == max(0, cy_room) else "annual_premium"
            c.execute("INSERT INTO collection_accrual_entries(term_key,kind,event_id,ref_event_id,week_index,cycle_index,amount_cents,txn_amount_cents,reason,recorded_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)", (term_key, "accrual", eid, None, week, cycle, got, txn["amount_cents"], reason, _now()))
            return {"outcome": "accrued", "accrued_cents": got, "wanted_cents": want, "limited_by": None if got == want else reason,
                    "week_index": week, "cycle_index": cycle}

    def confirm(self, term_key: str, cycle_index: int, amount_cents: int, provider_ref: str, reverse: bool = False) -> dict:
        """Mock settlement receipt. Confirmed funds can never exceed accrued (net) funds for that cycle."""
        with self._c() as c:
            self._lock(c, term_key)
            kind = "confirmation_reversal" if reverse else "confirmation"
            if c.execute("SELECT 1 FROM collection_accrual_entries WHERE term_key=? AND kind=? AND event_id=?", (term_key, kind, provider_ref)).fetchone():
                return {"outcome": "duplicate"}
            accrued = self._sum(c, term_key, ["accrual", "accrual_reversal"], cycle_index=cycle_index)
            confirmed = self._sum(c, term_key, ["confirmation", "confirmation_reversal"], cycle_index=cycle_index)
            if reverse:
                if amount_cents > confirmed:
                    raise ValueError("cannot reverse more than confirmed")
                signed = -amount_cents
            else:
                if amount_cents <= 0 or confirmed + amount_cents > accrued:
                    raise ValueError("confirmation exceeds accrued contributions for the cycle")
                signed = amount_cents
            c.execute("INSERT INTO collection_accrual_entries(term_key,kind,event_id,ref_event_id,week_index,cycle_index,amount_cents,reason,recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (term_key, kind, provider_ref, None, cycle_index * CONFIG["weeks_per_cycle"], cycle_index, signed, "mock_receipt", _now()))
            return {"outcome": "confirmed" if not reverse else "reversed", "confirmed_cents": signed}

    def summary(self, term_key: str, start: date, annual_cents: int, as_of: date, cfg: dict = CONFIG) -> dict:
        sched = schedule(start, annual_cents, cfg)
        week = max(0, (as_of - start).days // 7)
        cur = min(week // cfg["weeks_per_cycle"], len(sched["cycles"]) - 1)
        with self._c() as c:
            cycles = []
            for cy in sched["cycles"]:
                a = self._sum(c, term_key, ["accrual", "accrual_reversal"], cycle_index=cy["index"])
                k = self._sum(c, term_key, ["confirmation", "confirmation_reversal"], cycle_index=cy["index"])
                ended = as_of > date.fromisoformat(cy["end"])
                cycles.append({**cy, "accrued_cents": a, "confirmed_cents": k, "unconfirmed_accrual_cents": a - k,
                               "shortfall_cents": max(0, cy["instalment_cents"] - k) if ended else None, "ended": ended})
            wk = self._sum(c, term_key, ["accrual", "accrual_reversal"], week_index=week)
            tot_a = self._sum(c, term_key, ["accrual", "accrual_reversal"])
            tot_k = self._sum(c, term_key, ["confirmation", "confirmation_reversal"])
            ign = c.execute("SELECT reason,COUNT(*) AS n FROM collection_ignored_events WHERE term_key=? GROUP BY reason", (term_key,)).fetchall()
        return {"method": cfg["method"], "simulated": True, "partner_integration": False, "real_collected_cents": 0,
                "contractual_premium_owed_cents": annual_cents, "scheduled_instalment_this_cycle_cents": sched["cycles"][cur]["instalment_cents"],
                "accrued_cents": tot_a, "confirmed_collected_cents": tot_k, "unpaid_balance_cents": annual_cents - tot_k,
                "arrears_cents": sum(x["shortfall_cents"] or 0 for x in cycles),
                "current_week": {"index": week, "accrued_cents": wk, "cap_cents": sched["weekly_cap_cents"], "remaining_cents": max(0, sched["weekly_cap_cents"] - wk)},
                "cycles": cycles, "ignored": {r["reason"]: r["n"] for r in ign},
                "alternatives": "No transaction history or consent is required: use the fixed monthly (mock) GIRO billing schedule.",
                "explanation": "Accrued contributions are not money received; only mock-confirmed receipts count as collected. Shortfalls follow the arrears/true-up route."}


def suggest_weekly_cap(summary: dict, annual_cents: int, consent: bool, cfg: dict = CONFIG) -> dict:
    """Advisory collection pacing from a consented DIGITAL-sales summary. It never changes premium owed, benefits or claims.

    Fixed fallback = ceil(annual/52). With consent and enough observed days the cap may rise up to 2x the base when the hawker's
    digital sales support it (1.5% of average weekly digital sales); it never falls below the base, so the premium stays collectable.
    """
    base = math.ceil(annual_cents / 52)
    r = cfg["suggested_cap"]
    if not consent:
        return {"weekly_cap_cents": base, "mode": "fixed_fallback", "reason": "no_consent", "base_cents": base, **_NOTE}
    if summary["days_observed"] < r["min_days_observed"]:
        return {"weekly_cap_cents": base, "mode": "fixed_fallback", "reason": "insufficient_digital_history", "base_cents": base, **_NOTE}
    raw = round(summary["avg_week_cents"] * r["share_of_avg_week_digital_sales"])
    cap = max(base, min(raw, r["max_multiple_of_base"] * base))
    return {"weekly_cap_cents": cap, "mode": "data_informed", "reason": "within_digital_sales_band" if cap == raw else "clamped_to_band",
            "base_cents": base, "digital_sales_basis_cents_per_week": summary["avg_week_cents"], **_NOTE}


_NOTE = {"advisory": True, "affects_premium_owed": False, "affects_claims": False, "scope": "digital_sales_only_not_total_or_cash_income"}
