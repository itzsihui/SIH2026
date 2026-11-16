"""Phase 16: verified backup/restore, retention purge and subject erasure for local stores.

Restores never overwrite an existing target, and only complete, checksum-matching, fully migrated backups are accepted.
Retention keeps audit and financial ledger history (required under reviewed rules; none is established yet), purges only
expired authentication residue, and erases advisory stores (consent, notifications, recommendations) for a subject.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .ledger_repository import LATEST_VERSION

EXPECTED_VERSIONS = list(range(1, LATEST_VERSION + 1))
KEY_TABLES = ("pilot_audit", "pilot_policies", "engine_decisions", "settlement_instructions", "billing_attempts", "auth_principals")
RETENTION = {
    "auth_login_limits": {"action": "purge_after_seconds", "seconds": 86400},
    "auth_credentials_expired_or_revoked": {"action": "purge_after_seconds", "seconds": 30 * 86400},
    "pilot_audit": {"action": "retain", "reason": "required audit record; retention period not yet defined by reviewed rules"},
    "financial_ledger_and_decisions": {"action": "retain", "reason": "entitlement/settlement history is never deleted or restored"},
    "advisory_stores": {"action": "erase_on_request", "reason": "consent/notification/recommendation data are not required audit records"},
}


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inspect(path) -> dict:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        versions = [r[0] for r in c.execute("SELECT version FROM pilot_schema_migrations ORDER BY version")]
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in KEY_TABLES}
    finally:
        c.close()
    return {"integrity_ok": ok, "migration_versions": versions, "row_counts": counts}


def sqlite_backup(source, out_dir) -> dict:
    """Consistent online backup using SQLite's backup API (safe with WAL/concurrent writers)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = out / f"ledger-{stamp}.sqlite3"
    if dest.exists():
        raise FileExistsError(dest)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    try:
        info = _inspect(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise ValueError("backup failed verification and was discarded") from exc
    manifest = {"backend": "sqlite", "file": dest.name, "sha256": sha256_file(dest), "bytes": dest.stat().st_size, **info,
                "created_at": datetime.now(timezone.utc).isoformat()}
    if not info["integrity_ok"] or info["migration_versions"] != EXPECTED_VERSIONS:
        dest.unlink()
        raise ValueError("backup failed verification and was discarded")
    (out / (dest.name + ".manifest.json")).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def sqlite_restore(backup, target) -> dict:
    """Restore to a NEW path after checksum, integrity and migration verification. Never overwrites."""
    backup, target = Path(backup), Path(target)
    manifest = json.loads(Path(str(backup) + ".manifest.json").read_text())
    if target.exists():
        raise FileExistsError("restore target exists; restore to a new path and swap deliberately")
    if sha256_file(backup) != manifest["sha256"]:
        raise ValueError("backup checksum mismatch")
    info = _inspect(backup)
    if not info["integrity_ok"] or info["migration_versions"] != EXPECTED_VERSIONS:
        raise ValueError("backup is incomplete or incompatible with this code version")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".restoring")
    shutil.copyfile(backup, tmp)
    os.replace(tmp, target)
    return {"restored": str(target), **_inspect(target), "matches_manifest_counts": _inspect(target)["row_counts"] == manifest["row_counts"]}


def postgres_backup(url: str, schema: str, out_dir, pg_dump: str = "pg_dump") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"ledger-{schema}-{int(time.time() * 1000)}.dump"
    subprocess.run([pg_dump, "--dbname", url, "-n", schema, "-Fc", "-f", str(dest)], check=True, capture_output=True)
    m = {"backend": "postgres", "schema": schema, "file": dest.name, "sha256": sha256_file(dest), "bytes": dest.stat().st_size,
         "created_at": datetime.now(timezone.utc).isoformat()}
    (out / (dest.name + ".manifest.json")).write_text(json.dumps(m, indent=1, sort_keys=True))
    return m


def postgres_restore(dump, new_database_url: str, pg_restore: str = "pg_restore") -> dict:
    """Restore into an EMPTY, separate database; refuses when the target already has the ledger schema."""
    import psycopg
    dump = Path(dump)
    m = json.loads(Path(str(dump) + ".manifest.json").read_text())
    if sha256_file(dump) != m["sha256"]:
        raise ValueError("backup checksum mismatch")
    with psycopg.connect(new_database_url) as c:
        if c.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (m["schema"],)).fetchone():
            raise FileExistsError("target database already contains the ledger schema")
    subprocess.run([pg_restore, "--dbname", new_database_url, "--no-owner", str(dump)], check=True, capture_output=True)
    with psycopg.connect(new_database_url) as c:
        versions = [r[0] for r in c.execute(f'SELECT version FROM "{m["schema"]}".pilot_schema_migrations ORDER BY version')]
    return {"restored_schema": m["schema"], "migration_versions": versions, "complete": versions == EXPECTED_VERSIONS}


# --------------------------------------------------------------------------- retention & erasure

def purge_expired(repo, now: int | None = None) -> dict:
    """Delete only expired authentication residue. Audit, decisions, billing and settlement rows are never touched."""
    now = int(now if now is not None else time.time())
    with repo.transaction() as c:
        lim = c.execute("DELETE FROM auth_login_limits WHERE window_start<?", (now - RETENTION["auth_login_limits"]["seconds"],)).rowcount
        cut = now - RETENTION["auth_credentials_expired_or_revoked"]["seconds"]
        cred = c.execute("DELETE FROM auth_credentials WHERE (revoked=1 AND created_at<?) OR absolute_expires_at<?", (cut, cut)).rowcount
        c.audit(None, "retention_purge", {"login_limits": lim, "credentials": cred}, datetime.fromtimestamp(now, timezone.utc).isoformat())
    return {"login_limits_purged": lim, "credentials_purged": cred}


ERASURE_DDL = "CREATE TABLE IF NOT EXISTS erasure_log (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_sha256 TEXT NOT NULL, store TEXT NOT NULL, " \
              "rows_erased INTEGER NOT NULL, requested_by TEXT NOT NULL, reason TEXT NOT NULL, recorded_at TEXT NOT NULL);"
STORES = {  # table -> (filter sql, params-from-subject); child tables first
    "notifications": [("delivery_events", "notification_id IN (SELECT id FROM notifications WHERE merchant_id=?)"),
                      ("notifications", "merchant_id=?"), ("consent_events", "merchant_id=?")],
    "recommendations": [("recommendation_events", "recommendation_id IN (SELECT id FROM recommendations WHERE merchant_id=?)"),
                        ("recommendations", "merchant_id=?")],
}


def erase_subject(db_path, store: str, merchant_id: str, requested_by: str, reason: str) -> dict:
    """Erase a merchant from an advisory append-only store in ONE transaction, leaving a non-identifying erasure log row."""
    if store not in STORES:
        raise ValueError("unknown store")
    c = sqlite3.connect(db_path, isolation_level=None)
    try:
        c.execute("BEGIN IMMEDIATE")
        triggers = [(n, s) for n, s in c.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()]
        for n, _ in triggers:
            c.execute(f'DROP TRIGGER "{n}"')
        total = 0
        for table, where in STORES[store]:
            total += c.execute(f"DELETE FROM {table} WHERE {where}", (merchant_id,)).rowcount
        for _, sql in triggers:
            c.execute(sql)
        c.execute(ERASURE_DDL)
        c.execute("INSERT INTO erasure_log(subject_sha256,store,rows_erased,requested_by,reason,recorded_at) VALUES (?,?,?,?,?,?)",
                  (hashlib.sha256(merchant_id.encode()).hexdigest(), store, total, requested_by, reason, datetime.now(timezone.utc).isoformat()))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()
    return {"store": store, "rows_erased": total, "retained": ["pilot_audit", "financial ledger and decisions (policy-required, not erased)"]}
