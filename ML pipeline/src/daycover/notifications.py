"""Phase 15: opt-in notifications with consent, duplicate prevention, delivery status and restart recovery.

Local simulation only. Payloads are labelled ``simulated``; no real SMS/push/soundbox is contacted and physical TTS/soundbox
checks belong to Part 1. This module never imports billing/settlement/evidence code and a notification can never authorise
money movement. Dry-year credit / partner rewards stay unpriced, unfunded proposals (see ``reward_proposal``).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from . import explanations as ex

CHANNELS = ("in_app", "soundbox_sim", "sms_sim")
MAX_ATTEMPTS = 3
STALE_SENDING_SECONDS = 300
DDL = """
CREATE TABLE IF NOT EXISTS consent_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, merchant_id TEXT NOT NULL, channel TEXT NOT NULL,
  language TEXT NOT NULL, opted_in INTEGER NOT NULL CHECK(opted_in IN (0,1)), actor_id TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, merchant_id TEXT NOT NULL, channel TEXT NOT NULL,
  language TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS delivery_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, notification_id TEXT NOT NULL REFERENCES notifications(id),
  state TEXT NOT NULL CHECK(state IN ('queued','sending','delivered_sim','failed_attempt','failed_final','suppressed_no_consent')),
  detail TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS c_nu BEFORE UPDATE ON consent_events BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS c_nd BEFORE DELETE ON consent_events BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS n_nu BEFORE UPDATE ON notifications BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS n_nd BEFORE DELETE ON notifications BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS e_nu BEFORE UPDATE ON delivery_events BEGIN SELECT RAISE(ABORT,'append-only'); END;
CREATE TRIGGER IF NOT EXISTS e_nd BEFORE DELETE ON delivery_events BEGIN SELECT RAISE(ABORT,'append-only'); END;
"""
_now = lambda: datetime.now(timezone.utc).isoformat()


def events_from_facts(f: dict) -> list[dict]:
    """Material, deduplicatable states only. Pending/unevaluated days are not pushed; they would be noise."""
    out = []
    for peril, p in f["perils"].items():
        if p["state"] in ("entitlement_recorded", "entitlement_under_review", "capped"):
            out.append({"kind": f"{peril}:{p['state']}", "day": f["as_of_day"], "amount_cents": p["amount_cents"]})
    pay, b = f["payment"], f["billing"]
    if pay["uncertain"]:
        out.append({"kind": "payment_uncertain", "day": f["as_of_day"], "amount_cents": pay["reserved_cents"]})
    if pay["confirmed_mock_cents"]:
        out.append({"kind": "mock_payment_confirmed", "day": f["as_of_day"], "amount_cents": pay["confirmed_mock_cents"]})
    if b["failed_attempt_cents"]:
        out.append({"kind": "billing_attempt_failed", "day": f["as_of_day"], "amount_cents": b["failed_attempt_cents"]})
    return out


class NotificationStore:
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as c:
            c.executescript(DDL)

    def _c(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    # -- consent: default is NO notifications; only the merchant's own principal can opt in; opt-out wins immediately
    def set_consent(self, merchant_id: str, channel: str, language: str, opted_in: bool, actor_id: str, actor_is_merchant: bool) -> None:
        if channel not in CHANNELS or language not in ex.LANGS:
            raise ValueError("unsupported channel or language")
        if opted_in and not actor_is_merchant:
            raise PermissionError("only the merchant can opt in")
        with self._c() as c:
            c.execute("INSERT INTO consent_events(merchant_id,channel,language,opted_in,actor_id,recorded_at) VALUES (?,?,?,?,?,?)",
                      (merchant_id, channel, language, int(opted_in), actor_id, _now()))

    def consent(self, merchant_id: str, channel: str) -> dict | None:
        with self._c() as c:
            r = c.execute("SELECT * FROM consent_events WHERE merchant_id=? AND channel=? ORDER BY sequence DESC LIMIT 1", (merchant_id, channel)).fetchone()
        return {"language": r["language"]} if r and r["opted_in"] else None

    def _log(self, c, nid, state, detail=""):
        c.execute("INSERT INTO delivery_events(notification_id,state,detail,recorded_at) VALUES (?,?,?,?)", (nid, state, detail, _now()))

    def status(self, nid: str) -> str:
        with self._c() as c:
            return c.execute("SELECT state FROM delivery_events WHERE notification_id=? ORDER BY sequence DESC LIMIT 1", (nid,)).fetchone()["state"]

    def deliveries(self, nid: str) -> list[dict]:
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM delivery_events WHERE notification_id=? ORDER BY sequence", (nid,))]

    def enqueue(self, merchant_id: str, snapshot: dict, channels=("in_app",)) -> list[str]:
        """Create at most one notification per merchant/channel/event/state. Without consent it records suppression only."""
        f = ex.facts(snapshot)
        ids = []
        for ev in events_from_facts(f):
            for ch in channels:
                cons = self.consent(merchant_id, ch)
                lang = cons["language"] if cons else "en"
                text = ex.render(f, lang)
                chk = ex.check_text(text["text"], f, text["claim_ids"], lang)
                if not chk["ok"]:
                    raise AssertionError("notification failed factual check")
                key = hashlib.sha256(f"{merchant_id}|{ch}|{ev['kind']}|{ev['day']}|{ev['amount_cents']}|{f['contract_sha256']}".encode()).hexdigest()
                nid = "NTF-" + key[:20]
                payload = {"simulated": True, "authorizes_payment": False, "kind": ev["kind"], "day": ev["day"], "amount_cents": ev["amount_cents"],
                           "language": lang, "translation_status": text["translation_status"], "text": text["text"] if cons else "",
                           "contract_version": f["contract_version"], "fixture_label": "SIMULATED_NOT_A_REAL_MESSAGE"}
                with self._c() as c:
                    cur = c.execute("INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?,?,?,?)",
                                    (nid, key, merchant_id, ch, lang, ev["kind"], json.dumps(payload, sort_keys=True, ensure_ascii=False), _now()))
                    if cur.rowcount:  # new notification
                        if cons:
                            self._log(c, nid, "queued")
                        else:
                            self._log(c, nid, "suppressed_no_consent", "no_opt_in")
                ids.append(nid)
        return ids

    def dispatch(self, sender, limit: int = 100, now_ts: float | None = None) -> dict:
        """sender(notification_id, payload, idempotency_key) -> True delivered / False failed. Bounded retries; no resend once delivered."""
        res = {"delivered": 0, "failed": 0, "final_failed": 0, "skipped": 0}
        with self._c() as c:
            rows = c.execute("SELECT n.id,n.payload,n.merchant_id,n.channel FROM notifications n WHERE (SELECT state FROM delivery_events e "
                             "WHERE e.notification_id=n.id ORDER BY sequence DESC LIMIT 1) IN ('queued','failed_attempt') LIMIT ?", (limit,)).fetchall()
        for r in rows:
            if not self.consent(r["merchant_id"], r["channel"]):  # opt-out after queuing is honoured
                with self._c() as c:
                    self._log(c, r["id"], "suppressed_no_consent", "opted_out_before_dispatch")
                res["skipped"] += 1
                continue
            with self._c() as c:
                attempts = c.execute("SELECT COUNT(*) n FROM delivery_events WHERE notification_id=? AND state='sending'", (r["id"],)).fetchone()["n"]
                if attempts >= MAX_ATTEMPTS:
                    self._log(c, r["id"], "failed_final", "max_attempts")
                    res["final_failed"] += 1
                    continue
                self._log(c, r["id"], "sending", f"attempt_{attempts + 1}")
            try:
                ok = bool(sender(r["id"], json.loads(r["payload"]), r["id"]))
            except Exception:  # sender crash is a failed attempt, not a lost notification
                ok = False
            with self._c() as c:
                self._log(c, r["id"], "delivered_sim" if ok else "failed_attempt", "" if ok else "sender_failed")
            res["delivered" if ok else "failed"] += 1
        return res

    def recover(self) -> int:
        """After a crash, a notification left in 'sending' becomes a failed attempt (resendable once, idempotency key unchanged)."""
        n = 0
        with self._c() as c:
            for r in c.execute("SELECT n.id FROM notifications n WHERE (SELECT state FROM delivery_events e WHERE e.notification_id=n.id "
                               "ORDER BY sequence DESC LIMIT 1)='sending'").fetchall():
                self._log(c, r["id"], "failed_attempt", "recovered_after_restart")
                n += 1
        return n


def reward_proposal(kind: str, credit_sgd: float, premium_sgd: float, p_no_claim_year: float, sponsor: str | None = None) -> dict:
    """Dry-year credit / partner reward as a priced but UNFUNDED, UNAPPROVED proposal. No sponsor naming or branding allowed."""
    if kind not in ("dry_year_credit", "partner_reward"):
        raise ValueError("unknown reward kind")
    if sponsor:
        raise ValueError("sponsor naming is not allowed until funding is approved")
    if not 0 <= p_no_claim_year <= 1 or credit_sgd < 0:
        raise ValueError("invalid pricing inputs")
    return {"kind": kind, "status": "proposal_unapproved", "funding": "unfunded", "sponsor": None, "credit_enabled": False,
            "expected_cost_per_policy_sgd": round(credit_sgd * p_no_claim_year, 2), "credit_sgd": credit_sgd,
            "premium_effect": "none: premium stays at the frozen contract price", "basis": "assumption_not_verified",
            "requires": ["separate pricing review", "funding source approval", "new contract version"]}
