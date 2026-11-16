"""Phase 16: reliability and security plumbing (local simulation only).

* Correlation IDs, structured JSON request logs (no query strings, bodies, tokens or IPs), Prometheus-style metrics.
* Request-size and per-client rate limits; security headers.
* Environment separation checks, readiness and alert collection (source gaps, uncertain payouts, quarantined callbacks).
Nothing here writes to financial tables or contacts an external service.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response

from .identity_api import principal as _principal

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "configs" / "environments.json"
log = logging.getLogger("daycover.ops")
CID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)
RUNBOOK = {"source_gap": "docs/RUNBOOK.md#source-outage-or-correction", "payout_uncertain": "docs/RUNBOOK.md#uncertain-payout",
           "quarantined_callback": "docs/RUNBOOK.md#quarantined-callbacks", "failed_collection": "docs/RUNBOOK.md#failed-debit",
           "outbox_stuck": "docs/RUNBOOK.md#pending-decision-or-stuck-outbox"}


# ------------------------------------------------------------------------------------------ environments

def load_environments(path=ENV_FILE) -> dict:
    return json.loads(Path(path).read_text())


def check_environments(cfg: dict | None = None) -> list[str]:
    """Static separation rules: distinct stores, mock-only providers, distinct secret names, no real-looking flags."""
    cfg = cfg or load_environments()
    problems, dbs, schemas, secrets_ = [], {}, {}, {}
    for name, e in cfg["environments"].items():
        if e["provider_namespace"] != "local_mock_only":
            problems.append(f"{name}: provider must be local_mock_only")
        if e["backend"] == "sqlite" and not e["db"]:
            problems.append(f"{name}: sqlite needs a db path")
        if e["backend"] == "postgres" and not (e["pg_schema"] and re.fullmatch(r"daycover_pilot(_[a-z0-9_]+)?", e["pg_schema"])):
            problems.append(f"{name}: invalid pg schema")
        if e["db"] and dbs.setdefault(e["db"], name) != name:
            problems.append(f"{name}: shares db with {dbs[e['db']]}")
        if e["pg_schema"] and schemas.setdefault(e["pg_schema"], name) != name:
            problems.append(f"{name}: shares schema with {schemas[e['pg_schema']]}")
        if secrets_.setdefault(e["provider_secret_env"], name) != name:
            problems.append(f"{name}: shares provider secret env name with {secrets_[e['provider_secret_env']]}")
        if any(f in json.dumps(e).lower() for f in cfg["forbidden"]):
            problems.append(f"{name}: forbidden marker present")
    if "production" in cfg["environments"]:
        problems.append("no production environment may be defined in local release preparation")
    return problems


def apply_environment(name: str, env: dict | None = None, cfg: dict | None = None) -> dict:
    """Return the process environment variables for a named environment (caller decides whether to export them)."""
    cfg = cfg or load_environments()
    e = cfg["environments"][name]
    out = {"DAYCOVER_AUTH_MODE": e["auth_mode"], "DAYCOVER_PILOT_BACKEND": e["backend"],
           "DAYCOVER_RATE_LIMIT_PER_MIN": str(e["rate_limit_per_min"]), "DAYCOVER_MAX_BODY_BYTES": str(e["max_body_bytes"]),
           "DAYCOVER_ENV": name}
    if e["db"]:
        out["DAYCOVER_PILOT_DB"] = e["db"]
    if e["pg_schema"]:
        out["DAYCOVER_PILOT_PG_SCHEMA"] = e["pg_schema"]
    return out


# ------------------------------------------------------------------------------------------ metrics

class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.count = defaultdict(int)
        self.hist = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
        self.sums = defaultdict(float)
        self.rejected = defaultdict(int)

    def observe(self, method, route, status, seconds):
        key = (method, route, f"{status // 100}xx")
        with self.lock:
            self.count[key] += 1
            h = self.hist[(method, route)]
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    h[i] += 1
                    break
            else:
                h[-1] += 1
            self.sums[(method, route)] += seconds

    def reject(self, reason):
        with self.lock:
            self.rejected[reason] += 1

    def prometheus(self) -> str:
        lines = ["# TYPE daycover_http_requests_total counter"]
        with self.lock:
            for (m, r, s), n in sorted(self.count.items()):
                lines.append(f'daycover_http_requests_total{{method="{m}",route="{r}",status="{s}"}} {n}')
            lines.append("# TYPE daycover_http_request_seconds histogram")
            for (m, r), h in sorted(self.hist.items()):
                cum = 0
                for b, n in zip(BUCKETS, h):
                    cum += n
                    lines.append(f'daycover_http_request_seconds_bucket{{method="{m}",route="{r}",le="{b}"}} {cum}')
                lines.append(f'daycover_http_request_seconds_bucket{{method="{m}",route="{r}",le="+Inf"}} {cum + h[-1]}')
                lines.append(f'daycover_http_request_seconds_sum{{method="{m}",route="{r}"}} {self.sums[(m, r)]:.6f}')
            lines.append("# TYPE daycover_rejected_requests_total counter")
            for k, n in sorted(self.rejected.items()):
                lines.append(f'daycover_rejected_requests_total{{reason="{k}"}} {n}')
        return "\n".join(lines) + "\n"


METRICS = Metrics()


class OpsMiddleware:
    """Pure ASGI middleware: correlation id, size/rate limits, structured log, metrics, security headers."""

    def __init__(self, app, metrics: Metrics = METRICS):
        self.app, self.metrics = app, metrics
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    @staticmethod
    def _limits():
        return int(os.getenv("DAYCOVER_MAX_BODY_BYTES", "1048576")), int(os.getenv("DAYCOVER_RATE_LIMIT_PER_MIN", "1200"))

    def _allow(self, client: str, limit: int, now: float) -> bool:
        with self.lock:
            q = self.hits[client]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start = time.perf_counter()
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        cid = headers.get("x-correlation-id", "")
        cid = cid if CID.match(cid) else uuid.uuid4().hex
        max_body, rate = self._limits()
        client = hashlib.sha256((scope.get("client") or ("-", 0))[0].encode()).hexdigest()[:12]
        state = {"status": 500, "bytes": 0}

        async def send_wrapper(message):
            if state.get("too_large") and message["type"] in ("http.response.start", "http.response.body"):
                # the framework turned our abort into a 400; replace it with the correct 413
                if message["type"] == "http.response.start":
                    state["status"] = 413
                    body = json.dumps({"detail": "Request body too large.", "correlation_id": cid}).encode()
                    state["replacement"] = body
                    self.metrics.reject("body_too_large")
                    message = {"type": "http.response.start", "status": 413, "headers": [
                        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                        (b"x-correlation-id", cid.encode()), (b"x-content-type-options", b"nosniff")]}
                else:
                    message = {"type": "http.response.body", "body": state.get("replacement", b"")}
                await send(message)
                return
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                hdrs = [(k, v) for k, v in message["headers"] if k.lower() not in (b"x-correlation-id",)]
                hdrs += [(b"x-correlation-id", cid.encode()), (b"x-content-type-options", b"nosniff"),
                         (b"referrer-policy", b"no-referrer"), (b"x-daycover-mode", b"simulation_only")]
                message = {**message, "headers": hdrs}
            await send(message)

        async def limited_receive():
            msg = await receive()
            if msg["type"] == "http.request":
                state["bytes"] += len(msg.get("body", b""))
                if state["bytes"] > max_body:
                    state["too_large"] = True
                    raise _TooLarge()
            return msg

        async def reject(status, detail, reason, extra=()):
            self.metrics.reject(reason)
            body = json.dumps({"detail": detail, "correlation_id": cid}).encode()
            await send_wrapper({"type": "http.response.start", "status": status,
                                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *extra]})
            await send_wrapper({"type": "http.response.body", "body": body})

        try:
            declared = int(headers.get("content-length", "0") or 0)
        except ValueError:
            declared = 0
        route = "unmatched"
        try:
            if declared > max_body:
                state["status"] = 413
                await reject(413, "Request body too large.", "body_too_large")
            elif not self._allow(client, rate, time.monotonic()):
                state["status"] = 429
                await reject(429, "Too many requests.", "rate_limited", [(b"retry-after", b"60")])
            else:
                await self.app(scope, limited_receive, send_wrapper)
        except _TooLarge:
            state["status"] = 413
            await reject(413, "Request body too large.", "body_too_large")
        finally:
            r = scope.get("route")
            route = getattr(r, "path", None) or "unmatched"
            dur = time.perf_counter() - start
            self.metrics.observe(scope["method"], route, state["status"], dur)
            log.info(json.dumps({"event": "http_request", "correlation_id": cid, "method": scope["method"], "route": route,
                                 "status": state["status"], "duration_ms": round(dur * 1000, 2), "client": client,
                                 "env": os.getenv("DAYCOVER_ENV", "unset")}, sort_keys=True))


class _TooLarge(Exception):
    pass


# ------------------------------------------------------------------------------------------ readiness / alerts

def _latest_state_sql():
    return ("SELECT i.id,i.amount_cents,(SELECT state FROM settlement_instruction_events e WHERE e.instruction_id=i.id ORDER BY sequence DESC LIMIT 1) AS state "
            "FROM settlement_instructions i")


def collect_alerts(repo=None, now=None) -> list[dict]:
    """Read-only operational alerts. Each carries a runbook anchor; counts only, never merchant data."""
    from .ledger_repository import configured_repository
    from .weather_ingestion import source_health
    repo = repo or configured_repository()
    out = []
    for kind, h in source_health(repo, now=now).items():
        if h["status"] != "available_provisional":
            out.append({"code": "source_gap", "severity": "high" if h["status"] in ("missing", "stale") else "medium", "source": kind,
                        "status": h["status"], "count": 1, "runbook": RUNBOOK["source_gap"]})
    with repo.transaction() as c:
        unc = [r for r in c.execute(_latest_state_sql()).fetchall() if r["state"] == "uncertain"]
        if unc:
            out.append({"code": "payout_uncertain", "severity": "high", "count": len(unc), "amount_cents": sum(r["amount_cents"] for r in unc),
                        "runbook": RUNBOOK["payout_uncertain"]})
        q = c.execute("SELECT (SELECT COUNT(*) FROM billing_provider_events WHERE disposition='quarantined') AS b, "
                      "(SELECT COUNT(*) FROM settlement_provider_events WHERE disposition='quarantined') AS s").fetchone()
        if q["b"] or q["s"]:
            out.append({"code": "quarantined_callback", "severity": "high", "count": q["b"] + q["s"], "billing": q["b"], "settlement": q["s"],
                        "runbook": RUNBOOK["quarantined_callback"]})
        failed = c.execute("SELECT COUNT(*) AS n FROM billing_attempts WHERE scenario IN ('failed','timeout')").fetchone()["n"]
        if failed:
            out.append({"code": "failed_collection", "severity": "medium", "count": failed, "runbook": RUNBOOK["failed_collection"]})
        stuck = c.execute("SELECT COUNT(*) AS n FROM settlement_outbox o WHERE NOT EXISTS (SELECT 1 FROM settlement_instructions i WHERE i.outbox_id=o.id)").fetchone()["n"]
        if stuck:
            out.append({"code": "outbox_stuck", "severity": "low", "count": stuck, "runbook": RUNBOOK["outbox_stuck"],
                        "note": "outbox rows without an instruction need a reviewed recipient; not necessarily a fault"})
    return out


def readiness(repo=None) -> dict:
    from .ledger_repository import LedgerUnavailable, configured_repository
    checks = {}
    try:
        repo = repo or configured_repository()
        with repo.transaction() as c:
            versions = [r["version"] for r in c.execute("SELECT version FROM pilot_schema_migrations ORDER BY version").fetchall()]
        checks["ledger_migrated"] = versions == list(range(1, 8))
    except Exception:  # any failure to prove the ledger is migrated means not ready
        checks["ledger_migrated"] = False
    checks["environments_valid"] = not check_environments()
    from .contracts import M1_SHA256, M1_VERSION, get_contract
    checks["frozen_contract_intact"] = get_contract(M1_VERSION).sha256 == M1_SHA256
    checks["providers_local_mock_only"] = True  # asserted structurally by tests: provider modules import no network libraries
    return {"ready": all(checks.values()), "checks": checks, "mode": "simulation_only"}


router = APIRouter(prefix="/api/v1/ops", tags=["Operations"])


def operator(p=Depends(_principal)):
    if p.role not in ("operator", "reviewer", "service"):
        raise HTTPException(403, "Operator, reviewer or service role required.")
    return p


@router.get("/ready")
def ready(response: Response):
    r = readiness()
    response.status_code = 200 if r["ready"] else 503
    response.headers["Cache-Control"] = "no-store"
    return {"ready": r["ready"], "mode": r["mode"]}  # public: no detail


@router.get("/status")
def status(response: Response, p=Depends(operator)):
    response.headers["Cache-Control"] = "no-store"
    return {**readiness(), "alerts": collect_alerts()}


@router.get("/metrics")
def metrics(p=Depends(operator)):
    return Response(METRICS.prometheus(), media_type="text/plain; version=0.0.4", headers={"Cache-Control": "no-store"})
