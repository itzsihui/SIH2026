# DayCover+ Part 2 — Main Intelligence Engine + Dataset

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

## Run locally — no app required

A Python environment is already available in `.venv`. For a fresh setup:

```sh
cd "/Users/ankitasagar/Desktop/ML pipeline"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-daycover.txt -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn src.daycover.api:app --host 127.0.0.1 --port 8000
```

Open [local API documentation](http://127.0.0.1:8000/docs) while the server is running. Contract discovery is public. Private routes require local credentials by default; follow the onboarding/account setup in `docs/README.md`. SQLite is the default; the ledger is stored under `var/`. No mobile app is needed.

For optional ML libraries: `.venv/bin/python -m pip install -r requirements-ml.txt`. Having libraries installed does not supply missing training inputs or validate a model.

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

All further work is local in this folder. No GitHub changes, commits, branch operations, pushes or deployment until you explicitly request publication. The active folder is intentionally a standalone Part 2 component, with no `.git` directory; do not initialize one automatically. Future publication must overlay the intended engine files onto the chosen project branch without deleting Part 1.

The unrelated application components and previous documents were preserved in a verified recovery archive under hidden `.local-reference/`. They are excluded from normal development and future publishing; no additional repository was cloned during this separation.
