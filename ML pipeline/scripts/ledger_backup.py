"""Local ledger backup/restore. SQLite is backed up with the online backup API; PostgreSQL via pg_dump.

    .venv/bin/python -m scripts.ledger_backup backup --out var/backups
    .venv/bin/python -m scripts.ledger_backup restore BACKUP_FILE NEW_TARGET_PATH
Restores never overwrite; point the application at the restored path deliberately and only after review.
"""
import argparse
import json
import os

from src.daycover import recovery


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup"); b.add_argument("--out", default="var/backups")
    r = sub.add_parser("restore"); r.add_argument("backup"); r.add_argument("target")
    a = ap.parse_args(argv)
    if a.cmd == "backup":
        if os.getenv("DAYCOVER_PILOT_BACKEND", "sqlite") == "postgres":
            print(json.dumps(recovery.postgres_backup(os.environ["DAYCOVER_PILOT_DATABASE_URL"], os.getenv("DAYCOVER_PILOT_PG_SCHEMA", "daycover_pilot"), a.out)))
        else:
            print(json.dumps(recovery.sqlite_backup(os.getenv("DAYCOVER_PILOT_DB", "var/pilot.sqlite3"), a.out)))
    else:
        print(json.dumps(recovery.sqlite_restore(a.backup, a.target)))


if __name__ == "__main__":
    main()
