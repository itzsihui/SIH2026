# DayCover+ Part 2 — local operator runbook

Scope: the **local simulation** engine only. No real issuer, partner, collection or payout exists; every provider is a local mock. These procedures rehearse the future operating model; they do not authorise real money movement. Existing ledger history (audit, decisions, billing, settlement) is never edited or deleted.

Prerequisites: environment variables for the chosen backend exported in the same shell as the commands below ([README](../README.md#setup-with-a-database)). Operators need a `reviewer` or `service` credential; customers cannot view operations data.

## Daily checks

```sh
curl --fail http://127.0.0.1:8000/api/v1/ops/ready          # public, minimal: ready true/false
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/ops/status   # detail + alerts (operator/reviewer/service)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/ops/metrics  # Prometheus text
```

Every response carries `X-Correlation-ID`; quote it when investigating (structured JSON logs on the `daycover.ops` logger contain it, the route template and status, never query strings, tokens, bodies or IPs). Alert codes below link here.

## Source outage or correction
*Alert `source_gap`.* Statuses `missing`/`stale`/`degraded` mean weather is not fresh or has unresolved conflicts.
1. `python -m scripts.ingest_nea_telemetry --health` to see latest runs and alerts; resume with `--resume RUN_ID`.
2. Affected days stay **pending**; no value is invented and no denial is recorded. Customers see "pending, not denied".
3. After source recovery or a reviewed correction, use the trusted evidence CLI (`python -m scripts.daily_weather_evidence --help`) and the reviewer endpoints; then `POST /api/v1/evidence/...` evaluation as documented in `docs/README.md`. Corrections append reviews; history is preserved.
4. Historical decisions made before a correction show `current_context_matches: false` and need replay review; never edit rows.

## Pending decision or stuck outbox
*Alert `outbox_stuck`.* An accepted entitlement has no settlement instruction: usually the mock recipient is not registered/approved. A reviewer approves the recipient (`POST /api/v1/settlement-recipients/{stall}/{recipient_id}/review`), then a service credential queues it. Not a fault by itself.

## Uncertain payout
*Alert `payout_uncertain`.* A submission timed out or the provider response was lost.
1. Do **not** requeue with a new key. `POST .../instructions/{id}/reconcile` (or `/sync`) with the service credential; the reservation is retained until a definitive provider snapshot.
2. Repeated reconcile is idempotent; wallet credit appears at most once. Callbacks arriving first are accepted only when valid.
3. Customers are told "uncertain, under review" and that no real money moved.

## Quarantined callbacks
*Alert `quarantined_callback`.* Invalid, forged or regressing provider events are stored but never applied. Inspect `billing_provider_events`/`settlement_provider_events` where `disposition='quarantined'` (read-only SQL); correct the sender or reconcile via the API. Do not delete rows.

## Failed debit
*Alert `failed_collection`.* Failed/timeout attempts leave the bill outstanding; no debit occurred in simulation. Retry with a new idempotency key only after the previous attempt is terminal; partial collections retry the remainder only. Real mandate, grace, lapse and retry rules are unspecified — do not invent them.

## Backup, restore and rollback
```sh
.venv/bin/python -m scripts.ledger_backup backup --out var/backups              # SQLite online backup (or pg_dump when backend=postgres)
.venv/bin/python -m scripts.ledger_backup restore var/backups/FILE NEW_PATH     # verified restore to a NEW path; never overwrites
```
- Stop writers, back up before every migration or upgrade. Backups carry a checksum manifest; restores check integrity, checksum and migrations 1–7.
- **Rollback** = stop the API, restore the pre-upgrade backup to a new path, point `DAYCOVER_PILOT_DB` (or the PostgreSQL URL/schema) at it, start the matching code version, check `/api/v1/ops/ready`. Writes after the backup are lost; record them from logs/audit before switching. Migrations are additive and checksummed — never edit applied migration SQL.
- PostgreSQL restores go into an empty separate database (`recovery.postgres_restore`); the original schema is untouched.

## Restart / queue recovery
Restart the API. Settlement and billing operations are idempotent by key: replaying `queue`, `submit` or `reconcile` after a crash cannot create a second instruction or credit. Notifications left mid-send are recovered with `NotificationStore.recover()` and never resent after `delivered_sim`.

## Credentials and access
- Rotate a service credential: `python -m scripts.rotate_service_credential PRINCIPAL_ID --scopes ...` (revokes prior credentials, prints the new token once, audits without the token).
- Disable a principal with `auth.disable`; grants change with `auth.set_grant`. Both are audited. Sessions last 15 minutes (8 hours absolute).
- Defaults: request body ≤ 1 MiB (`DAYCOVER_MAX_BODY_BYTES`), 1200 requests/min per client (`DAYCOVER_RATE_LIMIT_PER_MIN`), login lockout after 5 failures/15 min. Staging-equivalent values are in `configs/environments.json` (names of secret variables only; never commit secrets).

## Quote-only service login for the app backend
Create this on the target database only (Railway: run with that service's `DAYCOVER_PILOT_BACKEND`, `DAYCOVER_PILOT_DATABASE_URL`, `DAYCOVER_PILOT_PG_SCHEMA` exported; never from a shared laptop shell). Least privilege: `coverage:read` only, one merchant grant per stall the app may quote.
```sh
.venv/bin/python -m scripts.manage_local_identity create app_quotes service            # prints the principal id
.venv/bin/python -m scripts.manage_local_identity grant PRINCIPAL_ID MERCHANT_ID          # repeat per merchant
.venv/bin/python -m scripts.manage_local_identity service-token PRINCIPAL_ID --scope coverage:read --ttl 86400
```
The token is printed once: hand it over privately and never commit it. Rotate with `scripts.rotate_service_credential`; revoke with `manage_local_identity disable`. Do not grant `settlement:*`, `billing:*` or `transactions:*` scopes for quote reads. Collection routes need `transactions:read`/`transactions:retain`/`billing:collect` and the merchant's `transaction_retention` consent.

## App wallet delivery
Failed/uncertain deliveries: `GET .../instructions/{id}/app-delivery`. `failed` with 401 = wrong/missing `ENGINE_SHARED_SECRET`; 404 = app does not know the stall (check the centre name / `DAYCOVER_APP_STALL_MAP`); `uncertain` = retry the same endpoint (same `instruction_id`, app deduplicates). `response_mismatch` or exhausted attempts need operator review; never create a new instruction to "retry".

## Retention and deletion
`recovery.RETENTION` lists the rules. `recovery.purge_expired` removes only stale login-limit rows and long-expired credentials. Audit and financial history are **retained** (a reviewed retention period does not yet exist). Advisory stores (consent, notifications, recommendations) are erased per subject with `recovery.erase_subject`, which keeps a hashed erasure log. Raw digital receipt datasets are deleted by removing the merchant's namespace from `data/processed/digital-v1.*` rebuilds; they hold no cash or identity data.

## Customer and operator rehearsal (local)
`tests/test_operations.py::test_customer_and_operator_journey_with_no_payout_and_failure` walks: payout day (entitlement, nothing submitted) → no-payout day (not evaluated) → uncertain payout (customer text, operator alert, retry with no duplicate) → reconciliation → consented simulated notification. Run `scripts/local_release_check.py` for the release-candidate record.
