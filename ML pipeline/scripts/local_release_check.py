"""Local release-candidate verification. Read-mostly; writes only an ignored record under var/release/.

    .venv/bin/python -m scripts.local_release_check [--tests-summary "467 passed, 1 skipped"]
Checks environment separation, frozen M1 contract, readiness, alerts, backup/restore rehearsal on a temporary copy,
provider isolation and code checksum. It deploys, contacts and changes nothing remote.
"""
import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.daycover import ops, recovery
from src.daycover.contracts import M1_SHA256, M1_VERSION, get_contract
from src.daycover.ledger_repository import SqlLedgerRepository

ROOT = Path(__file__).resolve().parents[1]
BLOCKERS = ["no real issuer/insurer approval", "no partner transaction access or consent", "no real mandate/collection rules",
            "no real payout rail or recipient verification", "official rain timestamp convention unverified (Phase 5 gate)",
            "no reviewed audit retention period", "no hosting, TLS termination or secret manager selected",
            "translations need native review", "Part 1 device/accessibility/TTS checks external"]


def code_sha() -> str:
    h = hashlib.sha256()
    for p in sorted(list((ROOT / "src").rglob("*.py")) + list((ROOT / "migrations").rglob("*.sql")) + [ROOT / "contracts" / "daycover-pilot-m1-2026.11-v1.json"]):
        if "__pycache__" not in p.parts:
            h.update(str(p.relative_to(ROOT)).encode()); h.update(p.read_bytes())
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests-summary", default="not recorded in this run")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as t:
        repo = SqlLedgerRepository(path=Path(t) / "rehearsal.sqlite3")
        repo.migrate()
        bk = recovery.sqlite_backup(repo.path, Path(t) / "bk")
        rs = recovery.sqlite_restore(Path(t) / "bk" / bk["file"], Path(t) / "restored.sqlite3")
        ready = ops.readiness(repo)
        alerts = ops.collect_alerts(repo)
    rec = {"created_at": datetime.now(timezone.utc).isoformat(), "code_sha256": code_sha(), "m1_version": M1_VERSION,
           "m1_sha256_matches": get_contract(M1_VERSION).sha256 == M1_SHA256, "environment_problems": ops.check_environments(),
           "readiness_on_rehearsal_ledger": ready, "alerts_on_empty_ledger": [x["code"] for x in alerts],
           "backup_restore_rehearsal": {"integrity_ok": rs["integrity_ok"], "versions": rs["migration_versions"], "counts_match": rs["matches_manifest_counts"]},
           "tests": a.tests_summary, "mode": "simulation_only", "deployed": False, "remote_changes": False, "future_release_blockers": BLOCKERS}
    rec["ok"] = rec["m1_sha256_matches"] and not rec["environment_problems"] and ready["ready"] and rs["integrity_ok"] and rs["matches_manifest_counts"]
    out = ROOT / "var" / "release"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"rc-{rec['code_sha256'][:12]}.json"
    path.write_text(json.dumps(rec, indent=1, sort_keys=True))
    print(json.dumps({k: rec[k] for k in ("ok", "code_sha256", "tests")}), str(path))


if __name__ == "__main__":
    main()
