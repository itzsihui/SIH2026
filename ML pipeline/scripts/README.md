# Part 2 development scripts

Run commands from the project root. No frontend app is required.

## Current engine and ledger

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn src.daycover.api:app --host 127.0.0.1 --port 8000
.venv/bin/python -m scripts.migrate_pilot_ledger
```

SQLite is the default. The canonical ledger is local under `var/`. To use PostgreSQL, explicitly select `DAYCOVER_PILOT_BACKEND=postgres`, securely supply `DAYCOVER_PILOT_DATABASE_URL`, then run the migration command. Read the backup/import/rollback instructions in `prompts.md` before touching an existing ledger. `docker-compose.yml` provisions only an optional local PostgreSQL service and does not auto-run legacy migrations.

To run the PostgreSQL tests as well, securely set `DAYCOVER_TEST_POSTGRES_URL` to an isolated local test service, then run pytest. The test fixture creates and removes only its generated `daycover_pilot_test_...` schemas. Do not point tests at shared user data. Without that variable, these tests are explicitly skipped.

## Data and research — inspect prerequisites first

| Script/group | Purpose | Current boundary |
|---|---|---|
| `ingest_nea_telemetry.py` | Resumable NEA v2 canonical adapter | Raw evidence, quarantine, source health, pagination and provisional revisions. No aggregates or settlement |
| `fetch_history.py` | Historical public-data acquisition | `--plan` previews requests; a full archive is not already present |
| `build_dataset.py` | Public climate/centre dataset preparation | Needs the full raw-history inputs; does not consume the supplied transaction CSVs directly |
| `synthesize_stalls.py` | Research merchant/QR scenarios | Different synthetic research format; does not prove real hawker income behavior |
| `train_rain.py`, `train_haze.py`, `train_impact.py` | Frequency and income-impact research | Optional ML dependencies and required processed/QR-history inputs must exist |
| `walk_forward*.py`, `audit_models.py`, `price_and_test_2026.py` | Evaluation and pricing scenarios | Audit leakage, missingness and contract differences before reuse |
| `calibrate_triggers.py`, `backtest_simulator.py`, `price_pilot.py` | Historical trigger/pricing evidence | Research results cannot issue policies or settle the canonical ledger |
| `premium_accrual_sim.py` | Collection mechanics experiment | Hypothetical collection only; not actual GIRO or transaction-provider access |
| `train_heat_workers.py`, `train_rl_reinsurance.py` | Optional research extensions | Shadow/advisory; not the current hawker claims path |

Install optional ML/research libraries with:

```sh
.venv/bin/python -m pip install -r requirements-ml.txt
```

Do not start a training or download job simply because a script exists. First record its input paths, source/licence, expected outputs, split strategy and relationship to the frozen contract. No GitHub issue-creation scripts, Flutter build scripts or payment sandbox are included in the active workspace.

## Local identity administration

Run `.venv/bin/python -m scripts.manage_local_identity --help`. Its `create`, `grant`, `service-token` and `disable` commands provision local roles, assign/revoke individual merchant access, issue/rotate scoped service credentials and disable accounts. Human passwords are entered through a hidden terminal prompt. Service secrets are intentionally displayed once; do not paste them into documentation or source. Follow `../docs/README.md` for the complete customer → reviewer → service workflow. These commands use the selected canonical ledger; they do not verify official identities or contact external services.

## Canonical weather commands

`.venv/bin/python -m scripts.ingest_nea_telemetry --kind rain` ingests a latest snapshot; use `--kind psi` for regional PSI. Add `--date YYYY-MM-DD --max-pages 1` for a bounded historical job. Resume with `--resume <returned_run_id> --max-pages 10`; do not supply a new kind/date with resume. `--health` reports missing, stale, degraded or available-provisional live sources. Completed jobs are idempotent; a new job deliberately re-fetches data and preserves revisions. Exit 2 means the job is paused/failed/quarantined or source health needs attention. See `../docs/README.md` for storage, rate limits, attribution and operational boundaries. No scheduled polling is automatically enabled.

## Daily weather evidence

`.venv/bin/python -m scripts.daily_weather_evidence --help` lists `build`, `show`, `mapping`, `revision`, `review`, `closure`, `review-closure` and `select`. These are trusted local database-admin operations; review actions require an active local reviewer ID and evidence reference. See `../docs/README.md` for the workflow and boundaries. Rain totals remain candidates until official interval labelling is verified; no CLI option overrides that gate. The HTTP evidence route is read-only and merchant-scoped. No command triggers a payout.

## Lifecycle and evidence decisions

Phase 6 is exposed through scoped FastAPI routes, documented in `../docs/README.md`. Use the existing identity tool to issue a merchant-granted service credential with `decision:evaluate` (and `coverage:read` for read models). Reviewers require fresh login scopes `policy:manage` / `decision:review`; customers/operators explicitly accept renewal through the API. These routes do not execute payments. Legacy synthetic triggers and reviewed-source decisions cannot share one period.

## Simulation billing

Phase 7 uses scoped API routes documented in `../docs/README.md`. Provision a merchant-granted service credential with `billing:collect`, `billing:reconcile` and `coverage:read`; customers/operators must separately grant `billing:authorize` mock permission, and reviewers use `billing:review` for explicit mock-only return bookkeeping. Fresh login/credential issuance is needed for new scopes. The provider persists locally and makes no network/debit call. No automatic collection/retry scheduler, real GIRO mandate or funded sponsor is configured.

## Mock settlement worker operations

Phase 8 worker operations are scoped APIs in `../docs/README.md`: sync pending outbox, queue a server-sized instruction, submit/recover its stable provider reference and reconcile signed mock outcomes. Use a merchant-granted service credential with `settlement:queue`, `settlement:submit`, `settlement:reconcile` and `coverage:read`; customer mock registration and reviewer approval have separate scopes. Three manual submissions per instruction are allowed, then reconcile only; no scheduler or real bank/wallet adapter is installed. Never infer failure from timeout or pay every positive entitlement entry separately.
