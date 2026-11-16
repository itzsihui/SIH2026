"""Phase 16: observability, request limits, environment separation, recovery, retention and journey rehearsal."""
import ast
import json
import logging
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.daycover import auth, billing, explanations as ex, notifications as nt, ops, recovery, settlement, read_models
from src.daycover.api import app
from src.daycover.ledger_repository import SqlLedgerRepository
from test_read_models import prepared, view
from test_settlement import queued, rows
from test_evidence_engine import DAY, NOW
import test_billing as tb


def mini_app(**env):
    m = ops.Metrics()
    a = FastAPI()

    @a.post("/echo/{x}")
    async def echo(x: str, body: dict | None = None):
        return {"x": x}

    @a.get("/ok")
    def okay():
        return {"ok": True}

    a.add_middleware(ops.OpsMiddleware, metrics=m)
    return a, m


# ---------------------------------------------------------------- environments

def test_environments_are_separated_and_mock_only():
    assert ops.check_environments() == []
    cfg = ops.load_environments()
    bad = json.loads(json.dumps(cfg))
    bad["environments"]["test"]["db"] = bad["environments"]["dev"]["db"]
    bad["environments"]["test"]["provider_secret_env"] = bad["environments"]["dev"]["provider_secret_env"]
    bad["environments"]["staging_local"]["provider_namespace"] = "real_provider"
    bad["environments"]["production"] = dict(bad["environments"]["dev"])
    probs = " ".join(ops.check_environments(bad))
    assert "shares db" in probs and "shares provider secret" in probs and "local_mock_only" in probs and "no production" in probs
    env = ops.apply_environment("staging_local")
    assert env["DAYCOVER_PILOT_BACKEND"] == "postgres" and env["DAYCOVER_PILOT_PG_SCHEMA"] == "daycover_pilot_staging_local"
    assert not any("SECRET" in k or "PASSWORD" in k or "TOKEN" in k for k in env)


# ---------------------------------------------------------------- middleware

def test_correlation_id_logging_metrics_and_privacy(caplog):
    a, m = mini_app()
    c = TestClient(a)
    with caplog.at_level(logging.INFO, logger="daycover.ops"):
        r = c.get("/ok?token=SECRET123&alias=bob", headers={"X-Correlation-ID": "abc-12345678", "Authorization": "Bearer TOPSECRET"})
        r2 = c.get("/ok", headers={"X-Correlation-ID": "bad id with spaces <script>"})
    assert r.headers["x-correlation-id"] == "abc-12345678" and r.headers["x-content-type-options"] == "nosniff"
    assert r2.headers["x-correlation-id"] != "bad id with spaces <script>" and len(r2.headers["x-correlation-id"]) == 32
    text = " ".join(rec.message for rec in caplog.records)
    assert "abc-12345678" in text and '"route": "/ok"' in text
    assert not any(s in text for s in ("SECRET123", "bob", "TOPSECRET", "testclient", "127.0.0.1"))
    prom = m.prometheus()
    assert 'daycover_http_requests_total{method="GET",route="/ok",status="2xx"} 2' in prom and "daycover_http_request_seconds_bucket" in prom


def test_body_and_rate_limits(monkeypatch):
    monkeypatch.setenv("DAYCOVER_MAX_BODY_BYTES", "100")
    monkeypatch.setenv("DAYCOVER_RATE_LIMIT_PER_MIN", "3")
    a, m = mini_app()
    c = TestClient(a)
    big = c.post("/echo/a", content=b"x" * 500, headers={"content-type": "application/json"})
    assert big.status_code == 413 and "correlation_id" in big.json()
    assert all(c.get("/ok").status_code == 200 for _ in range(3))
    limited = c.get("/ok")
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
    assert 'reason="body_too_large"' in m.prometheus() and 'reason="rate_limited"' in m.prometheus()


def test_streamed_oversize_body_is_cut_off(monkeypatch):
    monkeypatch.setenv("DAYCOVER_MAX_BODY_BYTES", "100")
    a, m = mini_app()
    c = TestClient(a)
    r = c.post("/echo/a", content=(b"x" * 60 for _ in range(5)), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_security_sweep_no_unexpected_public_routes(monkeypatch):
    monkeypatch.setenv("DAYCOVER_AUTH_MODE", "local")
    public = {"/health", "/api/v1/health", "/api/v1/ledger/health", "/api/v1/ops/ready", "/api/v1/contracts", "/api/v1/integration",
              "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect", "/api/v1/auth/login", "/rules", "/api/v1/rules", "/stalls",
              "/api/v1/stalls", "/api/v1/hawker-centres", "/api/v1/contract"}
    c = TestClient(app, raise_server_exceptions=False)
    open_ = []
    for r in app.routes:
        path = getattr(r, "path", None)
        if not path:
            continue
        concrete = path.replace("{", "").replace("}", "")
        for method in sorted(getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}):
            resp = c.request(method, concrete.replace("version", "x"), json={})
            if resp.status_code < 400 and path not in public and not path.startswith("/api/v1/contracts/"):
                open_.append((method, path, resp.status_code))
    assert open_ == [], open_


# ---------------------------------------------------------------- readiness & alerts

def test_readiness_and_operator_only_detail(ledger_backend):
    repo = ledger_backend
    assert ops.readiness(repo)["ready"] is True
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    c = TestClient(app)
    ready = c.get("/api/v1/ops/ready")
    assert ready.status_code == 200 and set(ready.json()) == {"ready", "mode"}
    cust = auth.login("settlement_owner", "local-owner-test-password")["access_token"]
    assert c.get("/api/v1/ops/status").status_code == 401
    assert c.get("/api/v1/ops/status", headers={"Authorization": "Bearer " + cust}).status_code == 403
    assert c.get("/api/v1/ops/metrics", headers={"Authorization": "Bearer " + cust}).status_code == 403
    rev = auth.login("engine_reviewer", "local-reviewer-test-password")["access_token"] if False else None
    svc = auth.issue_service(service, ["coverage:read"])["access_token"]
    st = c.get("/api/v1/ops/status", headers={"Authorization": "Bearer " + svc})
    assert st.status_code == 200 and st.json()["ready"] and st.headers["cache-control"] == "no-store"
    assert c.get("/api/v1/ops/metrics", headers={"Authorization": "Bearer " + svc}).status_code == 200


def test_unreachable_ledger_is_not_ready(monkeypatch):
    monkeypatch.setenv("DAYCOVER_PILOT_BACKEND", "postgres")
    monkeypatch.setenv("DAYCOVER_PILOT_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none?connect_timeout=2")
    r = ops.readiness()
    assert r["ready"] is False and r["checks"]["ledger_migrated"] is False
    assert TestClient(app).get("/api/v1/ops/ready").status_code == 503


def test_alerts_for_uncertain_payout_and_sources(ledger_backend):
    repo = ledger_backend
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    iid = queued(repo, tid, rid, oid, service, scenario="timeout")
    settlement.dispatch("HC076", tid, iid, service, repo, now=NOW)
    alerts = ops.collect_alerts(repo, now=NOW)
    by = {a["code"]: a for a in alerts}
    assert by["payout_uncertain"]["count"] == 1 and by["payout_uncertain"]["amount_cents"] == 6000
    assert by["payout_uncertain"]["runbook"].startswith("docs/RUNBOOK.md#")
    assert "source_gap" in by                                           # no live weather feed in fixtures
    assert "HC076" not in json.dumps(alerts) and p["merchant_id"] not in json.dumps(alerts)


def test_failed_collection_alert(ledger_backend):
    repo = ledger_backend
    owner, reviewer, service, p, tid, bill = tb.setup(repo)
    a = tb.attempt(repo, tid, bill, service, scenario="failed")
    billing.submit("HC076", tid, a, repo, now=tb.NOW)
    billing.reconcile("HC076", tid, a, repo, now=tb.NOW)
    assert any(x["code"] == "failed_collection" for x in ops.collect_alerts(repo, now=tb.NOW))


# ---------------------------------------------------------------- recovery

def test_sqlite_backup_restore_and_rollback(tmp_path):
    src = tmp_path / "live.sqlite3"
    repo = SqlLedgerRepository(path=src)
    repo.migrate()
    with repo.transaction() as c:
        c.audit(None, "before_backup", {}, "2026-11-16T00:00:00+00:00")
    m = recovery.sqlite_backup(src, tmp_path / "bk")
    with repo.transaction() as c:
        c.audit(None, "after_backup", {}, "2026-11-16T01:00:00+00:00")
    bk = tmp_path / "bk" / m["file"]
    out = recovery.sqlite_restore(bk, tmp_path / "restored.sqlite3")
    assert out["integrity_ok"] and out["migration_versions"] == list(range(1, 8)) and out["matches_manifest_counts"]
    live = sqlite3.connect(src).execute("SELECT COUNT(*) FROM pilot_audit").fetchone()[0]
    back = sqlite3.connect(tmp_path / "restored.sqlite3").execute("SELECT COUNT(*) FROM pilot_audit").fetchone()[0]
    assert back == live - 1                                              # rollback point excludes post-backup write
    with pytest.raises(FileExistsError):
        recovery.sqlite_restore(bk, tmp_path / "restored.sqlite3")
    restored = SqlLedgerRepository(path=tmp_path / "restored.sqlite3")
    restored.migrate()                                                   # idempotent on a restored ledger
    assert ops.readiness(restored)["checks"]["ledger_migrated"]
    data = bytearray(bk.read_bytes()); data[-10] ^= 0xFF; bad = tmp_path / "bk" / "tampered.sqlite3"
    bad.write_bytes(data); Path(str(bad) + ".manifest.json").write_text((tmp_path / "bk" / (m["file"] + ".manifest.json")).read_text())
    with pytest.raises(ValueError, match="checksum"):
        recovery.sqlite_restore(bad, tmp_path / "x.sqlite3")


def test_incomplete_backup_refused(tmp_path):
    p = tmp_path / "half.sqlite3"
    c = sqlite3.connect(p); c.execute("CREATE TABLE pilot_schema_migrations(version INTEGER)"); c.execute("INSERT INTO pilot_schema_migrations VALUES (1)")
    c.commit(); c.close()
    with pytest.raises(Exception):
        recovery.sqlite_backup(p, tmp_path / "bk")
    assert not list((tmp_path / "bk").glob("*.sqlite3"))


def test_postgres_backup_restore_when_available(ledger_backend, tmp_path):
    import os
    import uuid
    import psycopg
    repo = ledger_backend
    if repo.backend != "postgres":
        pytest.skip("postgres only")
    url, schema = os.environ["DAYCOVER_TEST_POSTGRES_URL"], repo.schema
    with repo.transaction() as c:
        c.audit(None, "pg_backup_probe", {}, "2026-11-16T00:00:00+00:00")
    m = recovery.postgres_backup(url, schema, tmp_path / "pgbk", pg_dump="/opt/homebrew/bin/pg_dump")
    name = "dcrestore_" + uuid.uuid4().hex[:10]
    with psycopg.connect(url, autocommit=True) as admin:
        try:
            admin.execute(f'CREATE DATABASE "{name}"')
        except Exception:
            pytest.skip("no CREATEDB permission")
    try:
        target = url.rsplit("/", 1)[0] + "/" + name
        out = recovery.postgres_restore(tmp_path / "pgbk" / m["file"], target, pg_restore="/opt/homebrew/bin/pg_restore")
        assert out["complete"]
        with pytest.raises(FileExistsError):
            recovery.postgres_restore(tmp_path / "pgbk" / m["file"], target, pg_restore="/opt/homebrew/bin/pg_restore")
    finally:
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


def test_restart_does_not_duplicate_settlement(ledger_backend):
    repo = ledger_backend
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    iid = queued(repo, tid, rid, oid, service, scenario="success")
    settlement.dispatch("HC076", tid, iid, service, repo, now=NOW)
    restarted = SqlLedgerRepository(repo.backend, path=getattr(repo, "path", None), url=getattr(repo, "url", None), schema=getattr(repo, "schema", None)) if repo.backend == "sqlite" else repo
    settlement.dispatch("HC076", tid, iid, service, restarted, now=NOW)       # replay after "restart"
    for _ in range(3):
        settlement.reconcile("HC076", tid, iid, restarted, now=NOW)
    assert len(rows(restarted, "settlement_instructions")) == 1
    assert len(rows(restarted, "settlement_mock_wallet_entries")) == 1
    assert settlement.overview("HC076", tid, restarted, now=NOW)["summary"]["confirmed_mock_cents"] == 6000
    again = queued(restarted, tid, rid, oid, service, scenario="success")      # same idempotency key
    assert again == iid and len(rows(restarted, "settlement_instructions")) == 1


# ---------------------------------------------------------------- retention, audit, least privilege

def test_purge_expired_keeps_audit_and_live_credentials(ledger_backend):
    repo = ledger_backend
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    live = auth.issue_service(service, ["coverage:read"])
    with repo.transaction() as c:
        c.execute("INSERT INTO auth_login_limits VALUES (?,?,?)", ("old", 5, 1))
        c.execute("INSERT INTO auth_login_limits VALUES (?,?,?)", ("recent", 1, auth.now()))
        audit_before = c.execute("SELECT COUNT(*) AS n FROM pilot_audit").fetchone()["n"]
        decisions = c.execute("SELECT COUNT(*) AS n FROM engine_decisions").fetchone()["n"]
    res = recovery.purge_expired(repo, now=auth.now())
    assert res["login_limits_purged"] == 1
    with repo.transaction() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM auth_login_limits WHERE key_hash='recent'").fetchone()["n"] == 1
        assert c.execute("SELECT COUNT(*) AS n FROM pilot_audit").fetchone()["n"] == audit_before + 1
        assert c.execute("SELECT COUNT(*) AS n FROM engine_decisions").fetchone()["n"] == decisions
    far = recovery.purge_expired(repo, now=auth.now() + 90 * 86400)
    assert far["credentials_purged"] >= 1
    with pytest.raises(Exception):
        TestClient(app).get("/api/v1/ops/status", headers={"Authorization": "Bearer " + live["access_token"]}).raise_for_status()


def test_erasure_of_advisory_stores_keeps_triggers_and_logs_hash_only(tmp_path):
    n = nt.NotificationStore(tmp_path / "n.sqlite3")
    n.set_consent("M-ERASE", "in_app", "en", True, "M-ERASE", True)
    n.set_consent("M-KEEP", "in_app", "en", True, "M-KEEP", True)
    with sqlite3.connect(tmp_path / "n.sqlite3") as c:
        for who in ("M-ERASE", "M-KEEP"):
            c.execute("INSERT INTO notifications VALUES (?,?,?,?,?,?,?,?)", (f"N-{who}", f"k-{who}", who, "in_app", "en", "k", "{}", "t"))
            c.execute("INSERT INTO delivery_events(notification_id,state,detail,recorded_at) VALUES (?,?,?,?)", (f"N-{who}", "queued", "", "t"))
    res = recovery.erase_subject(tmp_path / "n.sqlite3", "notifications", "M-ERASE", "reviewer-1", "subject request")
    assert res["rows_erased"] == 3
    with sqlite3.connect(tmp_path / "n.sqlite3") as c:
        assert c.execute("SELECT COUNT(*) FROM notifications WHERE merchant_id='M-KEEP'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM notifications WHERE merchant_id='M-ERASE'").fetchone()[0] == 0
        log = c.execute("SELECT subject_sha256 FROM erasure_log").fetchone()[0]
        assert "M-ERASE" not in log and len(log) == 64
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("DELETE FROM notifications")                      # append-only protection restored
    with pytest.raises(ValueError):
        recovery.erase_subject(tmp_path / "n.sqlite3", "ledger", "x", "r", "r")


def test_sensitive_actions_audited_without_secrets(ledger_backend):
    repo = ledger_backend
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    first = auth.issue_service(service, ["coverage:read"])
    second = auth.issue_service(service, ["coverage:read"], rotate=True)
    auth.set_grant(owner, p["merchant_id"], False)
    auth.disable(owner)
    token = auth.login("engine_reviewer", "local-reviewer-test-password")["access_token"]
    auth.lifecycle(token, "logout")
    with repo.transaction() as c:
        audit = c.execute("SELECT action,details FROM pilot_audit").fetchall()
        actions = {r["action"] for r in audit}
        blob = " ".join(r["details"] for r in audit)
        old = c.execute("SELECT revoked FROM auth_credentials WHERE principal_id=? ORDER BY created_at", (service,)).fetchall()
    assert {"merchant_grant_changed", "principal_disabled", "credential_logout"} <= actions
    for secret in (first["access_token"], second["access_token"], token, "local-owner-test-password", "local-reviewer-test-password"):
        assert secret not in blob
    assert old[0]["revoked"] == 1                                       # rotation revoked the earlier credential
    with pytest.raises(Exception):
        TestClient(app).get(f"/api/v1/read-models/stalls/HC076/terms/{tid}", params={"day": str(DAY)},
                            headers={"Authorization": "Bearer " + first["access_token"]}).raise_for_status()


def test_provider_modules_are_local_mock_only():
    banned = {"httpx", "requests", "urllib", "urllib3", "socket", "http", "aiohttp", "smtplib", "boto3", "stripe"}
    for name in ("billing_provider", "settlement_provider"):
        tree = ast.parse(Path(f"src/daycover/{name}.py").read_text())
        mods = {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not mods & banned, (name, mods & banned)
        src = Path(f"src/daycover/{name}.py").read_text()
        assert "getenv" not in src and "environ" not in src and "http" not in src.lower().replace("-", "")


# ---------------------------------------------------------------- journey rehearsal

def test_customer_and_operator_journey_with_no_payout_and_failure(ledger_backend, tmp_path):
    repo = ledger_backend
    owner, reviewer, service, p, tid, rid, oid = prepared(repo)
    c = TestClient(app)
    token = auth.login("settlement_owner", "local-owner-test-password")["access_token"]
    h = {"Authorization": "Bearer " + token}
    url = f"/api/v1/explanations/stalls/HC076/terms/{tid}"
    # 1 payout day: entitlement recorded, no payment submitted yet
    t1 = c.get(url, params={"day": str(DAY)}, headers=h).json()["text"]
    assert "S$60.00" in t1 and "no payment has been submitted" in t1
    # 2 no-payout day: not evaluated, honest, nothing recorded
    t2 = c.get(url, params={"day": str(DAY + timedelta(days=1))}, headers=h).json()["text"]
    assert "not been evaluated" in t2 and "S$60.00" not in t2.split("Remaining")[0]
    # 3 failure: payout outcome unknown -> customer sees uncertainty, operator sees alert, no duplicate on retry
    iid = queued(repo, tid, rid, oid, service, scenario="timeout")
    settlement.dispatch("HC076", tid, iid, service, repo, now=NOW)
    t3 = ex.explain(view(repo, owner, tid))["text"]
    assert "uncertain" in t3.lower() and "not real money" in t3
    assert any(a["code"] == "payout_uncertain" for a in ops.collect_alerts(repo, now=NOW))
    settlement.dispatch("HC076", tid, iid, service, repo, now=NOW)
    assert len(rows(repo, "settlement_instructions")) == 1
    # 4 operator reconciles the mock outcome; customer text changes only through ledger facts
    settlement.reconcile("HC076", tid, iid, repo, now=NOW)
    t4 = ex.explain(view(repo, owner, tid))["text"]
    assert "uncertain" not in t4.lower() or "no real money" in t4
    # 5 notification only with consent, simulated, one message per state
    store = nt.NotificationStore(tmp_path / "journey.sqlite3")
    v = view(repo, owner, tid)
    assert all(store.status(i) == "suppressed_no_consent" for i in store.enqueue("M-J", v))
    store.set_consent("M-J", "in_app", "en", True, "M-J", True)
    ids = store.enqueue("M-J", v)
    sent = []
    store.dispatch(lambda nid, payload, key: sent.append(payload) or True)
    assert sent == []                                                    # no retroactive messages for pre-consent events
