"""Rotate a local service credential: revokes all existing credentials for the principal and prints the new token ONCE.

    .venv/bin/python -m scripts.rotate_service_credential PRINCIPAL_ID --scopes settlement:queue settlement:submit [--ttl 3600]
Store the token in your local secret manager; it is never logged. The rotation is audited without the token.
"""
import argparse
import json

from src.daycover import auth


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("principal_id")
    ap.add_argument("--scopes", nargs="+", required=True)
    ap.add_argument("--ttl", type=int, default=3600)
    a = ap.parse_args(argv)
    res = auth.issue_service(a.principal_id, a.scopes, a.ttl, rotate=True)
    with auth.configured_repository().transaction() as c:
        c.audit(None, "service_credential_rotated", {"principal_id": a.principal_id, "credential_id": res["credential_id"], "scopes": sorted(a.scopes)}, auth.audit_time())
    print(json.dumps(res))


if __name__ == "__main__":
    main()
