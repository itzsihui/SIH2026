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

## Part 1 integration checks

Run `.venv/bin/python -m pytest -q tests/test_read_models.py`. With `DAYCOVER_TEST_POSTGRES_URL` pointing to a dedicated disposable service, the same tests cover SQLite and generated PostgreSQL schemas. The HTTP consumer fixtures start/stop local Uvicorn, exercise safe GET retries and expired credentials, and leave no persistent app data. Routes and frontend handling are in `../docs/README.md` under “Part 1 versioned read models.” No frontend build or real provider is required.

## Digital-only dataset foundation

Run `.venv/bin/python -m scripts.build_digital_dataset --out data/processed/digital-v1.1` with the supplied CSVs present. Choose a new version path if it exists. This uses `configs/dataset-v1.json`, keeps raw inputs unchanged, and writes validated digital receipts, forward-time/merchant split membership, manifests and rejection/audit reports. It does not train a model or write to a ledger. `.venv/bin/python -m scripts.inventory_dataset_sources --out data/processed/digital-source-inventory-v1.json` separately inventories local source copies; it also refuses overwrite. Tests: `.venv/bin/python -m pytest -q tests/test_dataset_pipeline.py`. Read `../dataset/README.md` for exact filtering, provenance, refund and leakage boundaries. The older `build_dataset.py` remains a separate historical weather research tool, not the transaction adapter.

## Phase 11 digital-sales baseline

`.venv/bin/python -m scripts.run_income_baseline` fits weekday/pooled medians on the Phase 10 `split=train` rows only, scores validation/test/holdout (observed digital days only; gaps are unknown, not zero) and writes `data/processed/income-baseline-v1/` (ignored; never overwritten). Includes seeded labelled scenario panels and assumption-labelled margin scenarios on digital sales. Synthetic data only; no real-world accuracy claim and no weather response applied.

## Phase 12 weather-impact audit

`.venv/bin/python -m scripts.run_weather_impact` audits leakage/target/missingness and compares advisory weather candidates with a no-weather control (train-only fits, merchant-cluster bootstrap). Writes ignored `data/processed/weather-impact-v1/`. Current result on synthetic data: candidates rejected for insufficient weather exposure; baseline retained. No cash features, no filled weather, no real-world claim.

## Phase 13 advisory recommendations

`src/daycover/recommendation.py` + `configs/recommendation-bands-v1.json` price candidate benefit bands by replaying their exact trigger/cap rules, recommend with a fixed-M1 fallback (no history/consent needed), and record choices in a separate append-only store. `.venv/bin/python -m scripts.run_recommendation_audit` writes ignored `data/processed/recommendation-audit-v1/`. Advisory only: it cannot change the frozen contract, existing terms or entitlements; indicative prices are not approved prices.

## Phase 14 protection and capital research

`.venv/bin/python -m scripts.run_protection_research` replays M1 and research S$150 designs on identical PSI/rain assumptions, measures trigger quality against digital-sales disruption (low power on current synthetic data), gauge-to-gauge disagreement, sparse-PSI stress, liquidity timing and seeded portfolio scenarios. Writes ignored `data/processed/protection-research-v1/`. Research only: assumptions are not quotes, nothing guarantees solvency, and no result changes existing contract rules.

## Phase 15 notifications

`src/daycover/notifications.py` stores opt-in consent, simulated notification payloads and delivery status in a separate append-only SQLite store; tests use fake senders only. No real SMS/push/soundbox is contacted.

## Phase 16 operations

`scripts/ledger_backup.py` (verified backup/restore to a new path), `scripts/rotate_service_credential.py` (revoke-and-reissue, token printed once) and `scripts/local_release_check.py` (environment, contract, readiness, backup/restore rehearsal and code checksum; writes ignored `var/release/`). Procedures: `docs/RUNBOOK.md`.
