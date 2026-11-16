"""Explicit isolated ledger migration; optional read-only M1 SQLite import.

Configure DAYCOVER_PILOT_BACKEND=postgres and DAYCOVER_PILOT_DATABASE_URL,
then run python -m scripts.migrate_pilot_ledger [--sqlite-source backup.sqlite3].
No legacy PostGIS tables, payment providers or source files are modified.
"""
import argparse
import json
from src.daycover.ledger_repository import configured_repository
from src.daycover.ledger_migrations import import_sqlite


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sqlite-source')
    args=parser.parse_args()
    repo=configured_repository()
    repo.migrate()
    result=import_sqlite(repo,args.sqlite_source) if args.sqlite_source else {'schema_version':7,'backend':repo.backend}
    print(json.dumps(result))


if __name__=='__main__':
    main()
