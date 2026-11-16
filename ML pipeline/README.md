# DayCover+ Part 2 — Main Intelligence Engine + Dataset

Team repository: [itzsihui/SIH2026](https://github.com/itzsihui/SIH2026). This README covers the Main Intelligence Engine component in that project.

This is your **Part 2 development workspace**, not another copy of the complete application. Part 2 means the Main Intelligence Engine from your architecture; it is broader than the already completed development “Phase 2” database milestone.

The engine takes merchant/data inputs, analyses income and weather, applies a locked policy contract, records financial decisions, and returns explanations through APIs. The mobile app, frontend dashboard, wallet UI and payment-gateway sandbox belong to Part 1 and are not active source folders here.

## Start reading

1. [Engine architecture and interfaces](docs/README.md) — what Part 2 owns and how Part 1 connects.
2. [Your supplied transaction dataset](dataset/README.md) — exactly which files are present and what they mean.
3. [Weather and model data](data/README.md) — observed data versus synthetic/research outputs.
4. [Development commands](scripts/README.md) — useful scripts and their prerequisites.
5. `prompts.md` — the local-only phase plan and detailed agent handoff; intentionally ignored for future publishing.

## What is inside

| Folder | Purpose |
|---|---|
| `src/daycover/` | FastAPI, contract registry, deterministic rules, weather validation, policy periods and SQLite/Postgres ledger |
| `src/pricing/` | Experimental rain/haze/impact models and pricing research; not claims authority |
| `src/*.py` | Supporting historical weather, basis-risk, optimisation and financial research |
| `dataset/` | Your three transaction CSVs: 2,216,326 supplied synthetic receipts, unchanged |
| `data/raw/`, `data/processed/` | Weather/reference inputs and existing research/model outputs |
| `contracts/` | Frozen M1 simulation contract and separate catalogue of research alternatives |
| `migrations/` | Canonical pilot migrations plus older backend compatibility schemas |
| `scripts/` | Migration, ingestion, dataset preparation, training and evaluation tools |
| `tests/` | Tests for the current engine, APIs, data validation and ledger |
| `research/`, `results/` | Existing evidence/source notes and historical experiment outputs |
| `public/data/` | Backtest JSON consumed by backend research APIs; no frontend app |
| `docs/` | Focused guidance and selected original reference documents |

## Setup with a database

These commands use macOS/Linux shell syntax. Install Python 3.11+ and, for the PostgreSQL option, Docker with Compose. The full Phase 8 test run used Python 3.14 and PostgreSQL 18; the bundled Compose service uses PostgreSQL 16. No mobile app or live payment account is required.

### 1. Open the engine folder and install dependencies

After checking out [the team repository](https://github.com/itzsihui/SIH2026), open the **engine folder containing `requirements-daycover.txt`, `src/daycover/`, `migrations/pilot/` and `docker-compose.yml`**. If this component is nested inside the repository, run commands from that subfolder. The existing local working copy is:

```sh
cd "/Users/ankitasagar/Desktop/ML pipeline"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-daycover.txt -r requirements.txt
```

On another machine, replace the `cd` path with your engine checkout path. Choose **one** database option below, then continue with step 3. Run configuration, migrations, account commands and the API in the same terminal; a new terminal needs the same environment variables again. The application reads the process environment; a `.env` file alone does not configure it. Docker Compose can read its own `.env`, which does not export variables to Python.

### 2A. SQLite — quickest local setup

SQLite ships with Python and needs no database server:

```sh
export DAYCOVER_AUTH_MODE=local
export DAYCOVER_PILOT_BACKEND=sqlite
export DAYCOVER_PILOT_DB="$PWD/var/pilot.sqlite3"
unset DAYCOVER_PILOT_DATABASE_URL DAYCOVER_PILOT_PG_SCHEMA
.venv/bin/python -m scripts.migrate_pilot_ledger
```

The migration creates the parent folder and database if needed. Expected output includes `"schema_version": 7` and `"backend": "sqlite"`. SQLite also checks/applies supported migrations on ledger access. Keep `var/pilot.sqlite3` private; it holds identity, policy, evidence and financial simulation history.

### 2B. PostgreSQL — local persistent service

From the engine folder, configure the bundled database service. Replace the password placeholder with your own local password; do not commit it:

```sh
export POSTGRES_USER=daycover_local
export POSTGRES_DB=daycover_engine
export POSTGRES_PORT=5433
export POSTGRES_PASSWORD='REPLACE_WITH_YOUR_LOCAL_PASSWORD'
docker compose up -d db
docker compose ps db
```

Wait until `db` reports **healthy**. Compose binds it to `127.0.0.1:5433`, stores data in the named `daycover_engine_pgdata` volume and starts only PostgreSQL. The FastAPI server runs separately. Configure Python to use that same service; this constructs a URL with password/user encoding:

```sh
export DAYCOVER_AUTH_MODE=local
export DAYCOVER_PILOT_BACKEND=postgres
export DAYCOVER_PILOT_PG_SCHEMA=daycover_pilot
export DAYCOVER_PILOT_DATABASE_URL="$(.venv/bin/python -c 'import os; from urllib.parse import quote; print("postgresql://" + quote(os.environ["POSTGRES_USER"], safe="") + ":" + quote(os.environ["POSTGRES_PASSWORD"], safe="") + "@127.0.0.1:" + os.environ["POSTGRES_PORT"] + "/" + quote(os.environ["POSTGRES_DB"], safe=""))')"
.venv/bin/python -m scripts.migrate_pilot_ledger
```

Expected output includes `"schema_version": 7` and `"backend": "postgres"`. This applies canonical `migrations/pilot/001_*` through `007_*` in the isolated `daycover_pilot` schema; no manual SQL import or legacy root migration is needed. The database role needs permission to create/use that schema and its objects. PostgreSQL requires explicit migration before API use and never silently falls back to SQLite.

For an existing PostgreSQL server, set `DAYCOVER_PILOT_DATABASE_URL` to its connection URL instead and select `DAYCOVER_PILOT_BACKEND=postgres` explicitly. An optional schema must match `daycover_pilot` or `daycover_pilot_<lowercase_suffix>` (letters, digits and underscores). Always use the same backend, URL and schema for account provisioning, migrations and the API.

### 3. Provision local accounts

A fresh database has no usable customer/reviewer login. Provision identities before opening private API routes:

```sh
.venv/bin/python -m scripts.manage_local_identity create customer_local customer
.venv/bin/python -m scripts.manage_local_identity create reviewer_local reviewer
.venv/bin/python -m scripts.manage_local_identity create weather_local service
```

Human accounts prompt for a 12–128 character password. Save the returned principal IDs locally. Sign in through `POST /api/v1/auth/login`, then use the bearer token in `/docs` via **Authorize**. Follow [onboarding, merchant grants and scoped service credentials](docs/README.md#local-identity-setup-and-onboarding) for customer → reviewer → service setup. A database migration does not seed identities, accept policies or create payouts. These accounts are for local simulation; they do not verify official identities.

### 4. Start the API and check database readiness

```sh
.venv/bin/python -m uvicorn src.daycover.api:app --host 127.0.0.1 --port 8000
```

Open [API documentation](http://127.0.0.1:8000/docs). In a second terminal, check the running server:

```sh
curl --fail http://127.0.0.1:8000/api/v1/ledger/health
```

Expected response (the `backend` is `sqlite` or `postgres`):

```json
{"ready":true,"backend":"postgres","schema_version":7,"mode":"simulation_only"}
```

The ledger endpoint checks the selected database/migration state; a general API health response alone does not establish database readiness. Contract discovery is public; policy, evidence, billing and settlement routes require the appropriate local role and merchant grant. Part 1 clients must call this API with bearer credentials rather than connect directly to the ledger database. See [the integration guide](docs/README.md) for payloads, scopes and simulation boundaries.

### 5. Run checks and stop safely

```sh
.venv/bin/python -m pytest -q
```

Without `DAYCOVER_TEST_POSTGRES_URL`, PostgreSQL parity tests are skipped. To include them, use a **dedicated disposable test database** and export its URL as `DAYCOVER_TEST_POSTGRES_URL` before running pytest. The test role must be allowed to create/drop generated `daycover_pilot_test_...` schemas. Do not use a shared application database for tests.

Stop the API with Ctrl+C. For the bundled PostgreSQL service:

```sh
docker compose stop db
# Later, with the same Compose configuration:
docker compose up -d db
```

Stopping preserves the named volume. Do not use `docker compose down -v` unless you intend to delete that local database. Changing `POSTGRES_USER`, `POSTGRES_DB` or `POSTGRES_PASSWORD` after a volume has been initialized does not change its existing database credentials.

Before upgrading an existing database, stop writers and take a backup (SQLite: the database and any associated WAL state using a SQLite-aware backup; PostgreSQL: `pg_dump`). Migrations are additive/checksummed; retain the matching code/database backup for recovery rather than deleting migration records or editing old migration SQL. Switching the backend selects another store; it does **not** copy your identities, policies or history. The optional `--sqlite-source` command is a limited legacy M1 importer, not a complete migration of current Phase 8 data.

If readiness fails, check that PostgreSQL is healthy, the port/credentials/schema match, and migrations ran with the same environment as the API. A stale shell configuration can select the wrong database. Keep database URLs, `var/`, raw/private datasets and local `prompts.md` out of commits under the existing ignore rules.

Optional ML libraries: `.venv/bin/python -m pip install -r requirements-ml.txt`. Installing them does not supply missing training inputs or validate a model.

## ML sales scope

Use digital sales only. Cash transactions, cash-share estimates and inferred cash income are excluded from the planned ML pipeline. Preserve raw datasets; the upcoming validated adapter must explicitly allow digital payment methods and quarantine unknown methods. Existing cash-inclusive research is historical and must be adapted before reuse. Digital sales must not be presented as total revenue or net income. See [dataset scope](dataset/README.md#ml-input-scope).

## Current state

- **Implemented:** versioned simulation contract; explicit demo acceptance; deterministic rain/haze decisions; exclusions/caps; ingestion validation; durable SQLite/Postgres ledger; audit/revision history; idempotency and reconciliation; local authentication, merchant isolation, eligibility review and optional purpose-specific sales consent; resumable weather ingestion with raw evidence, station history, quarantine, corrections and source health; persisted daily candidates/reviews, versioned closures and deterministic bounded fallback; explicit simulation lifecycle/renewal, reviewed-evidence entitlements and ordered replay; exact simulation billing with authorized mock collections and callback reconciliation; atomic settlement outbox, mock recipient reviews and duplicate-safe mock settlement recovery.
- **Research code exists:** income/weather-impact methods, frequency models, pricing, stress tests and synthetic-data experiments. The supplied CSVs are not yet wired into a validated income-training pipeline.
- **Next development:** Phase 9 versioned engine read models and external Part 1 integration contracts, followed by dataset/model validation. The official rainfall timestamp-verification gate remains open and must be preserved.
- **Not established:** real identity verification, insurer approval, partner transaction access, real premium collection or real payouts.

The active M1 simulation is **70 mm rain → S$30 once per policy year**, haze at **PSI 101 on two days / 151 severe → S$30/60**, a five-day/S$150 haze cap and **S$180 combined cap**. Indicative S$104 annual premium, monthly GIRO proposed only. Other designs remain separate catalogue records. **Rules decide; ML advises; people approve future versions.**

## Local verification

Phase 8: **339 tests passed, one skipped** with SQLite and an isolated PostgreSQL 18 service. The skipped check requires an optional frontend build outside Part 2. Forty-seven settlement checks cover atomic decision/outbox creation, local recipient approval, current-source gates, uncertain reservations, response loss, callback-before-ack, cumulative reversals/partial retries, concurrency, signed callbacks, wallet reconciliation, net-entitlement accounting and migration recovery. Earlier phase results remain in `prompts.md`.

A real local HTTP test with explicit fixture evidence passed: S$60 entitlement/outbox → mock recipient and independent review → queued/uncertain reservation → one reconciled mock S$60 wallet credit → duplicate-safe repeat. Remaining weather cap stayed S$120, real paid stayed zero, and no premium or external/legacy wallet was updated. Temporary test data/services were removed.

**All financial provider activity remains local mock simulation.** No actual recipient verification, bank rail, issuer approval or external wallet bridge is enabled. The official rainfall timestamp gate, real collection/mandate rules and unsupported sponsor funding remain unchanged. See the existing READMEs for stable interfaces and `prompts.md` for the evolving handoff.

Authentication here is a local prototype boundary. Singpass/OTP, official licence verification, merchant transaction connectors and real payment rails remain unavailable. Existing representative-HC demo scenarios require explicit `DAYCOVER_AUTH_MODE=demo`; use a separate local demo database. Legacy global research/dashboard routes are disabled in the default identity mode because they cannot enforce merchant isolation.

## Working boundary

All further work is local in this folder. No GitHub changes, commits, branch operations, pushes or deployment until you explicitly request publication. The active folder is intentionally a standalone Part 2 component, with existing Git metadata left untouched; do not initialize or operate on it during local-only phase work. Future publication must overlay the intended engine files onto the chosen project branch without deleting Part 1.

The unrelated application components and previous documents were preserved in a verified recovery archive under hidden `.local-reference/`. They are excluded from normal development and future publishing; no additional repository was cloned during this separation.
