# DayCover+ — master prompts, handoff and build checklist

Last updated: 16 November 2026. This is a **local planning file**. Keep all new agent handoffs, phase prompts and progress notes here; do not create more context/conclusion/prompt files. Existing committed project documentation remains reference material. Never store credentials, personal merchant data or payment secrets here.

## Local-only execution rule — applies to every phase and reusable prompt

The user has changed the workflow: **make and test all further changes locally; publish the project folder together on one branch later, only when explicitly requested.** This supersedes earlier publication practices and any standing inference of permission from prior phases.

- Edit local project files, run local tests/services, inspect local code/history and update this local handoff.
- Stay on the current local checkout. Do not stage, commit, create/switch branches, merge, rebase, pull, fetch, push, tag or otherwise change Git history/remotes unless the user explicitly asks for that action later. Read-only `git status`, `git diff`, `git log` and `git check-ignore` are allowed.
- Do not call GitHub connectors or browser automation to create/update PRs, issues, comments, reviews, releases, branches, workflows or repository files. Do not trigger/retry remote CI, merge previous PRs or deploy. No routine GitHub inspection/polling is needed for a local phase; use the recorded historical context and local files.
- Read-only official documentation, dependency downloads and authorized public dataset downloads may be used when needed for local implementation; they do not authorize any remote write or publication.
- Verify locally and report exact local test results. Do not claim fresh GitHub CI results or request a push/deployment decision after each phase. A phase can be complete locally without being published.
- Keep planning/handoffs in ignored `prompts.md` in the canonical Desktop folder. Keep `.gitignore` protections; do not force-add local notes, credentials, generated files or raw/private datasets.
- Existing commits/PRs/remote CI links below are **historical evidence only**. Leave them as they are. They do not authorize another remote operation, and their current remote state has not been rechecked for this policy update.
- When the user later explicitly asks to publish, review the accumulated project changes and local test evidence, then prepare the requested single branch. Publish only the intended project source and permitted artifacts under the existing ignore rules. Do not assume this instruction currently authorizes staging, committing or pushing.

## Active scope — Part 2 Main Intelligence Engine + dataset

This is a focused standalone engine component, **not** the entire DayCover app and **not merely development Phase 2**. Read `README.md`, `docs/README.md`, `dataset/README.md`, `data/README.md` and `scripts/README.md` for the working layout and exact available inputs.

- Own the backend APIs, canonical contracts/ledger, weather validation, dataset preparation, income/impact research, recommendations, future billing/settlement orchestration and read models.
- Part 1 Flutter/web/dashboard/payment sandbox remains external. Do not clone or restore it to implement an engine phase. Build/test engine interfaces with API clients and fixtures; coordinate the external consumer separately.
- Mobile/frontend/.NET sandbox, obsolete legacy `src/engine` tests, publishing scripts and old mixed project documents are excluded from the active tree and preserved in `.local-reference/excluded-components-before-part2.tar.gz`. Some historical notes below describe those original paths; they are provenance, not instructions to recreate them.
- A `.git` directory was observed during the Phase 8 final check; leave it untouched. Do not initialize a repository or run Git operations during local-only phase work. Later explicit publication must overlay intended Part 2 changes onto the chosen project branch without deleting unrelated Part 1 files.
- New developer READMEs explain stable structure; all phase progress and changing handoffs remain in this `prompts.md`. Existing historical project/CI facts below remain dated evidence, not proof that every old component is present here.
- Keep the three supplied CSVs unchanged. Their verified total is 2,216,326 receipt rows; companion generator/profile/weather/summary files mentioned in the original README are absent. Dataset adapters and a full quality/provenance audit remain future work.

**Digital-sales-only ML scope:** exclude cash transactions, declared cash shares and inferred cash income from ML features, labels, baselines, recommendations and evaluation. Accept only explicitly mapped digital payment methods; quarantine unknown/missing methods rather than assume digital. Preserve raw source files and report excluded row counts. Digital sales are observed digital revenue, not total revenue or net income. Historical cash-inclusive research is not an approved pipeline input. Settlement ledger terminology is separate from sales inputs.

## 1. Start here in every new chat

Copy this instruction into a new chat and attach this file if that chat cannot read the local checkout:

> Continue DayCover+ Part 2 Main Intelligence Engine in the local standalone component folder. Read `prompts.md` completely, then the applicable `AGENTS.md`, current code, contract registry and relevant tests. Verify that the working directory is `/Users/ankitasagar/Desktop/ML pipeline`, then inspect the local files and handoff. Existing Git metadata must remain untouched; do not initialize or clone a repository. Treat this file's progress as a dated handoff, not proof that local code has remained unchanged. Do not check or change GitHub as a routine prerequisite. Work on the next unfinished phase whose dependencies are satisfied. Complete implementation, meaningful tests and the handoff before moving to the next phase. Preserve Part 2 research code and keep Part 1 external; use API contracts instead of copying its app. Rules decide; AI explains; humans approve future policy changes. Never imply insurer approval, a partner integration, real collection or real payouts without evidence. Update the checklist and session record in this file only. Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Do not contact anyone based on this file.

**Default next task:** Phase 11 digital-only transaction simulator/statistical baseline. Phase 10's supplied-synthetic dataset foundation is implemented/tested locally; use `data/processed/digital-v1.1/manifest.json` and its split rules, not earlier cash-inclusive research inputs. No model is trained. Foreign candidate files, raw-copy licensing/provenance and real loss observations remain gated; Phase 5 rain timestamp verification is still open.

### Working locations and history

- Current team repository (reported pushed by user): `https://github.com/itzsihui/SIH2026`. Older `harsh-pandhe/sih2026-fin2` links below are historical provenance. Further edits remain local until explicitly requested otherwise.
- **Canonical local working folder:** `/Users/ankitasagar/Desktop/ML pipeline`. All further edits, local services, tests and handoffs must run here. The old Documents checkout is retained as a reference copy; do not continue implementation there.
- Latest app baseline inspected: `app-wallet-gateway`, commit `08fc23f`.
- M1 feature branch: `feature/daycover-m1-pilot`; implementation commit `75a0135`.
- M1 PR: `https://github.com/harsh-pandhe/sih2026-fin2/pull/15`, targeting `app-wallet-gateway`. Historical record: opened and unmerged when last checked. Do not recheck or change it during local-only phase work.
- Research repository: `https://github.com/harsh-pandhe/sih2026-research-findings`.
- Input: Desktop `ML pipeline/pipeline.pdf`, originally uploaded in “Plan Pipeline And Dataset Development”. Pricing/context also came from “Draft Pricing Response”. Treat prior assistant claims as leads to verify.
- Desktop `ML pipeline` now contains only the active Main Intelligence Engine and dataset component, with completed backend M1/Phase 1/Phase 2 code. External Part 1 components and older mixed documentation are in the local recovery archive, not the active project. Work directly here; there is no other master handoff to synchronize.

## 2. Product purpose and boundaries

DayCover+ explores fixed weather benefits for Singapore hawker stallholders. Independent weather evidence and a pre-agreed contract determine eligibility and benefit amounts. Transaction and income models can inform future recommendations and measure protection quality; they do not decide whether to honour an active parametric benefit.

End-to-end target:

`Onboarding + optional data consent → income/weather analysis → recommendation → approved version + customer acceptance → billing → weather monitoring → deterministic eligibility/caps → settlement/reconciliation → customer explanation → research and renewal review`.

### Non-negotiable rules

- Preserve accepted contract versions, effective dates, evidence and the history of decisions.
- No in-force repricing, retroactive benefit reduction or AI-generated claim approval/denial.
- Missing, stale or incomplete weather is unknown/pending, never invented zero rainfall or fabricated official data.
- Digital sales are not total revenue; revenue is not net income. Do not estimate cash income; report digital coverage and margin uncertainty.
- Cash-heavy stalls must retain a fixed-cover route without mandatory transaction sharing.
- Heat, flood and alternative rain triggers stay non-paying research until separately versioned and approved.
- Proposed sponsors, rewards, reinsurance, collection rails and payment providers are not established partners.
- Actual deployment and real money movement need appropriate authorization, controls and verified integration evidence. Keep developing and testing with adapters/mocks while those dependencies are unavailable.
- Do not merge all of `ml-training`, rewrite the latest app, or mix contracts just to make a demo run.

## 3. Frozen M1 simulation contract — do not silently change

Authoritative implementation record: `contracts/daycover-pilot-m1-2026.11-v1.json` and `src/daycover/pilot.py`.

| Field | Selected M1 simulation |
|---|---|
| Version | `daycover-pilot-m1-2026.11-v1` |
| Approval status | Simulation only; not insurer approved |
| Plan | Fixed Haze + Rain |
| Rain | Assigned gauge daily total ≥70 mm; S$30 once per enrolled policy year |
| Haze observation | Maximum hourly regional 24-hour PSI during the Singapore day |
| Haze benefit | PSI ≥151 today: S$60; otherwise today AND yesterday ≥101: S$30 today |
| Haze caps | At most 5 paid days and S$150 per policy year; partial final payment permitted |
| Combined cap | S$180, comprising separate haze/rain subcaps |
| Same-day overlap | Rain and haze may both pay within their separate caps |
| Closures | Scheduled cleaning/works excluded; no cap consumption |
| Missing data | Pending; later evidence may resolve pending decisions |
| Term | Explicit start through day before next anniversary; no automatic renewal |
| Leap day | Feb 28 anniversary in non-leap years; retain explicit convention |
| Rain fallback | Nearest valid within 5 km or pending; historical engine supports it, live evidence integration remains unfinished |
| Indicative price | S$104/year, S$2/week equivalent |
| Billing choice | Proposed monthly GIRO: eight S$8.67 + four S$8.66 instalments = S$104 |
| Collections/subsidy | S$0 collected in M1; no funded subsidy |
| Settlement | Simulated only; no real PayNow transfer |

Other designs must remain distinct registry entries/research scenarios:

- Uploaded architecture's S$150 **combined** cap and four-week/weekly-capped transaction collection.
- Latest wallet/.NET sandbox's 100 mm rain model, transaction collection and S$115 price / S$115–125 recommendations, including waiting-period proposals.
- Historical `src/engine` terms and research cap comparisons.

Choosing one of these later requires an explicit design decision, reproducible repricing, a new version and appropriate approval/customer acceptance. No profitability result transfers automatically between designs.

## 4. What exists and where to inspect

| Component | Location | Handoff status |
|---|---|---|
| Part 1 wallet/QR Flutter app | External component; original path `mobile/daycover_app/` | Excluded from active Part 2 tree; integrate through API contracts |
| Part 2 pilot integration | `src/daycover/api.py` | Test directly with API clients; mobile source is external |
| Part 1 wallet/payment sandbox | External component; original `daycover-pay-system/` path | Archived locally for recovery only; no runtime dependency of Part 2 |
| Unified Python gateway | `src/daycover/api.py` | M1 pilot APIs and separately labelled research routes |
| Pilot decision rules | `src/daycover/pilot.py` | Fixed deterministic rain/haze benefits and caps |
| Pilot durable state | `src/daycover/pilot_store.py`, `ledger_repository.py`, `ledger_migrations.py` | Canonical SQLite/Postgres ledger, atomic period allocation, append-only financial/audit history; isolated from legacy payouts |
| Policy dates | `src/daycover/policy_year.py` | Anniversary helper and leap-day convention |
| Historical rules/replay | `src/daycover/rules.py`, `engine.py`, `data.py` | Research; calendar-year replay is not enrolled-policy settlement |
| Canonical ingestion | `src/daycover/ingestion.py` | Validated NEA v2 snapshots and strict daily aggregation |
| Snapshot job | `scripts/ingest_nea_telemetry.py`, `.github/workflows/ingest.yml` | No invented fallback; snapshots do not settle claims |
| Existing Postgres | `src/daycover/db.py`, root `migrations/` | Legacy PostGIS infrastructure preserved. Canonical pilot schema is separate under `migrations/pilot/`; legacy counters are not migrated into claims |
| Insurer dashboard | `dashboard/src/`, `src/daycover/dash.py` | Research views; operational pilot views remain to build |
| ML/data work | `src/pricing/`, `scripts/train_*`, dataset scripts, research branches | Reuse selectively after provenance/leakage review |
| Engine tests | `tests/` | Current backend tests retained; original mobile tests and GitHub workflow are archived/external |

### Pilot API and environment

- `GET /api/v1/contract`; `GET /api/v1/rules` returns pilot rules.
- `POST /api/v1/policies` (also `/policies`): `stall_id`, `accepted_version`, `consent:true`, optional `start_date`.
- `GET /api/v1/policy/{stall}`; `GET /api/v1/payouts/{stall}`.
- `POST /api/v1/triggers/simulate`: named scenario, stall, optional `event_date`, `rain_daily_mm`, `psi_today`, `psi_yesterday`. Omitted readings use labelled synthetic scenario values; explicit null means missing.
- Decisions carry version, evidence, reason, amount, term, simulation state and remaining coverage. Final duplicate returns the same claim without another disbursement; pending evidence may be retried.
- Pilot storage: SQLite `DAYCOVER_PILOT_DB`, default `var/pilot.sqlite3`; explicit Postgres selection via `DAYCOVER_PILOT_BACKEND=postgres` and securely supplied `DAYCOVER_PILOT_DATABASE_URL`. See Phase 2 for migration/readiness/rollback instructions.
- Pilot mobile: `PILOT_API_BASE`, default `http://127.0.0.1:8000/api/v1`.
- Wallet mobile: existing `API_BASE`, `ENGINE_BASE`, `PUBLIC_BASE`; do not reuse them for pilot APIs or assume the wallet's numeric stall IDs equal pilot `HC...` IDs.
- `/engine/evaluate`, `/engine/replay`, `/events` and `/rules` are research interfaces; do not settle a policy through them.

### Verified M1 baseline, 16 November 2026

- [x] Explicit demo terms acceptance and policy enrolment.
- [x] Mobile → real FastAPI → deterministic S$30 rain simulation → persisted receipt → refreshed S$150 remaining dashboard.
- [x] Duplicate requests cannot add another payout; concurrent duplicate posting tested.
- [x] Haze monetary/day caps, overlap, closures, missing readings and policy term boundaries tested.
- [x] 49 Python tests passed; one React static-mount test skipped because its build was absent.
- [x] Four Flutter tests passed; separately executed real HTTP integration test passed.
- [x] Flutter analysis clean; GitHub PR CI backend/mobile/wire checks passed at handoff.
- [x] Latest wallet app retained and pilot flow labelled separately.
- [ ] Physical Android/iOS device rendering, accessibility and native TTS audio verification.
- [ ] All remaining system phases below. M1 success is not production readiness.

Current limitations: one immutable demo term per stall; no renewal/cancellation workflow; out-of-order earlier decisions behind later payouts return 409 for reconciliation; official daily aggregates do not feed settlement; demo identity is not authentication; wallet and pilot do not share identity/balances; historical weather is labelled with observation dates rather than claimed live.

## 5. How to execute the plan

Work through the core phases in order. Dataset work in phases 10–12 may run alongside the core after shared identifiers and data contracts are fixed; this is a scheduling option, not permission to spawn agents. Research models never block completing fixed-cover infrastructure.

For each phase:

1. Apply the local-only execution rule above. Inspect local implementation and user changes; distinguish missing work from code already present. Do not fetch or inspect GitHub as a routine prerequisite.
2. State the concrete scope and dependencies. Resolve routine implementation details autonomously; ask only about a material unresolved product decision or unavailable authorization.
3. Implement the smallest complete vertical slice in the current local checkout. Preserve existing functionality and old accepted contracts; do not create/switch branches or stage/commit changes.
4. Test meaningful boundaries, failure cases and recovery. Run relevant existing checks; avoid unrelated rewrites.
5. Record changed paths, decisions, exact checks/results, remaining gaps and the next action in section 8.
6. Mark a phase complete locally only when its acceptance criteria and relevant local checks pass. Partial code, mocked provider success and unexecuted tests are not completion evidence. Do not publish, seek routine publication approval or wait for remote CI at the end of a phase.

### Phase 1 — inventory, contract registry and integration decision

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Audit the current app, Python engine, .NET wallet, APIs, datasets and draft pricing. Produce a concise compatibility/authority table inside this file, then implement a version registry and clear separation between production candidates, issued terms and research scenarios. Preserve the M1 registry entry. Recommend an architecture for integrating wallet and pilot and document the tradeoff before changing their responsibilities. Do not approve commercial terms yourself.

- [x] Historical Phase 1 remote verification completed then. For any rerun, inspect local refs, working tree and AGENTS instructions only; do not refresh GitHub state.
- [x] List each active trigger, premium, cap, waiting period, overlap and collection variant with its source.
- [x] Inventory duplicated identities, routes, stores, settlement functions and model outputs.
- [x] Define a canonical policy/version identifier and version-selection rules.
- [x] Separate indicative quote, simulation contract, candidate approval and issued policy states.
- [x] Specify API compatibility and migration approach; retain mobile wallet/QR features.
- [x] Define one decision/settlement authority and adapters for other services.
- [x] Identify decisions needing product/insurer input; progress on independent implementation.

**Done when:** a request selects an explicit supported contract version, research overrides cannot affect an enrolled term, and conflicting app/backend terms are visible and tested. Architecture decisions are captured here.

#### Phase 1 audit and architecture decision (16 November 2026)

Prerequisites completed: read local instructions/hand-off; preserved the existing `.gitignore` edits; verified remote branch SHAs and open M1 PR #15 against local `75a0135`/`08fc23f`; baseline 49 Python tests passed. Work is isolated on `feature/daycover-phase1-contract-registry` above M1. No code was fetched/merged from the research branches and no original M1 contract bytes were changed.

**Contract authority inventory:** `contracts/registry.json` now exposes seven distinct source records through a read-only catalogue. Source summaries are descriptive snapshots, not new approved contracts; the wallet's live config remains mutable inside its separate sandbox.

| Registry version | Trigger / cap / overlap | Price / collection / waiting | Authority |
|---|---|---|---|
| `daycover-pilot-m1-2026.11-v1` | 70 mm, one S$30 rain; PSI 101 two days/151, S$30/60; five haze days/S$150; S$180 combined; perils may both pay | S$104; 12 monthly GIRO instalments proposed; no additional simulation wait | Only executable simulation. Original JSON is hash-pinned; no insurer approval |
| `wallet-sandbox-08fc23f` | 100 mm; rain/haze amounts and monetary limits scaled by premium/115; five haze days; separate peril instructions; optional portfolio pro-rata | Premium formula clamps 0.00066 × annual QR sales to S$40–172, S$115 reference; 13 four-week levy/GIRO cycles; 7-day code wait, 28-day proposal distinct | Existing .NET research sandbox, never a FastAPI policy authority |
| `2026.11-draft2` | 70 mm, S$30 once/calendar year; PSI 101/151 and S$150/five-day haze limit; separate perils; 80 mm shadow/comparison and override scenarios remain research | No price/collection/wait in pure replay | Historical Python replay only |
| `train-2026.11-v1` | 70 mm, two rain days; PSI 101/151 in benefit units; five haze/six total day limits; script-specific overlap requires audit | Model-priced bands, not S$104; seven-day QR activity condition in COVER is not pilot eligibility | Offline pricing/advisory only |
| `legacy-engine-50mm-v1` | Two-gauge mean 50 mm during 08:00–20:00; two rain days; five haze days; S$150 combined; higher single daily benefit | S$115 config; S$0.02/sale capped at S$2.21/week; wait unspecified | Historical `src/engine` prototype |
| `candidate-plan4-150-proposal-v1` | 70 mm rain; proposed severe PSI 201; 3 moderate/2 severe haze-day sublimits; S$150 combined reserving S$30 rain; S$60 daily/rain priority | S$87 model estimate; transaction/four-week proposal; wait unresolved | Unapproved research proposal from separate anniversary-branch document/PDF |
| `candidate-checkout-104-monthly-v1` | Retains baseline 70 mm/101/151/S$180 design | Fixed S$104, 12 monthly levy targets/carry/year-end top-up; cooling-off/eligibility unresolved | `PHASE2_CHECKOUT_PREMIUM_DESIGN.md` and accrual simulator proposal, not the .NET 13-cycle model |

**Duplicated services/data inventory:**

| Area | Current duplication | Decision / migration boundary |
|---|---|---|
| Identity | Pilot `HC...` representative centre IDs; wallet `Stall.Id`/UEN/licence/centre IDs; ML synthetic stall IDs | Separate namespaces. Never infer a merchant mapping from similar names/numbers; Phase 2/3 supplies explicit persisted mappings |
| Terms | Frozen JSON vs mutable Python research defaults, .NET Cfg, ML RULES/COVER and pricing drafts | Frozen registry JSON is the pilot execution source. Other configs are read-only catalogue summaries for pilot consumers |
| Routes | FastAPI `/api/v1/*` and research `/engine/*`; wallet `/api/stalls`, checkout, internal payouts/config; .NET engine evaluate/step | Preserve existing clients. New version-required quote API plus discovery endpoints; no cross-service execution bridge |
| Stores | Pilot SQLite terms/decisions; legacy Postgres stall counters/readings/events/payouts; .NET in-memory wallet/claims/idempotency; research CSV/JSON | Phase 2 builds canonical durable policy/period ledger with migration plans. Do not copy wallet balances or assume seeded policies were issued |
| Settlement | SQLite simulated receipt; legacy `db.record_payout`; .NET `IntPayouts`/`Execute` wallet credits | Pilot simulation ledger is sole authority for pilot posting. Other demonstrations cannot settle a pilot; provider outbox/reconciliation is Phase 8 |
| Models/data | Official climate processing, synthetic stall/QR scenarios, impact/rain/haze models and walk-forward outputs | Advisory only. `train_impact.py` reads synthetic QR history and fills missing rain/PSI; inspect leakage/missingness before reuse in Phase 10–12 |
| Dashboards | Flutter wallet, pilot screens, React historical dashboard, .NET console | Keep labels and sources distinct now; Phase 9 integrates canonical read models after identities, billing and settlement are aligned |

**Architecture decision:** use FastAPI plus the registered deterministic pilot engine as the canonical policy-decision boundary; preserve the current Flutter wallet/QR app and .NET research sandbox. This incrementally reuses the validated Python ingestion/contract/ledger instead of replacing the wallet or importing mutable sandbox terms. Tradeoff: two visibly separate demo flows remain until explicit mappings and adapters are implemented. This is an architecture choice for engineering, not approval of an insurance product or production release.

Adapter contracts for later phases: the wallet supplies authorized receipt read models through a namespaced merchant mapping; it cannot send arbitrary payable amounts into the pilot. ML supplies versioned recommendations/metrics only. The settlement adapter consumes committed policy-linked instructions and reports attempts/outcomes; it never changes benefits. A future gateway reads canonical policy/billing/settlement projections. No wallet bridge or real-provider adapter is enabled by this phase.

**Identifiers and lifecycle:** existing `SIM-POL-...` policy IDs are preserved. `product_version_id` aliases the explicit accepted version; `rule_version` remains for existing clients. A stable `SIM-PERIOD-...` key identifies the enrolled policy/start period. Registry lifecycle (`simulation`, `research`, `candidate_proposal`, reserved `approved`) is distinct from an indicative quote and from `enrolled_simulation`. Real `issued_policy` state is reserved and unavailable. Catalogue visibility does not grant execution/issuance permission.

**API compatibility:** `GET /api/v1/contracts` lists designs/authority; `GET /api/v1/contracts/{version}` returns metadata and executable terms where supported. `POST /api/v1/quotes` requires `contract_version`; quoting creates no policy. `/quote` remains a pinned-M1 compatibility alias and reports `legacy_default_applied`. `/api/v1/contract` and `/api/v1/rules` accept explicit `version` while retaining their M1 default. Enrolment requires `accepted_version`; simulation resolves the enrolled version and rejects a conflicting optional version. Unrecognized policy/quote/simulation body overrides are rejected. `/api/v1/integration` reports authority, lifecycle and identity boundaries.

**Integrity/migration:** M1 canonical terms SHA-256 is `b8e27a5a534f1697dab8a8de1fac2bfd4acad963ec87309654b2c60f8065aa6f`. All rule fields are read from the original JSON, not defaults or mutable compatibility dictionaries. Every policy read, decision and duplicate path verifies the accepted snapshot. Existing M1 snapshots without a hash are verified and read without rewriting their terms/IDs. Different or corrupted terms return a conflict for review. This fingerprint detects version drift; it is not a signature or a substitute for future DB access controls/audit retention.

**Still requiring product/external input:** actual commercial contract, any wait/cooling-off/grace/cancellation/refund rules, revised overlap/caps, approval evidence and customer disclosures, provider/identity access, eGIRO first-payment/retry terms, official-data finality/revisions and funded credits. These do not block Phase 2's schema/repository work. The Phase 1 catalogue has no approved-for-real-issuance products and cannot promote one through an API.

**Verification:** 70 Python tests passed (one unbuilt React static-mount check skipped); six Flutter tests passed; `flutter analyze` clean. Real Flutter→FastAPI HTTP flow passed separately with a fresh temporary ledger: explicit M1 selection, S$30 simulated rain, S$150 remaining and no duplicate. New regressions cover research/default mutation isolation, rejected overrides/unsupported versions, read-only catalogue, corrupt saved snapshots including duplicate path, legacy snapshot compatibility, stable period IDs and mobile version mismatch. Native TTS and the unchanged .NET runtime remain unverified. Published as commit `590278a`, PR #16 (`https://github.com/harsh-pandhe/sih2026-fin2/pull/16`), stacked on M1 PR #15; GitHub PR CI backend/mobile checks (including real HTTP wire test) passed: https://github.com/harsh-pandhe/sih2026-fin2/actions/runs/43762525336.

### Phase 2 — canonical schemas and persistent policy ledger

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Port the pilot's policy/decision ledger to a durable Postgres implementation behind a repository interface while keeping the SQLite demo usable. Reuse existing migrations where appropriate; do not overwrite legacy data or equate legacy stall counters with issued-policy accounting.

- [x] Define merchant, operator, centre, stall, policy, version and period IDs separately.
- [x] Store accepted version/snapshot, effective dates, status, evidence-source assignments and acceptance audit.
- [x] Define observations, aggregates, decisions, payable instructions, settlement attempts, billing entries and audit records.
- [x] Use exact money representation and explicit currency; retain event-date SGT independently of processing timestamps.
- [x] Add migrations/backfill plans, foreign keys, uniqueness and transaction boundaries.
- [x] Lock policy-period allocation atomically; test concurrent distinct events as well as duplicate retries.
- [x] Compare SQLite/Postgres outcomes for the same scenarios; test restarts and rollback on failure.
- [x] Define reconciliation and compensating entries; avoid silent mutation/deletion of financial history.

**Done when:** a restarted service can reproduce policy balances from persisted records and concurrent posting cannot exceed caps or duplicate settlement.

#### Phase 2 implementation and database handoff (16 November 2026)

Branch: `feature/daycover-phase2-ledger`, based on Phase 1 `590278a`. PR #16 was verified open at phase start. Accepted M1 JSON, rules, existing policy IDs and deterministic period IDs are unchanged. This phase changes persistence, not coverage or commercial approval.

**Repository and isolation.** `src/daycover/ledger_repository.py` defines the repository/unit-of-work boundary, shared SQL operations and SQLite/Postgres implementations. `pilot_store.py` remains the API-facing facade. PostgreSQL uses a dedicated `daycover_pilot` schema and never consults legacy public PostGIS policies/counters. SQLite remains the default local demo. Select Postgres explicitly with `DAYCOVER_PILOT_BACKEND=postgres` and securely supply `DAYCOVER_PILOT_DATABASE_URL`; optionally set `DAYCOVER_PILOT_PG_SCHEMA` to a validated `daycover_pilot_...` name. A failed/unmigrated Postgres backend returns an unavailable error; it never falls back to SQLite. Use `GET /api/v1/ledger/health` for pilot readiness; the older health route retains legacy compatibility.

**Canonical schemas.** `migrations/pilot/001_sqlite.sql` and `001_postgres.sql` define:

| Tables | Role and boundary |
|---|---|
| `pilot_merchants`, `pilot_operators`, `pilot_operator_merchants`, `pilot_centres`, `pilot_stalls` | Separate stable IDs/namespaces and foreign keys. Existing HC IDs remain external representative-centre references. Created demo merchant/operator relationships are explicitly `unverified_simulation`, not proof of identity or licensing |
| `pilot_product_versions`, `pilot_policies`, `pilot_periods` | Accepted immutable version content/hash, original snapshot, effective dates/status, gauge/PSI assignment, period currency/cap. API returns distinct merchant/operator/centre/stall-entity/version/period IDs while preserving old aliases |
| `pilot_evidence`, `pilot_decision_revisions`, `pilot_decisions` | Append-only evidence and revision history plus current decision projection. Pending can resolve; final decisions cannot be updated. Covered event day remains separate from timestamp of processing |
| `pilot_instructions`, `pilot_settlement_attempts` | Policy/period/decision-linked simulated instructions and confirmations. Constraints allow only simulation provider/mode. No real outbox/payment execution is introduced |
| `pilot_financial_entries` | Append-only integer-cent allocation, simulated settlement and linked compensation entries; explicit SGD; persistent idempotency keys. Cap usage derives from allocation entries, not mutable cached counters |
| `pilot_billing_entries` | Schema for later obligations/collections/credits/refunds; no bills or real debits are invented in Phase 2. Operational billing remains Phase 7 |
| `pilot_observations`, `pilot_daily_aggregates`, `pilot_aggregate_inputs` | Canonical source/unit/time/quality/revision/coverage relationships. These structures do not imply live official evidence is connected; ingestion/aggregation integration remains Phase 4–6 |
| `pilot_audit`, `pilot_imports`, `pilot_schema_migrations` | Acceptance/decision/correction audit, import fingerprints and checked schema revision |

Financial amounts are stored in integer cents with currency; the old `amount` field on decisions is a generated compatibility projection. Public JSON still uses SGD numbers for existing Flutter clients. Postgres locks the enrolled policy-period row before eligibility/cap allocation; SQLite uses `BEGIN IMMEDIATE`. Decision/evidence/revision/instruction/attempt/financial/audit inserts commit or roll back together. Existing final duplicate requests return the same receipt without a new entry. Pending retries preserve earlier evidence/revisions. New enrolments serialize by stall to avoid duplicate terms.

**Migrations and legacy backfill.** Run `python -m scripts.migrate_pilot_ledger` after choosing a backend. Postgres migrations are explicit, isolated, transactional, schema-locked and checksum-checked; repeated application is safe. For SQLite, first access applies the local additive migration transaction. Existing M1 `pilot_policies`/`pilot_decisions` are retained as `legacy_m1_policies`/`legacy_m1_decisions`, and verified records are copied into canonical tables with unchanged policy IDs, snapshots, acceptance timestamps and receipt JSON. Invalid evidence/amounts, mismatched terms, conflicts or cap excess abort the entire import/DDL transaction rather than silently correcting data. Legacy public Postgres counters are never interpreted as issued policies or imported automatically.

For moving an **original M1-format SQLite backup** to an already migrated target, run `python -m scripts.migrate_pilot_ledger --sqlite-source /path/to/original-m1-backup.sqlite3`. The external source is opened read-only and its snapshot is consistent; imports are fingerprinted/idempotent. Conflicting existing destination terms/decisions are rejected. Already-canonical databases are rejected by this legacy importer: use a verified full database backup/restore for them so revisions/corrections cannot be lost. Do not use this importer as a cross-service wallet migration.

**Backup and rollback procedure.** Before changing a non-test database, take a consistent SQLite backup or managed Postgres backup/snapshot and verify it separately. Migration failure rolls back its DDL/data and SQLite legacy-table renames; source rows remain intact. Once new canonical transactions have been posted, do not switch to old code/legacy tables and assume new payouts are present there. Rollback requires restoring a consistent database/code pair or a separately reviewed forward migration/export of all canonical records. Do not delete a ledger, edit a published migration checksum, drop a shared schema, or overwrite accepted terms to resolve a migration mismatch.

**Reconciliation and corrections.** `pilot_store.reconcile(stall)` reconstructs allocated, simulated-settled, compensated and outstanding cents; history exposes the reconciliation summary. `compensate_simulation(...)` is an internal-only, reasoned/idempotent correction mechanism for a policy-owned simulated settlement. It appends an opposite entry and audit, keeps the original decision/receipt, and marks reconciliation for review. It never restores spent benefit caps, resubmits a transfer or authorizes a real payout. Authenticated operator review and bank reconciliation remain later phases. Database triggers reject update/delete on financial/evidence/audit/history tables and reject edits to finalized decisions.

**Verification.** Full suite with `DAYCOVER_TEST_POSTGRES_URL` pointing to a temporary local PostgreSQL 18 service: **93 passed, one skipped** (unbuilt React static mount). Tests execute the same guarantees on SQLite and real Postgres, compare complete scenario outcomes, exercise concurrent duplicates AND distinct rain/haze events at remaining caps, inject failure after financial posting to prove full rollback, reconstruct from new repository connections, retain pending revisions, check FKs/append-only guards, compensation idempotency, repeat migrations, invalid-import/DDL rollback, unchanged legacy IDs/snapshots/receipts, missing-schema readiness and unavailable-backend behavior. SQLite and Postgres real Flutter→API wire tests passed locally; CI now provisions Postgres 16 and runs both wire backends. Native TTS/.NET execution remain outside this phase. Published as implementation commits `3a5763c` and `519343d` plus discovery-pointer commit `76873f3`, PR #17 (`https://github.com/harsh-pandhe/sih2026-fin2/pull/17`) stacked above Phase 1 #16. GitHub PR CI passed for backend, mobile analysis/tests and both SQLite/Postgres real wire flows: https://github.com/harsh-pandhe/sih2026-fin2/actions/runs/43765132785. `AGENTS.md` now points local continuation to this ignored master handoff; detailed notes remain here only.

**Remaining scope.** One immutable demo term per stall remains; cancellation/renewal and late/out-of-order evidence reconciliation are Phase 6. Demo identities are not authentication. New observation/billing schemas are foundations, not completed ingestion/billing functionality. No real partner account, insurer approval, provider credentials, premium collection or payout has been established. No shared/user database was migrated during this implementation; tests used isolated temporary files and schemas.

### Phase 3 — identity, onboarding, permissions and optional consent

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Replace reliance on demo persona identity with a testable authentication/authorization boundary and canonical stall mapping. Keep mocked identity available only in an explicit demo mode. Build fixed-cover onboarding without requiring sales access; separate optional data permissions from terms acceptance.

- [x] Define customer, operator, reviewer and service roles with tenant/object access checks.
- [x] Add session/token lifecycle, revocation and controlled service credentials.
- [x] Map wallet and pilot IDs explicitly; validate operator/stall relationships and duplicate enrolment.
- [x] Validate location, gauge/PSI assignment, licence/eligibility evidence and acceptance version.
- [x] Add separate purposes/scopes for transaction analysis, retention and revocation.
- [x] Minimise personal data and mask it in responses, logs and model requests.
- [x] Reject cross-merchant reads/writes and unauthorized simulate/admin actions.
- [x] Test onboarding without transactions, unsupported version, expired session and revoked permissions.

**Done when:** one merchant cannot read/change another's records, and a cash-heavy merchant can complete fixed-cover onboarding without transaction access. Real identity-provider availability is documented separately.

#### Phase 3 local implementation and handoff (16 November 2026)

- **Files/boundary:** `auth.py`, `identity_api.py`, `scripts/manage_local_identity.py`, additive `migrations/pilot/002_*.sql`, migration/repository/API integration and `tests/test_identity.py`. Stable setup/routes are in `docs/README.md`; evolving handoff remains here only. Default `DAYCOVER_AUTH_MODE=local` closes private APIs. Explicit demo mode preserves legacy HC scenarios in an isolated database; LOCAL-STALL resources always require credentials. Part 1 remains external and must integrate the bearer/local-ID API; no mobile source was copied or tested in this phase.
- **Accounts/access:** locally provisioned customer/operator/reviewer/service roles, salted scrypt password hashes, opaque tokens stored only as SHA-256 hashes, 15-minute rotating human sessions with an eight-hour absolute limit, logout/all-session revocation, account disable, bounded scoped service credentials/rotation and persisted login limits. No public role-grant endpoint. Merchant grants are rechecked for every request; foreign/unknown objects both return 404. A request already executing is not retroactively cancelled by a later grant revocation.
- **Onboarding:** distinct local merchant/operator/stall IDs; hashed opaque manual/wallet references, duplicate/conflict controls, licence-reference hash and evidence checksum, finite/near-centre location validation, server-owned reference gauge/approximate PSI assignment and explicit supported acceptance version. Independent assigned reviewer records simulation eligibility; explicit terms acceptance then creates canonical policy/period using these identities. These are local, unverified mappings and reviews, not official licence/identity checks. Old HC identities are never automatically assigned to a new account.
- **Consent/privacy:** separate append-only grants/revocations for income baseline, impact research and retention; service scopes + merchant grant + unexpired purpose consent are all required. Analysis does not imply retention. Prototype permission validity defaults to 30 days, maximum 90; retention permission is explicitly 1–90 days, not a legally approved retention policy. No transaction connector/store/purge scheduler exists yet; later adapters must enforce this boundary. Fixed cover works without sales access and remains after optional consent withdrawal. Raw reference values, passwords and tokens are omitted from audit/error/profile responses; identity flows make no model calls. Reference hashes are pseudonymous, not anonymized proof.
- **Existing data:** v1 migration files, frozen M1 contract, supplied CSVs, accepted snapshots, ledger IDs/allocations and original receipt JSON preserved. New schema migration is transactional/checksum checked; injected failure after v2 DDL rolls back on SQLite and real PostgreSQL. Existing user/shared databases were not migrated; tests used disposable files/schemas. The API keeps the historical `pilot` namespace for legacy HC policies and labels new identities `engine_local`.
- **Verification:** full local suite with isolated PostgreSQL 18: **117 passed, one skipped** (absent optional frontend build). Includes both-database no-sales onboarding/enrolment/service simulation, cross-merchant denial, independent review, scope/expiry/revocation, concurrent refresh/duplicate onboarding, absolute session lifetime, consent separation/history and existing-policy migration rollback. A real local Uvicorn/HTTP check separately passed: customer onboarding → reviewer acceptance → fixed cover with zero sales grants → service rain S$30 → S$150 remaining → persisted receipt → revoked logout. Temporary HTTP process/database were removed and temporary PostgreSQL stopped after validation. No Git/GitHub/remote CI/deployment operation occurred.
- **Explicit remaining dependencies:** no real Singpass/OTP/IdP, official licence ownership verification, insurer approval, wallet bridge, transaction-provider connector, production gateway/rate controls, merchant-data retention/deletion job or real payment rail. Eligibility review withdrawal prevents new enrolment; cancellation/renewal of existing terms remains Phase 6. Legacy global research/dashboard endpoints are disabled in local mode because they cannot enforce merchant isolation; clients use scoped policy/history APIs. Phase 4 is next; do not enable real settlement from consent or weather mock data.

### Phase 4 — reliable weather ingestion and provenance

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Extend the validated snapshot parser into resumable official-data ingestion with raw evidence retention, pagination, source metadata, station histories, deduplication, quarantine and outage handling. Keep settlement disconnected until phase 5/6 evidence gates pass.

- [x] Verify current official endpoint schemas/terms before implementing adapters.
- [x] Persist raw payload/reference, fetch/observation times, source, metric, unit, quality and content hash.
- [x] Implement bounded retries/backoff, rate limiting, pagination and resumable backfill.
- [x] Validate timezone, finite/range checks, identifiers, units and expected intervals.
- [x] Differentiate equal duplicates, conflicting corrections and missing observations; retain revisions.
- [x] Record station relocation/availability and mapping effective dates.
- [x] Quarantine invalid input; alert on missing/stale sources without fabricated substitutes.
- [x] Test malformed payloads, timeout, partial pages, retries, late data and source changes.

**Done when:** repeated/resumed ingestion is safe, provenance can reproduce every accepted observation, and failures remain visible without generating qualifying evidence.

#### Phase 4 local implementation and handoff (16 November 2026)

- **Implementation:** `src/daycover/weather_ingestion.py`, rewritten canonical `scripts/ingest_nea_telemetry.py`, additive `migrations/pilot/003_*.sql`, schema-version/readiness updates and `tests/test_weather_ingestion.py`. Existing v1/v2 migrations, M1 terms, Phase 3 access controls and supplied raw CSVs remain unchanged. The old snapshot parser stays available; new ingestion no longer writes the legacy public-database sink. Stable commands/source links are in the existing READMEs; no new handoff files.
- **Verified authority:** official data.gov.sg rainfall/PSI schemas, `date`/`paginationToken`, rate-limit guide and Open Data Licence checked on 16 November 2026. Dataset/API/licence links and attribution are in `docs/README.md`. Parser version `nea-weather-v1-2026.11` is stored per fetch. Rain is five-minute millimetres; PSI is the regional 24-hour index with quarter-hour publication ticks, not a daily aggregate. Rain interval end-labelling and hourly PSI selection still require Phase 5 verification.
- **Persistence/resume:** exact raw bytes (base64/SHA-256/completeness), source/endpoint, fetch/measurement/source-update times, unit/metric, station metadata versions/presence, quality, provenance and revision classification. Page writes and cursor advance are atomic. Equal repeats deduplicate observations; conflicts retain all revisions and raise review alerts, never latest-wins. Completed run replay is a no-op; new run deliberately re-fetches. Failed/quarantined/paused jobs resume their saved source/date/token. Concurrent workers commit one page, retain superseded raw responses and never overwrite a newer checkpoint with a late failure. Backfill covers one requested Singapore day per run, with a configurable bounded page budget; it is not a downloaded full archive.
- **Transport/outages:** fixed official hosts/no redirects, shared persistent two-second throttle across sources/workers, bounded I/O/body handling, three attempts by default (up to five), selected transient retries and persisted Retry-After deferrals. No silent zero/fallback. Raw invalid/partial/stale payloads are quarantined without partial observation writes/cursor advance. CLI status and `--health` expose durable alerts; health distinguishes missing/stale/degraded/available-provisional and never claims settlement-ready. No external alert dispatcher or continuous scheduler is installed. Optional API key stays in a header, outside persisted request metadata/status.
- **Station mapping limit:** location/name changes and absent/nonreporting stations are retained and flagged. Metadata `first_observed_at` is the fetch that first saw that version, not an invented historical relocation date. Historical page metadata may describe a current station; exact official valid-time mapping is unknown and must be reviewed in Phase 5. Existing accepted gauge/region assignments are never rewritten. Presence/observed mapping history is implemented; verified historical relocation dates are an external evidence dependency.
- **Verification:** full local SQLite + isolated PostgreSQL 18 suite **162 passed, one skipped** (absent optional frontend build). The 45 new ingestion checks cover malformed/schema-changed input, timestamps/units/intervals/ranges, raw reproduction, missing/stale inputs, retries/timeout/403/rate deferral, page budgets/cycles/resume, equal/conflicting/late readings, metadata changes/absence, append-only guards, concurrent workers and rollback preserving existing accounts. A threshold-like interval on an enrolled policy creates no decision/payment. No GitHub/remote CI or Part 1 testing was performed.
- **Actual public API checks:** new adapter received HTTP 200 for latest rain (87 readings) and PSI (five regions), retaining 92 provisional observations in a disposable local database. The initial urllib schema probe had returned 403; the implemented HTTP client succeeded without a supplied API key. Separately fetched two bounded historical rainfall pages for 15 November 2026 using a fresh runner/saved cursor: pages 1→2, 4,349 provisional observations, both invocations correctly paused at their budget, zero financial entries. This validates resume, not full-day completeness or a full backfill. Temporary databases were removed; the test PostgreSQL service was stopped after validation. No user/shared database was migrated.
- **Next:** Phase 5 persisted Singapore-day aggregation, closure versions and approved fallback/finality gates. Reuse all raw/provenance revisions; explicitly handle conflicts and unknown station effective dates. Do not feed provisional observations or the older pure `daily_summary` helper directly to settlement. Still no real identity/insurer/transaction/payment partner or real payout.

### Phase 5 — daily aggregates, closures and fallback evidence

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Build persisted, versioned Singapore-day aggregates from canonical observations. Document and test interval semantics, coverage rules, revisions and geographic fallback. Do not label a snapshot a daily total or historical sampled dates a full archive.

- [ ] Verify rain end-of-interval convention against authoritative source documentation before operational use.
- [x] Calculate daily rain from validated intervals; retain expected/observed bins and missingness.
- [x] Calculate daily maximum hourly regional 24-hour PSI and previous-day evidence.
- [x] Distinguish complete/final, incomplete/pending, corrected and rejected aggregates.
- [x] Implement assigned-gauge then approved nearest-valid-within-5-km fallback with reproducible tie-breaks.
- [x] Record selected gauge, assignment, distance, reason, quality, version and source references.
- [x] Version centre closures and resolve late closure corrections under explicit review rules.
- [x] Test midnight/year boundaries, UTC conversion, missing bins, stale data, station outage and conflicting corrections.

**Done when:** every daily input is traceable and completeness-qualified; missing data cannot turn into zero or a final denial; fallback decisions are deterministic and disclosed.

#### Phase 5 local implementation and handoff (16 November 2026)

- **Status:** local implementation and tests are finished; the first checklist item above stays **open**. Official NEA/MSS/data.gov.sg pages were checked, including hourly PSI reporting. Exact five-minute API rain timestamp/window labelling could not be verified from authoritative material found. `RAIN_TIMING_VERIFIED=False` is a hard finalization gate with no environment/CLI override. Never mark that source convention verified from third-party examples, numerical agreement or local reviewer approval. A future confirmed interpretation must carry an authoritative citation and a new method version.
- **Files:** `daily_evidence.py`, `evidence_api.py`, `scripts/daily_weather_evidence.py`, additive `004_*.sql`, schema/readiness v4 updates and `tests/test_daily_evidence.py`; existing READMEs describe stable commands/interfaces. Older migration fixtures were extended to remove all newer empty tables only in their disposable test schemas. v1–v3 migration files, frozen M1, existing ledger/source records and supplied CSVs remain unchanged; the older pure summary helper now labels its rain convention as research only.
- **Daily evidence:** method `sgt-daily-v1-2026.11`; rain candidate sums 288 end-labelled bins (00:05 through following midnight) with decimal arithmetic, under the unverified-method gate. PSI takes the maximum of 24 exact on-the-hour regional 24-hour PSI readings in SGT; quarter-hour spikes are ignored. Previous-day evidence is separate. Missing/conflicting/rejected bins, unfinished days, incomplete acquisitions, missing raw proof, unreviewed/revoked/mismatched effective station mappings and unverified timing remain pending; candidate values never become usable final values by themselves.
- **Review/revisions:** immutable candidates/projections/observation links, fingerprints, provenance and method versions. Locally provisioned active reviewers can bind a metadata version to an explicit inclusive date range, choose/reject an exact observation revision set, and finalize/reject a current qualified day. New observation, mapping or resolution inputs invalidate the current approval; old final rows/history stay intact. Rebuild before reviewing changed data. Ingestion source alerts remain conservative source history and are not deleted by local aggregate reviews. Local finality is a reviewed snapshot, not official permanent source finality or insurer approval.
- **Closures/fallback:** explicit sourced open/cleaning/works facts retain document checksum, payload and supersession. Late corrections stay pending until current-version review; rejected corrections do not imply open. No automatic verified-open calendar is inferred. Selection prefers a valid current assigned gauge, otherwise approved/final gauges within frozen 5 km of stall coordinates; exact distance then station ID breaks ties. It records assigned/selected gauge, distance/reason, considered candidates, quality, method/raw/review references and closure/current/previous PSI. Operational final rain/fallback remains gated; eligible-rain branches were exercised only with a test-only verified-method fixture.
- **Integration/security:** `GET /api/v1/evidence/{stall_id}/{day}` is bearer-protected, merchant-scoped and read-only. Trusted local admin CLI builds/reviews/persists selections; reviewer-ID checks there are not remote authentication. API returns current qualification rather than blindly reading an old final SQL row. All outputs retain `settlement_ready:false` / `financial_effect:false`; no weather or closure operation creates/reverses financial entries or changes accepted caps. Existing synthetic simulation endpoints remain separate until Phase 6.
- **Verification:** **199 passed, one skipped** with SQLite and isolated PostgreSQL 18; 37 new Phase 5 checks. Covers full/missing bins, rain method gate, hourly PSI, previous day, midnight/year/leap boundaries, revisions/late correction, reviewer/mapping gates, incomplete acquisitions, deterministic five-km fallback/ties, closure corrections/rejection, current fingerprint invalidation, concurrent builds, append-only evidence, migration rollback preserving raw data and merchant isolation. Fixture-based real local Uvicorn/HTTP smoke passed: reviewed PSI=151 and explicit reviewed open closure; missing previous day pending; unauthorized/foreign requests denied; zero selection/financial writes from GET. Test server/files/schemas were disposable; PostgreSQL was stopped. No real dataset values, station-validity dates, closures or approval were fabricated for actual merchants.
- **Next dependency/phase:** obtain authoritative confirmation of rain interval label convention before lifting its final-evidence gate. Actual historical station-validity approvals and closure source reviews also require evidence; no production reviewer/issuer is claimed. Phase 6 should consume the current service's `usable_value` and current qualification, not arbitrary old final SQL rows; preserve pending rain and explicit simulation/real-settlement boundaries. Keep all further work local/unpublished.

### Phase 6 — policy lifecycle and official-evidence decision engine

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Connect enrolled policies to persisted final weather evidence through one deterministic engine. Add explicit lifecycle/renewal handling, cap accounting and controlled late-data reconciliation. Keep payment execution separate.

- [x] Validate active term, plan/version and exclusions before creating payable decisions.
- [x] Count benefits by covered event date and policy period, never settlement year alone.
- [x] Support explicit issue/renewal/cancellation/expiry state transitions with recorded effective dates.
- [x] Define waiting-period/endorsement handling only if selected terms require it; do not import sandbox proposals.
- [x] Enforce per-peril, day, monetary, overlap and combined caps atomically.
- [x] Handle out-of-order events and pending evidence through ordered replay/review with auditable adjustments.
- [x] Preserve prior decisions and issued versions when evidence is corrected.
- [x] Compare full replay versus sliced/restarted replay; test leap days, anniversary boundaries and cancellation.
- [x] Keep legacy calendar-year research output clearly separate from policy settlement.

**Done when:** identical policy/evidence versions produce identical decisions, restarts/replay do not restore spent caps, and no payment can bypass the policy-ledger decision.

#### Phase 6 local implementation and handoff (16 November 2026)

- **Scope/status:** implemented locally for the frozen M1 **simulation** contract. Actual issuance/payment stays unsupported. Phase 5 rain timestamp verification remains open; production reviewed-source rain stays pending. Eligible-rain overlap branches were exercised only with a clearly test-only verified-method fixture. No actual weather/identity/licence/closure/partner approval is manufactured.
- **Files/schema:** `policy_lifecycle.py`, `evidence_engine.py`, `lifecycle_api.py`, additive `migrations/pilot/005_*.sql`, repository/facade/evidence-selector/API scope integration and `tests/test_evidence_engine.py`. Schema/readiness is v5. Existing migrations v1–v4, frozen M1, original snapshots/receipts and supplied CSVs remain unchanged. Existing terms backfill without claiming activation; old decision periods become `synthetic_demo`. New policy creation registers an immutable initial engine term. Old rollback fixtures remove all newer empty tables only in their disposable schemas.
- **Lifecycle:** explicitly accepted term/period snapshots; reviewer `activate_simulation`, prospective inclusive policy-wide `cancel_simulation`, and `record_expiry` events. Activation at inception supports historical simulation, not backdated real insurance. Customer/operator renewal explicitly accepts the next anniversary/version and creates a separate cap period, never overwriting old terms. Feb-29 anniversaries follow Feb-28 in non-leap years and revert in leap years. Each renewal needs activation. Cancellation is non-backdated, disables later coverage/renewal/reactivation, and does not execute refunds/financial reversals. No unsupported waiting/grace/lapse/endorsement/mandate rules were invented. Product cancellation/refund rules for actual insurance remain unapproved/open.
- **Decision authority:** source selector runs in the same policy-locked transaction with an explicit accepted term context. Validate contract/version/hash, period ID/version/anniversary bounds, active state, current closure and current final-evidence fingerprints. The existing registered `pilot.decide` remains the benefit-rule calculator. Unknown evidence remains pending; acute PSI does not require yesterday, while the two-day tier requires separately qualified previous-day data. Qualified closure exclusions suppress without cap consumption. Original legacy research and synthetic scenario paths do not become official evidence.
- **Ledger/mode boundary:** one immutable mode per period (`synthetic_demo` / `reviewed_evidence`), no silent mixing/conversion. Reviewed decisions append immutable revisions, positive integer-cent cap reservations and signed net entitlement entries. Counts use unique peril/covered days in the accepted period; top-ups do not consume another haze day, and January never resets a term. Reservations are monotonic. This engine creates **no payment instructions, settlement attempts or settlement financial entries**; execution stays `NOT_SUBMITTED`, disbursed=false. Old named synthetic triggers retain their historical simulated ledger and original demo-term boundary; they cannot post into a reviewed-evidence period.
- **Corrections/replay:** changed finalized or out-of-order assessments append `review_required` without altering entitlement. Service prepares a chronological plan from term inception (≤366 days), bound to current source/lifecycle/ledger fingerprints; assigned reviewer approval is atomic/idempotent and stale plans fail. Reviewed factual corrections append signed simulation entitlement adjustments while preserving prior decisions, accepted rules, consumed caps and all entry history. Pending corrected evidence retains prior entitlement. Downward adjustments never release cap or create a clawback. Positive targets can be constrained by previously consumed cap, so a theoretical reordered target is not a promise to reallocate spent capacity; funding exceptions/real settlement reconciliation remain later work. Future payment logic must reconcile net entitlement against net settled amounts, not send every positive entry as a new transfer.
- **Interfaces/security:** stable endpoint/body/scope examples are in `docs/README.md`. Reviewer scopes `policy:manage`/`decision:review`, service `decision:evaluate`, customer/operator explicit renewal via `policy:enrol`; all new HTTP routes require bearer + merchant grant. Re-login/reissue credentials for new scopes; existing tokens do not gain them automatically. No client-supplied weather/amount/counters. Existing coverage and evidence read routes understand accepted renewals; lifecycle/history expose all terms. Legacy payout history preserves receipts and separately labels new unsubmitted entitlement totals. Ledger-wide/source admin operations remain trusted local boundaries, not a real IdP/issuer.
- **Verification:** **241 passed, one skipped** on SQLite and isolated PostgreSQL 18; 42 Phase 6 checks. Covers qualified PSI/rain-pending, two-day PSI, per-peril/day/money/overlap caps, no New Year reset, duplicates/concurrency, full vs sliced/restarted equivalence, out-of-order/late-data plans and stale-plan rejection, top-up day counting, monotonic caps after negative corrections, renewal/leap anniversaries, cancellation/expiry, period metadata mismatch fail-closed, immutable records, v5 migration rollback preserving v4 receipts/caps, scoped APIs and forged-payload rejection. Real local Uvicorn/HTTP fixture smoke passed: scoped activation → PSI entitlement S$60 → rain pending → S$120 remaining → duplicate safe; foreign/customer evaluation denied; zero payment instructions/attempts/financial settlement writes. Temporary API/files/schemas removed and temporary PostgreSQL stopped after validation. No user/shared database migration, Part 1 code copy/test, GitHub/remote CI or publication operation.
- **Next:** Phase 7 selected S$104 simulation billing schedule/collection bookkeeping with mock provider and explicit unresolved commercial rules. Preserve the rain gate, immutable terms, mode separation and entitlement/payment boundary. Phase 8 will own settlement orchestration/reconciliation; no current real payout is implied.

### Phase 7 — billing and collection reconciliation

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Implement the selected S$104 annual obligation and exact monthly schedule as a billing ledger. Keep a provider interface with a deterministic mock. Model transaction-linked/four-week collection as a separate candidate only if explicitly selected later.

- [x] Generate eight 867-cent and four 866-cent bills with explicit due-date/anniversary convention.
- [x] Separate owed, due, collected, pending, failed, refunded and sponsor-funded amounts.
- [x] Define first-payment, mandate, retry, grace/lapse and refund behavior as open product decisions where not specified.
- [x] Store authorized collection attempts and reconcile outcomes idempotently.
- [x] Test duplicate/out-of-order callbacks, failed/partial payment, retry, reversal and wrong references.
- [x] Show customer schedule, balances, mandate status and explanation without claiming a debit occurred.
- [x] Conditional funding gate: M1 subsidy remains zero; no sponsor is approved. Funded-credit implementation is deferred until approval, with eligibility/cohort cap/sunset required then. No funding is fabricated.
- [x] Verify illustrative collection-cost and hypothetical net-income-share arithmetic separately from risk premium; actual fee quotes/customer affordability remain unverified.

**Done when:** all 12 bills total S$104 exactly, retries cannot overcollect, outstanding amounts reconcile, and simulation/provider status is visible.

#### Phase 7 local implementation and handoff (16 November 2026)

- **Scope/files:** `billing.py`, `billing_provider.py`, `billing_api.py`, additive `006_*.sql`, schema/readiness v6, role/API/facade integration and `tests/test_billing.py`. Migrations v1–v5, frozen M1, accepted terms, receipts/entitlements/caps and supplied CSVs are preserved. Existing billing entries are not guessed/imported into a new schedule. Old migration rollback fixtures remove newer tables only in their disposable databases.
- **Schedule:** exactly eight 867 + four 866-cent obligations per explicitly accepted term, S$104 total. Versioned **simulation** due convention anchors each date to term inception and clamps independently in shorter months; renewal gets its own schedule. First projected bill is at inception, but actual first-payment/debit-date approval remains open. Obligations/collections are separate; no unpaid-bill lapse, cancellation proration, refund entitlement or automatic retry is inferred.
- **Permission/provider:** customer/operator separately grants/revokes term-bound `mock_collections_only` permission; it is neither terms acceptance, sales consent nor real GIRO. Service uses `billing:collect`/`billing:reconcile`, reviewer `billing:review`, all with merchant grants/fresh scopes. Attempts derive only projected-due outstanding/unreserved amounts and persist intent before the provider boundary. Provider interface has one enabled local deterministic mock; no banking/network adapter. Mock state/signing secret persists locally, never appears in responses/logs/handoff, and must never be treated as a real provider credential.
- **Reconciliation/recovery:** submission does not collect. Immutable signed cumulative mock snapshots bind attempt, bill, provider reference, SGD amount, event ID/sequence and authorized returns. Equal events deduplicate; old events stay stale; wrong signatures/references, inconsistent terminal changes and overcollection are quarantined. Timeout/submitting/pending reserves remain until outcome is known. Recovery reuses the same provider job; callbacks before acknowledgements cannot regress confirmed status. Receipts, signed billing entries, provenance and audit post atomically. Revocation cancels unsent work; already submitted outcomes still reconcile even after expiry/revocation, with no new call after permission loss. No automatic retry/collection scheduler is installed.
- **Balances/returns:** show owed/due/future outstanding, gross vs retained mock collection, pending reservation, failed-attempt volume, partial remainder, refunds/reversals and zero sponsor funding. Confirmed returns reopen mock outstanding; gross may exceed annual price after returned/recollected funds, but retained net can never exceed a bill/S$104. Explicit reviewer-authorized **mock-only** full retained return is bounded/idempotent and is not real refund eligibility. Unapproved linked credits fail reconciliation; no sponsor ledger/funds are invented. Billing never changes climate caps, entitlements, coverage state or payout entries. Existing policy fields retain real collection zero and add labelled `mock_billing`; separate billing errors do not block coverage reads.
- **Economics:** read-only cost scenarios reproduce the draft assumptions (20-cent success + 5% one-extra S$1 failure → S$3 monthly versus S$13 unselected weekly comparison), not current bank quotes or actual billed fees. Hypothetical S$500/1,000/1,500 monthly **net income** inputs illustrate premium share; no cash/digital-receipt inference or actual affordability/risk-price verification is claimed. Frozen annual price and modeled risk/other costs stay separate. Real mandate/classification/fees/first payment/grace/lapse/proration/refund policy require later product/provider evidence.
- **Verification:** **292 passed, one skipped** with SQLite + isolated PostgreSQL 18; 51 Phase 7 checks cover calendar schedules, authorization, duplicates, failed/partial/unknown outcomes, out-of-order return-before-confirmation, wrong callbacks, response-loss recovery, callbacks before acknowledgements, atomic posting/DDL rollback, concurrent reservations, twelve-bill annual net limit, renewal/cancellation, append-only history, unsupported credit, scoped APIs and illustrative arithmetic. Real local HTTP mock smoke passed: twelve bills/S$104 → separate mock permission → submitted but uncollected → one confirmed mock S$8.67 → S$95.33 mock outstanding → duplicate-safe reconciliation. Foreign/customer charge attempts denied; real collected stayed zero, coverage cap S$180 unchanged, no entitlement/payout writes. Test API/files/schemas were disposable; temporary PostgreSQL stopped. No user/shared DB migration, actual debit/refund, GitHub/remote CI/deployment or dataset edit occurred.
- **Next:** Phase 8 mock settlement outbox/adapter for Phase 6 net entitlements. Keep premium collection and benefit settlement separate; preserve monotonic caps, source qualification/rain gate and real-operation gates. Never pay each positive entitlement entry independently of net adjustments/already settled amounts. Commands/routes and exact operational limitations are in existing READMEs; evolving handoff stays here only.

### Phase 8 — settlement orchestration and reconciliation

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Add a transactional payable-instruction/outbox flow and settlement adapter. Use simulated settlement until explicit real-provider authorization and credentials exist. Recover safely from timeouts and duplicate callbacks.

- [x] Link instruction to immutable policy/period/decision/evidence versions and independently reviewed local mock recipient reference; actual verification remains unavailable.
- [x] Define pending, queued, submitted, uncertain, confirmed, failed and reversed states.
- [x] Persist decision/outbox in one database transaction; separate entitlement from bank confirmation. This is not a Git commit.
- [x] Use persistent idempotency keys, retry policy and provider-reference reconciliation.
- [x] Handle crash after submission, timeout with unknown result, callback before response and duplicate callback.
- [x] Prevent sandbox wallet double-credit and accidental real-rail use.
- [x] Record audit trails and operator actions without exposing account secrets.
- [x] Test both successful mock settlement and failures that leave entitlement/balances correct.

**Done when:** no transfer is called paid merely because submission returned; recovery cannot double-pay; confirmed outcomes reconcile to instructions and the customer sees honest status.

#### Phase 8 local implementation and handoff (16 November 2026)

- **Scope/files:** `settlement.py`, `settlement_provider.py`, `settlement_api.py`, migration `007_*` and recovery/API tests; schema v7. Frozen M1 and migrations 001–006 remain unchanged. Premium billing is separate.
- **Atomic authority:** accepted engine decision/adjustment and immutable outbox share a transaction. Migration backfill creates pending records only. Queue binds accepted term/contract/period/decision/source context and independently reviewed mock recipient; amount is current signed net entitlement less confirmed mock cash and unresolved reservations. Never pay every positive entry separately; spent benefit caps remain monotonic.
- **Recipient boundary:** only hashed `MOCK-` aliases, independently reviewed for local simulation, with generated local wallet IDs. Actual recipient verification is false. No external/Part 1 wallet bridge, live rail, real account or bank call exists.
- **Recovery:** durable dispatch intent precedes provider invocation; response loss retries the same instruction/reference, at most three manual submissions then reconcile only. Unknown/pending outcomes hold reservations. Source/recipient changes cancel only never-dispatched instructions; in-flight outcomes require reconciliation before rerouting.
- **Posting:** signed cumulative mock callbacks validate identity, recipient/review, currency, sequence and amount. Receipt, signed mock cash, unique local wallet mirror and audit post atomically. Duplicate/old callbacks cannot recredit; reversal-before-confirmation and callback-before-ack are safe. Partial/failure/reversal permit only remaining net value. In-flight overpayments surface for review, never automatic clawback or cap restoration.
- **Verification:** **339 passed, one optional absent-frontend skip**, SQLite + isolated PostgreSQL 18; **47 Phase 8 checks** including transaction rollback, retries, concurrent requests, invalid callbacks, adjustments, recipient/source changes, migration recovery and reconciliation. Local HTTP fixture flow: accepted PSI evidence → S$60 entitlement/outbox → mock recipient review → timeout/reserved S$60 → reconcile one mock S$60 local wallet credit → duplicate safe; cap remaining S$120 and real paid zero. The weather evidence was an explicit test fixture, not live verified ingestion.
- **Cleanup/limits:** temporary API/files/test schemas removed and PostgreSQL stopped. No user/shared database migration, CSV/model rewrite, actual transaction, Git operation, GitHub write, remote CI or deployment. Readable setup/API contracts are in existing READMEs; all evolving handoff remains here.
- **Next:** Phase 9 versioned read models and integration payloads for the external Part 1 owner, tested with API clients/fixtures here. Do not clone/rebuild Part 1. Preserve source, commercial and real-operation gates.

### Phase 9 — engine read models and Part 1 API integration

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Build versioned engine read models and API contracts for the external Part 1 app/dashboard. Test with engine API clients and fixtures; do not copy or rebuild the mobile/dashboard code here. Document payloads, identity mappings, errors and simulation labels for the Part 1 owner.

- [x] Replace ambiguous IDs/duplicate state with explicit mappings and versioned API models.
- [x] Show accepted terms, start/end, policy status, gauge/region and observation freshness.
- [x] Show remaining rain/haze/day/combined caps and explanatory decisions, including pending/non-paying cases.
- [x] Show bills, collection status, payout progress and reconciled receipts.
- [x] Add operator views for ingestion gaps, pending decisions, exceptions and reconciliation queues.
- [x] Protect reviewer actions and display source/version evidence for every override/review.
- [x] Test API timeout/retry/error/expiry behavior and identity isolation; document expected handling for external Part 1 screens.
- [x] Supply documented language/status/error payloads and a Part 1 integration checklist; physical UI/accessibility/TTS verification belongs to the external Part 1 owner.
- [x] Run real HTTP engine integration tests with client fixtures against the canonical backend; do not require a local Flutter checkout.

**Done when:** versioned engine APIs let external merchant/operator clients trace the same policy, weather evidence, decision, cover and settlement status, with locally verified fixtures and integration examples.

#### Phase 9 local implementation and handoff (16 November 2026)

- **Files/API:** `read_models.py`, `read_models_api.py`, API/discovery wiring and `tests/test_read_models.py`; `daycover.part2.v1` schema with explicit identity/policy/cap models in OpenAPI. GET term directory, explicit term/day merchant view and role-restricted operations view under `/api/v1/read-models`. No migration; canonical schema remains v7 and frozen contract unchanged.
- **Authority/read safety:** one policy-locked transaction reuses canonical evidence/billing/settlement projections. GET creates no decision, bill, evidence selection, provider job or transfer. Exposes accepted version/hash/start/end/current and event-day state, canonical identity mappings, gauge/PSI region, live feed freshness distinct from historical review, missing source bins and bounded fallback.
- **Honest displays:** remaining rain/haze/day/combined caps, pending/unevaluated/non-paying reasons, original decision evidence plus current-context match, projected/stored bills, net entitlement versus reserved and confirmed mock amounts. Historical decision write-time flags never replace current settlement state. Up to 100 validated mock receipt snapshots with truncation marker; do not sum cumulative receipts. Real paid/collected zero, no external wallet bridge or real identity verification.
- **Operations:** merchant-scoped source gaps, pending/unevaluated decisions, settlement/reconciliation queues, exceptions and replay/recipient/lifecycle review references. Read access grants no review or dispatch action; existing separately scoped APIs/trusted evidence CLI remain authoritative.
- **Integration contract:** existing READMEs document routes, IDs, cents/count units, schema/status language, sanitized 401/403/404/409/422/503 errors, GET-only timeout/backoff, stale/out-of-order frontend handling and external Part 1 checklist. No Flutter/UI copy/build; physical accessibility/TTS/localization/device validation remains external and unclaimed.
- **Verification:** **360 passed, one optional absent-frontend skip**, SQLite + isolated PostgreSQL 18; **21 Phase 9 checks** including no-write reads, missing/closed sources, corrections, confirmation/reversal, billing separation, service scopes, revoked/foreign access, safe unavailable-ledger errors, renewal isolation and OpenAPI types. Real local HTTP consumer tests passed on both backends with an injected client timeout, safe GET retry and expired session. Temporary HTTP processes/files/schemas removed; PostgreSQL stopped.
- **Scope preserved:** digital-only ML requirement recorded, no CSV/model rewrite, user/shared DB migration, real operation, Git action, GitHub write, remote CI or deployment. Existing cash-inclusive research is historical and must be adapted before ML reuse. Rain timing verification is still unresolved.
- **Next:** Phase 10 dataset manifest, quality/provenance audit, digital payment allowlist/filter and reproducible derived datasets/splits. Do not start training or regenerate supplied CSVs merely because source scripts exist.

### Phase 10 — dataset foundation (may overlap after phases 1–2)

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Build a reproducible dataset pipeline using existing research assets. Audit source coverage/licences before downloading or distributing. Keep observed records, calibrated synthetic examples and assumptions distinguishable.

- [x] Create manifests with source, access date, licence, attribution, checksum and schema version.
- [x] Inventory rain/PSI, centre metadata, closures, WBGT/flood and transaction candidates.
- [x] Document that the historical rain sample is not exhaustive daily coverage.
- [x] Evaluate original F&B research datasets referenced in the pricing chat, including Mendeley `kcgf45y24m/2`, `9hntk3wbwc/1`, `bfkvybtpj6/2`, and Café Data 2.0; verify publisher metadata/described contents and declared licences rather than repeating earlier claims; raw-file inspection, digital eligibility and supplemental-data reuse remain explicitly gated before import.
- [x] Define receipt, line-item, refund, payment type, trading day and observation-quality schemas; enforce an explicit digital-method allowlist, exclude cash and quarantine unknown/missing methods.
- [x] Keep provenance classes: observed foreign, official Singapore, calibrated synthetic, consented Singapore.
- [x] Normalize currencies/timezones/merchant identifiers without relabelling foreign shops as Singapore hawkers.
- [x] Create time/merchant split manifests before feature generation; prevent receipt/line-item duplicate leakage.
- [x] Add quality reports, rejection reasons, reproducible builds and small safe fixtures; keep large/raw/private data out of application Git history.

**Done when:** another engineer can rebuild a documented dataset version and distinguish measured facts from simulated local assumptions.

#### Phase 10 local implementation and handoff (16 November 2026)

- **Files:** supplied-synthetic streaming adapter `src/daycover/dataset_pipeline.py`; build/inventory CLIs in `scripts/`; `configs/dataset-v1.json`, `schemas/dataset-v1.json`, `data/sources-v1.json`, 29 dataset tests and existing README updates. No policy contract, migration or engine financial behavior changed.
- **Full build:** latest ignored output `data/processed/digital-v1.1/`; build ID `4b2f4d792ea8826b106a1b3f6cab2abfc5fc9d28b1cd8cf4dada983ee9ad9bcc`. All **2,216,326** source receipts scanned: **775,772 digital** (729,330 SGQR_NETS_SIM + 46,442 OTHER_DIGITAL_SIM), **1,440,554 cash excluded**. All source flags are non-refund; no duplicate/conflicting IDs or inconsistent merchant metadata found. Original CSV SHA-256 values unchanged. Trial outputs from this turn were removed; keep the final version and inventory.
- **Artifacts/gates:** digital receipts, source/config/adapter/output checksummed manifest, quality report, split manifest and hashed quarantine log. Exact positive cents, SGT timestamp/date, identity/region/provenance checks; no date-only invented midnight. Unknown/missing/mixed tender, invalid amounts and unlinked refunds quarantined. Duplicate IDs keep one; conflicts remove original/variants; inconsistent merchant groups excluded. Counts must reconcile. Source/config/adapter mutations discard unpublished builds; never overwrite a version. No cash/share/margin features, total-income extrapolation, zero-sales fill, weather joins or trained model.
- **Splits:** train before 2025-09-01; validation through 2025-10-31; test from 2025-11-01. Seeded merchant hash holds out 23/100 synthetic merchants in this build, all their dates excluded from training. Counts: **403,423 train / 88,511 validation / 92,980 test / 190,858 merchant holdout**. Holdout retains time-window labels for later future-window evaluation. Fit transforms/models on `split=train` only; foreign line items must group source+merchant+receipt before splits.
- **Source inventory:** ignored `data/processed/digital-source-inventory-v1.json` inventories 15 local artifacts. Main rain sample: 43,329 station-day rows on 701 dates, not full daily coverage; WBGT mapping is not an observed archive. Source-copy origin/licences remain unverified where no proof is present. Primary Mendeley pages/ Café article evaluated in source catalogue; no foreign raw files downloaded/imported and no foreign digital eligibility approved. No consented Singapore merchant microdata or synthetic-to-real centre mapping exists.
- **Verification:** **389 passed, one optional absent-frontend skip**, SQLite + isolated PostgreSQL; 29 dataset tests. Two fixture builds match byte-for-byte. Independent full output scan verified all 775,772 unique digital IDs, exact cents, allowed methods, canonical provenance, split membership and merchant isolation; manifest source/output checksums matched. Temporary PostgreSQL stopped, disposable test services/files/schemas cleaned. Raw CSVs, existing models and user/shared application DBs unchanged; no Git/GitHub/remote CI/deployment or actual financial operation.
- **Next:** Phase 11 digital-only baseline/simulator using the final manifest and training split. Reuse no cash-inclusive model assumptions. Missing sales days are unknown without verified trading/payment/closure context. Foreign adapters, verified data licences/consent, refund linkage and empirical weather-loss labels are prerequisites for their respective future uses, not fabricated approvals.

### Phase 11 — transaction simulator and statistical income baseline

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Build or adapt a simulator and a simple comparable-day/hour baseline before complex ML. Calibrate only to verified observations/aggregates and use digital sales only and expose margin, digital-observation and weather-response uncertainty.

- [x] Model different stall types, opening hours, digital volume, digital payment methods and seasonality as labelled scenarios. *(Partial: five labelled volume/outage/sparsity scenarios with weekday seasonality; stall type, opening hours and payment-method mix are not in the digital receipt file, so they are NOT modelled — no invented types.)*
- [x] Include closures, sparse records, refunds, payment outages and zero-sales-versus-missing distinctions.
- [x] Keep digital receipts and digital-sales baselines explicit; never extrapolate total sales or cash income. Margin scenarios must be labelled assumptions.
- [x] Implement simple weekday (hour omitted: no verified hour-level need yet) or rolling/pooled baselines with uncertainty intervals.
- [x] Compare sparse digital-history fallbacks; never penalize refusal to share transactions.
- [x] Avoid declaring invented weather losses ground truth.
- [x] Fix seeds and retain configuration/source versions so scenarios are reproducible.

**Done when:** transparent baselines work on safe real-held-out records where available and synthetic scenarios are reported separately.

#### Phase 11 local implementation and handoff (16 November 2026)

- **Files:** `src/daycover/income_baseline.py`, `scripts/run_income_baseline.py`, `tests/test_income_baseline.py` (8 tests). Output (ignored, never overwritten): `data/processed/income-baseline-v1/baseline_report.json` + `scenario_panels.csv`. No policy/contract/migration/dataset/CSV change.
- **Upstream reuse:** the requested `harsh-pandhe/sih2026-fin2` `ml-training-with-rl` URL returned HTTP 404 via WebFetch (branch/path unavailable or private), so it could not be compared. Existing local copies (`synthesize_stalls.py`, `src/pricing/impact_model.py`) were reviewed instead: their cash/QR-share, stall-attribute and weather-drop assumptions were NOT reused; only the idea of a weekday-median normal-sales baseline with train-only fitting. Retry upstream comparison when access is available.
- **Method:** observed merchant-days only (≥1 digital receipt). Tiers: merchant+weekday median → merchant pooled × global weekday shape → centre+weekday → global weekday; 80% intervals from log-ratio quantiles (merchant tiers from train residuals; cold-start tiers from leave-one-merchant-out train residuals). Past-only rolling 28-day median comparator (no fit). Fit refuses cash rows and any holdout merchant in train.
- **Unknown vs zero:** 5,014 of 36,476 merchant calendar days have no digital receipt; treated as unknown, never zero. Simulator has explicit states observed_sales/verified_zero/closed/outage_missing/unrecorded, refunds, seeded (hash of seed+scenario+version), margin scenarios (30/45/60%) labelled unverified and applied to digital sales only; no weather response applied.
- **Results (synthetic data only; not real-world accuracy):** validation WAPE 0.256 (cov 0.76 vs 0.80 nominal), test WAPE 0.230 (cov 0.80); rolling-28d 0.253/0.239; global-weekday-only ~0.57–0.58. Merchant holdout future window: stat. baseline (cold-start centre tier, all 7,113 rows) WAPE 0.736, bias 0.54, coverage 0.56 — poor; rolling own-history WAPE 0.231. Conclusion: cold-start centre fallback under-covers and underestimates (holdout merchants appear larger than centre medians); it must be shown with wide/low-confidence labelling, and fixed-cover remains the path when no history is shared. Rolling baseline is competitive with the weekday model on forward time; keep both as comparators.
- **Verification:** full suite 268 passed / 130 skipped (PostgreSQL tests skipped — no `DAYCOVER_TEST_POSTGRES_URL` this run; previous 389-pass PG evidence unchanged). Raw CSV checksums untouched; no Git/GitHub/deploy.
- **Gaps:** stall type/hours/payment-method mix scenarios, hour-of-day baseline, weather/closure joins and refund linkage need data not yet present. No weather-income target exists. Phase 5 rain timestamp gate still open.
- **Next:** Phase 12 weather impact ML — start with leakage/target audit; with no verified weather-loss labels, a model likely cannot be justified over these baselines; retain baseline rather than invent uplift.

### Phase 12 — weather impact ML and evaluation

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Audit and reuse selected income sensitivity, rain-frequency, haze-credibility and walk-forward components from the research branches. Train only after phase 10/11 datasets and split rules exist. Keep models advisory.

- [ ] Audit leakage, bootstrap assumptions, target definitions, missingness and any synthetic labels.
- [ ] Define the target precisely: sales deviation, expected gross-profit disruption or trigger frequency.
- [ ] Compare with simple baselines on forward-time and held-out-merchant tests.
- [ ] Control for closures, holidays, trading hours, payment outages and non-weather changes.
- [ ] Evaluate uncertainty/calibration and results by digital observation coverage, stall type, centre and sample size; never introduce cash-share features.
- [ ] Report foreign-data transfer limits and observed-versus-synthetic performance separately.
- [ ] Version models/features/datasets, document failure modes and support rollback.
- [ ] Keep heat/flood shadow work and RL reinsurance experiments out of the core claims path.

**Done when:** a model has reproducible held-out evidence of usefulness over simple baselines, with its limitations visible; otherwise retain the baseline rather than inventing uplift.

### Phase 13 — recommendations, affordability and inclusive protection

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Use validated income/impact estimates to compare future pre-agreed benefit bands, not to resize today's payout. Implement an advisory quote/recommendation path with customer acceptance and reviewer controls.

- [ ] Provide fixed-cover fallback without a transaction-history requirement.
- [ ] Express normal earnings, estimated gross-profit loss and uncertainty separately.
- [ ] Price candidate bands using the candidate's exact trigger/cap/overlap design.
- [ ] Evaluate affordability, premium burden, meaningful cushion and sparse-data fairness.
- [ ] Compare access and error rates across cash-heavy/digital-heavy groups without inferring unnecessary sensitive traits.
- [ ] Record recommendation rationale, model version, customer choice and approval state.
- [ ] Apply accepted changes only to eligible new issues/renewals, never existing-event entitlements.

**Done when:** a future recommendation is reproducible and explainable, access remains inclusive, and it cannot mutate an active contract.

### Phase 14 — protection effectiveness, pricing and capital research

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Extend research dashboards with measured protection-quality metrics and contract-specific pricing/stress comparisons. Treat all treaty/funding/fee assumptions as scenarios unless independently established.

- [ ] Measure missed material-disruption days, paid days without measured disruption and payout-to-estimated-loss coverage.
- [ ] Separate gauge disagreement from actual income basis risk.
- [ ] Include uncertainty, expenses, collection failures, timing of cash, capital and reinsurance assumptions.
- [ ] Replay severe haze and rain accumulation years and sparse/missing-data scenarios.
- [ ] Compare S$180 baseline and S$150 alternatives on identical assumptions; never transplant their profit estimates.
- [ ] Quantify concentration, liquidity timing and residual losses without guaranteeing solvency.
- [ ] Keep optimiser output advisory; record proposal, evidence, reviewer decision and future version.

**Done when:** results can be reproduced per contract/data version, limitations are visible, and research cannot directly change rules used for existing claims.

### Phase 15 — read-only explanations, alerts and rewards proposals

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Ground the concierge and notifications in canonical contract/decision/billing records. Add multilingual explanations without giving the model authority or personal-data access beyond the purpose required.

- [ ] Explain paid, capped, excluded, pending, failed collection and uncertain settlement states accurately.
- [ ] Include version, evidence date/source and remaining cover where relevant.
- [ ] Test factual consistency and prompt-injection attempts; prevent any payout/price/tool mutation.
- [ ] Add opt-in notifications with duplicate prevention, delivery status and language preferences.
- [ ] Supply notification payload fixtures clearly labelled simulated; physical soundbox/TTS verification belongs to the external Part 1 owner.
- [ ] Keep dry-year credit and partner rewards as separately priced/funded proposals until approved; no invented sponsor branding.

**Done when:** explanations match ledger facts, ambiguity is acknowledged, and neither language output nor notifications can authorize money movement.

### Phase 16 — reliability, security and local release preparation

**Prompt:** Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Prepare and rehearse a staging-equivalent setup locally after the relevant preceding gates. Build release configuration, recovery scripts and verification evidence locally; record future hosting/integration requirements without deploying or changing a remote environment.

- [ ] Add readiness checks, structured logs, metrics, correlation IDs and source/payout exception alerts.
- [ ] Separate dev/test/staging configurations and simulation/provider credentials.
- [ ] Add least-privilege access, secret rotation, request limits and sensitive-action audit.
- [ ] Test backups/restores, migration rollback, queue recovery and duplicate processing after restart.
- [ ] Run critical engine API, concurrency, security and reconciliation checks locally. Document external Part 1 checks for later integration; do not trigger remote CI.
- [ ] Define retention/deletion handling for merchant data while preserving required audit records under reviewed rules.
- [ ] Verify provider-interface behavior with local mocks/fixtures and document which future sandbox checks, approvals and access remain absent. Do not invoke state-changing provider operations during local-only work.
- [ ] Produce an operator runbook here: outage, source correction, pending decision, failed debit, uncertain payout and rollback procedures.
- [ ] Rehearse the customer/operator journey, including no-payout and failure scenarios.
- [ ] Record the concrete local release candidate, test evidence and future deployment/real-payment prerequisites. Do not request routine publication approval or deploy; wait for the user to explicitly request a later publication/release task.

**Done when:** the staging-equivalent environment is reproducible locally, failures are observable/recoverable, operator responsibilities and future release blockers are recorded, and no remote deployment/publication has occurred.

## 6. Common acceptance matrix — add evidence, not just ticks

| Case | Required behavior | Status / evidence |
|---|---|---|
| Rain 69.9 / 70 mm | No trigger / S$30 if eligible | M1 tests; recheck after integration |
| PSI boundary / two-day sequence | Exact tier and missing-previous-day behavior | M1 rules/tests; extend with official evidence |
| Scheduled closure | Excluded without consuming caps | M1 tests |
| Incomplete/stale/outage weather | Pending or ingestion rejection; no fabricated reading | M1 parser/aggregation tests; operational pipeline pending |
| Missing assigned gauge | Approved valid fallback or pending with provenance | Historical engine tested; operational link pending |
| Haze final partial cap | Stop exactly at S$150 and within five paid days | M1 tests |
| Concurrent same event | One entitlement/instruction | SQLite and isolated PostgreSQL tested; Phase 8 mock recovery tested; actual provider checks remain gated |
| Concurrent different events | Never overspend shared period caps | SQLite and real Postgres concurrency tests passed in Phase 2 |
| Jan 1 during same term | Does not restore spent caps | M1 tests |
| Expired term / renewal | No automatic extension; explicit new term/version | Expiry tested; renewal workflow pending |
| Backdated/corrected weather | Ordered reconciliation with preserved history | M1 rejects out-of-order; operational resolution pending |
| Retry/unknown bank result | No duplicate transfer; truthful pending state | Provider mock/adapter work pending |
| Monthly rounding | Exactly 10,400 cents annually | M1 schedule tested; billing ledger pending |
| Cash-heavy/no sales consent | Fixed-cover path remains usable | M1 fixed cover; fairness/permissions extension pending |
| Cross-merchant request | Denied without information leakage | Auth phase pending |
| AI asked to change payout | Read-only refusal; ledger unchanged | Concierge limited; broader adversarial tests pending |
| Device offline/restarts | Recoverable UI, persisted state, no invented success | Persistence tested; physical device coverage pending |

## 7. Part 2 reproduction commands and environment notes

All commands run from `/Users/ankitasagar/Desktop/ML pipeline`. This standalone engine folder keeps Part 1 external. Existing Git metadata must remain untouched; do not initialize, restore or clone a repository as a routine prerequisite.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-daycover.txt -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn src.daycover.api:app --host 127.0.0.1 --port 8000
```

While running, `/docs` provides local API exploration without a mobile app. The default SQLite ledger is under `var/`. PostgreSQL selection, migration/import and rollback instructions are in Phase 2 above; PostgreSQL tests need an isolated local service through `DAYCOVER_TEST_POSTGRES_URL`. Never delete an existing ledger to reset a test.

Optional ML/research dependencies:

```sh
.venv/bin/python -m pip install -r requirements-ml.txt
```

Read `scripts/README.md`, `data/README.md` and `dataset/README.md` before running acquisition/training. The three supplied receipt CSVs require adapters and a quality audit; original companion artifacts and some legacy model inputs are missing. Existing reports do not imply a reproducible or validated model. Frontend/native TTS/end-device checks are external Part 1 integration responsibilities, not prerequisites for developing this engine.

## 8. Session handoff — update this section at the end of each phase

- **Workspace/policy:** `/Users/ankitasagar/Desktop/ML pipeline`, focused Part 2 engine + datasets. Existing `.git` observed at final Phase 8 check and left untouched; no initialize/clone/restore of Part 1 or development in old reference checkout. Local edits/tests only: no staging/commits/branches/fetch/pull/push, GitHub writes/remote CI or deployment until explicit publication request. Recovery archive remains excluded.
- **Latest user scope:** digital-sales-only ML; no cash transactions, cash-share features or inferred cash income. Preserve raw CSVs; future adapters must exclude cash and quarantine unknown payment methods with counts. Legacy cash-inclusive research cannot be reused without removing those assumptions.
- **Current phase:** Phase 11 digital-only baseline/simulator implemented/tested locally (see its handoff); Phase 12 is next. Phase 10 dataset foundation remains the input. Foreign raw-file import/eligibility, verified real transaction data and authoritative rain timing remain gated.
- **Latest evidence:** 389 passed/one optional absent-frontend skip, SQLite + isolated PostgreSQL; 29 dataset checks. Full input/output audit: 2,216,326 source rows → 775,772 digital receipts, 1,440,554 cash excluded, 100 merchants, no duplicate/conflicting IDs or mappings. Source/output checksums and all split memberships verified; byte-identical fixture rebuilds. PostgreSQL stopped and disposable services/data cleaned. No raw CSV, user ledger, model or financial operation changed.
- **Authority/modules:** existing identity/weather/evidence/lifecycle/entitlement/mock billing/mock settlement/read-model stack remains schema v7 and frozen M1. New dataset adapter is `dataset_pipeline.py`; CLI/config/schema/source catalogue are described in READMEs. Canonical dataset is ignored `data/processed/digital-v1.1/`; source inventory is separate. Dataset builds never alter the policy ledger.
- **Next action:** Phase 11 uses `manifest.json`, `quality.json`, `digital_receipts.csv` and `splits.json`; fit on train only (403,423), validate 88,511, temporal test 92,980, merchant holdout 190,858 with its future-window label. Cash/unknown methods and inferred cash income cannot enter ML. No zero-sales imputation without evidence. No weather-income target or real-world accuracy claim exists yet. Foreign candidate adapters/imports need raw-file/payment/licence checks; Part 1 device work stays external.
- **Open boundaries:** real mandate, first payment/debit dates, automatic retries, grace/lapse, cancellation proration/refund eligibility and actual fee quotes/affordability remain unspecified/unverified. Sponsor credit remains zero/unapproved. No actual IdP/issuer/transaction provider/payment rail; no confirmed rain interval convention/full archive/historical station-validity calendar. Never lift these gates by relabelling a mock.
- **Setup documentation update (16 November 2026):** README now links the current team repository and documents SQLite/PostgreSQL selection, Compose configuration, canonical v7 migration, local identity setup, readiness, isolated test DBs, persistent stop/restart and backup boundaries. This was a local documentation change only; no commit/push or database change.
- **Docs:** stable interfaces in READMEs; all evolving checklists/handoffs in ignored `prompts.md` only. Preserve accepted snapshots, monetary/source history and supplied data; do not create more context/conclusion files.

### Prompt for a focused phase

> Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Implement Phase [number] from `prompts.md`. Start by verifying the focused Part 2 folder, local files, outstanding edits and prerequisites; skip Git checks when metadata is absent. Reuse existing functionality and complete only this phase's coherent scope. Add meaningful tests for its acceptance criteria and failure/recovery cases. Keep the frozen M1 contract unchanged unless this task explicitly authorizes a new version. Do not claim live integrations from mocks. Update checkboxes, evidence, limitations and section 8 in `prompts.md`; keep all new handoff notes in this file. Report what works, what was tested and the next concrete step.

### Prompt when work is interrupted

> Work locally only. Do not stage or commit Git changes, create/switch branches, push, open/update pull requests, change GitHub, or deploy. Publishing is deferred until the user explicitly requests one consolidated branch push. Read `prompts.md` and inspect the actual local Part 2 files before continuing; do not clone or restore Part 1. Use local evidence; do not fetch/poll GitHub or follow old PR instructions. Reconcile the last handoff with the code and test evidence. Resume the first incomplete acceptance criterion of the current phase, preserving user changes. Do not restart completed phases or silently drop unresolved failures. Refresh section 8 before stopping.
