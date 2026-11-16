"""Signed outbound bridge: deliver an already-queued mock settlement instruction to the Part 1 app backend sandbox.

Contract: https://daycover-pay.vercel.app/docs/ENGINE_CONTRACT.md. POST /api/engine/payouts, header X-Engine-Signature =
hex HMAC-SHA256(ENGINE_SHARED_SECRET, "instruction_id|stall_id|gross_cents|currency|event_id"), idempotent on instruction_id.

Safety model
* OFF by default: needs DAYCOVER_APP_WALLET_BRIDGE=1 AND ENGINE_SHARED_SECRET. The secret is read from the environment only and never
  stored, logged, audited or returned.
* The engine's mock settlement state machine stays the authority. The bridge only DELIVERS an instruction that the settlement module
  currently deems eligible (current authority, reviewed recipient). Its delivery record is separate: the app's answer is unsigned, so
  it is never used to mark an entitlement confirmed or to change any balance here.
* Durable intent is audited before the POST; timeouts/errors are 'uncertain' and retried with the SAME instruction_id (no double pay).
* The payload carries only whitelisted fields (no merchant identity, no free text) plus the centre NAME the app asked for.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import date

from . import auth, policy_lifecycle as life, settlement
from .ledger_repository import configured_repository
from .weather_ingestion import iso, utcnow

DEFAULT_URL = "https://daycover-pay.vercel.app"
MAX_ATTEMPTS = 5
ATTEMPT, RESULT = "app_wallet_attempt", "app_wallet_result"
STATUSES = {"settled", "rejected"}


class BridgeDisabled(ValueError):
    pass


def enabled() -> bool:
    return os.getenv("DAYCOVER_APP_WALLET_BRIDGE") == "1" and bool(os.getenv("ENGINE_SHARED_SECRET"))


def canonical(p: dict) -> str:
    return "|".join(str(p[k]) for k in ("instruction_id", "stall_id", "gross_cents", "currency", "event_id"))


def sign(secret: str, p: dict) -> str:
    return hmac.new(secret.encode(), canonical(p).encode(), hashlib.sha256).hexdigest()


def _stall_map() -> dict:
    raw = os.getenv("DAYCOVER_APP_STALL_MAP")  # optional JSON {engine_stall_id: app_stall_id}
    return json.loads(raw) if raw else {}


def centre_name(c, stall: str) -> str | None:
    from .identity_api import CENTRES
    if stall in CENTRES:
        return CENTRES[stall].centre
    row = c.execute("SELECT centre_ref FROM auth_onboarding WHERE stall_id=?", (stall,)).fetchone()
    return CENTRES[row["centre_ref"]].centre if row and row["centre_ref"] in CENTRES else None


def _reading(decision: dict) -> str:
    ev = decision.get("evidence", {})
    if decision["peril"] == "haze" and ev.get("psi_today") is not None:
        return f"PSI {int(float(ev['psi_today']))}"
    if decision["peril"] == "rain" and ev.get("rain_mm") is not None:
        return f"{float(ev['rain_mm']):g} mm"
    return decision["peril"]


def build_payload(c, stall: str, instruction: dict) -> dict:
    cents = int(instruction["amount_cents"])
    if not 1 <= cents <= 20000:
        raise ValueError("amount outside the app contract range (1-20000 cents)")
    if instruction["peril"] not in ("rain", "haze"):
        raise ValueError("unsupported peril")
    name = centre_name(c, stall)
    if not name:
        raise ValueError("centre name unavailable; the app maps stalls by centre name")
    decision = json.loads(instruction["authority"])["decision"]
    day = instruction["day"]
    date.fromisoformat(day)
    return {"instruction_id": instruction["id"], "stall_id": _stall_map().get(stall, stall), "gross_cents": cents, "currency": "SGD",
            "event_id": f"EV-{instruction['peril'].upper()}-{day}", "peril": instruction["peril"], "reading": _reading(decision),
            "event_date": day, "centre_name": name}


def _history(c, policy_id: str, iid: str) -> list[dict]:
    rows = c.execute("SELECT action,details,recorded_at FROM pilot_audit WHERE policy_id=? AND action IN (?,?) ORDER BY recorded_at,id", (policy_id, ATTEMPT, RESULT)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["details"])
        if d.get("instruction_id") == iid:
            out.append({"action": r["action"], **d, "recorded_at": r["recorded_at"]})
    return out


def delivery_status(stall: str, term_id: str, instruction_id: str, repository=None) -> dict:
    with (repository or configured_repository()).transaction() as c:
        p = life.term_context(c, stall, term_id=term_id)
        settlement._instruction(c, p, instruction_id)
        h = _history(c, p["id"], instruction_id)
    results = [x for x in h if x["action"] == RESULT]
    return {"instruction_id": instruction_id, "attempts": sum(1 for x in h if x["action"] == ATTEMPT),
            "latest": results[-1] if results else None, "delivered": any(x["status"] == "settled" for x in results),
            "app_sandbox_only": True, "engine_confirmation_changed": False, "real_transfer": False}


def _httpx_post(url, headers, body: bytes, timeout):
    import httpx  # the only outbound HTTP in the engine; used solely by this bridge
    r = httpx.post(url, content=body, headers=headers, timeout=timeout)
    try:
        data = r.json()
    except ValueError:
        data = None
    return r.status_code, data


def deliver(stall: str, term_id: str, instruction_id: str, actor, repository=None, *, post=None, now=None) -> dict:
    if not enabled():
        raise BridgeDisabled("App wallet bridge is disabled (set DAYCOVER_APP_WALLET_BRIDGE=1 and ENGINE_SHARED_SECRET).")
    auth.require_scope(actor, "settlement:submit")
    repo, now, post = repository or configured_repository(), now or utcnow(), post or _httpx_post
    with repo.transaction() as c:
        auth.stall_access(c, actor, stall)
        p = life.term_context(c, stall, term_id=term_id)
        ins = settlement._instruction(c, p, instruction_id)
        if settlement._state(c, ins)["status"] == "canceled_unsent":
            raise ValueError("Instruction was canceled before dispatch.")
        reason = settlement._eligibility(c, p, ins, now)
        if reason:
            raise ValueError("Instruction is not currently eligible: " + reason)
        h = _history(c, p["id"], instruction_id)
        done = [x for x in h if x["action"] == RESULT and x["status"] == "settled"]
        if done:
            return {**delivery_status_from(h, instruction_id), "duplicate_prevented_locally": True}
        n = sum(1 for x in h if x["action"] == ATTEMPT)
        if n >= MAX_ATTEMPTS:
            raise ValueError("Delivery attempt limit reached; operator review required.")
        payload = build_payload(c, stall, dict(ins))
        c.audit(p["id"], ATTEMPT, {"instruction_id": instruction_id, "attempt": n + 1, "stall_id": payload["stall_id"],
                                   "centre_name": payload["centre_name"], "gross_cents": payload["gross_cents"], "event_id": payload["event_id"]}, iso(utcnow()))
    url = os.getenv("DAYCOVER_APP_WALLET_URL", DEFAULT_URL).rstrip("/") + "/api/engine/payouts"
    headers = {"Content-Type": "application/json", "X-Engine-Signature": sign(os.environ["ENGINE_SHARED_SECRET"], payload)}
    try:
        status_code, data = post(url, headers, json.dumps(payload, separators=(",", ":")).encode(), 10)
    except Exception:  # timeout/connect/other: outcome unknown, never assume success or failure
        status_code, data = None, None
    outcome = _interpret(payload, status_code, data)
    with repo.transaction() as c:
        c.audit(p["id"], RESULT, {"instruction_id": instruction_id, "http_status": status_code, **outcome}, iso(utcnow()))
        h = _history(c, p["id"], instruction_id)
    return delivery_status_from(h, instruction_id)


def delivery_status_from(h, iid):
    results = [x for x in h if x["action"] == RESULT]
    return {"instruction_id": iid, "attempts": sum(1 for x in h if x["action"] == ATTEMPT), "latest": results[-1] if results else None,
            "delivered": any(x["status"] == "settled" for x in results), "app_sandbox_only": True,
            "engine_confirmation_changed": False, "real_transfer": False}


def _interpret(sent: dict, code, data) -> dict:
    """Map the app's unsigned answer to a delivery status. It never affects engine balances."""
    if code is None:
        return {"status": "uncertain", "reason": "no_response_retry_same_instruction_id"}
    if code == 401:
        return {"status": "failed", "reason": "app_rejected_signature_check_secret_configuration"}
    if code == 404:
        return {"status": "failed", "reason": "app_unknown_stall_check_centre_mapping"}
    if code == 400:
        return {"status": "failed", "reason": "app_rejected_body"}
    if code == 503:
        return {"status": "uncertain", "reason": "app_secret_not_configured"}
    if code != 200 or not isinstance(data, dict):
        return {"status": "uncertain", "reason": f"unexpected_http_{code}"}
    amount = data.get("amount")
    consistent = (data.get("instruction_id") == sent["instruction_id"] and isinstance(amount, (int, float))
                  and round(float(amount) * 100) == sent["gross_cents"] and data.get("currency", "SGD") == "SGD")
    status = data.get("status")
    if not consistent or status not in STATUSES:
        return {"status": "response_mismatch", "reason": "app_response_differs_from_instruction"}
    ref = data.get("provider_ref")
    return {"status": status, "duplicate": bool(data.get("duplicate")), "provider_ref": ref if isinstance(ref, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", ref) else None,
            "amount_cents": sent["gross_cents"]}
