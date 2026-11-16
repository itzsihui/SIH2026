# Supplied transaction dataset — actual files in this workspace

The three supplied CSVs have been retained **byte-for-byte unchanged**.

| File | Receipt rows, excluding header |
|---|---:|
| `DayCover_transactions_part_1.csv` | 800,000 |
| `DayCover_transactions_part_2.csv` | 800,000 |
| `DayCover_transactions_part_3.csv` | 616,326 |
| **Total** | **2,216,326** |

All three headers contain:

`transaction_id`, `timestamp_sgt`, `date`, `stall_id`, `centre_id`, `psi_region`, `stall_type`, `payment_method`, `amount_sgd`, `gross_margin_rate_assumed`, `refund_flag`, `data_origin`.

The provided original README declares the data synthetic. The Phase 10 full scan of all 2,216,326 rows found `data_origin=synthetic_calibrated_to_imda_aggregate`. The adapter also audits identifiers, timestamps, exact cents, duplicates, merchant mappings, provenance and split membership. These are not established observations of real hawkers or verified weather-income losses.

## ML input scope

**Digital-sales-only ML scope:** exclude cash transactions, declared cash shares and inferred cash income from ML features, labels, baselines, recommendations and evaluation. Accept only explicitly mapped digital payment methods; quarantine unknown/missing methods rather than assume digital. Preserve raw source files and report excluded row counts. Digital sales are observed digital revenue, not total revenue or net income. Historical cash-inclusive research is not an approved pipeline input. Settlement ledger terminology is separate from sales inputs.

The validated adapter is `src/daycover/dataset_pipeline.py`, configured by `configs/dataset-v1.json`. It writes a separate version under `data/processed/`; originals remain unchanged. No model is trained by this build.

## Build and audit digital receipts

From the engine root:

```sh
.venv/bin/python -m scripts.build_digital_dataset --out data/processed/digital-v1.1
.venv/bin/python -m scripts.inventory_dataset_sources --out data/processed/digital-source-inventory-v1.json
.venv/bin/python -m pytest -q tests/test_dataset_pipeline.py
```

Both commands refuse existing output paths. The local Phase 10 run already created these outputs; to rebuild, choose a **new** version directory/file. Use `--input path/to/part.csv` repeatedly for explicitly selected supplied-format files. This is a supplied-synthetic-source adapter, not a generic foreign POS loader. The scripts do not touch the application database.

| Generated artifact | Purpose |
|---|---|
| `digital_receipts.csv` | One namespaced digital receipt per record, exact SGD cents, explicit `+08:00` timestamp, source file/record ordinal and split membership |
| `manifest.json` | Schema/build ID, source sizes/SHA-256, access date, licence/attribution limitations, config and adapter checksums, output checksums |
| `quality.json` | Full row accounting, payment counts, duplicates/conflicts/rejections, dates and split totals; no real-world training accuracy claim |
| `splits.json` | Versioned calendar cutoffs, deterministic merchant assignments, counts and transformation fit rule before any feature generation |
| `quarantine.csv` | Source file/record ordinal, record hash and reason; raw records are not copied into rejection logs |

The supplied files contain **775,772 eligible digital receipts** (729,330 `SGQR_NETS_SIM`, 46,442 `OTHER_DIGITAL_SIM`); **1,440,554 `CASH_SIM` rows are excluded**. All supplied refund flags are zero; no refund linkage is invented. The full audit found no duplicate/conflicting transaction IDs or conflicting merchant metadata. All 100 synthetic merchants span the 2025 dataset; this does not establish complete observed real-world trading histories.

Only the two configured digital methods are allowed. Unknown/missing/mixed tender is quarantined. Dates must match the SGT timestamp; invalid amounts, non-finite values, fractional cents, provenance mismatches and inconsistent merchant mappings cannot silently enter training. The input margin field is quality-checked as an assumption and **never becomes a model feature or measured income**. Cash shares and total-income estimates are absent from the derived table.

Exact duplicate receipts retain one canonical record across all parts. Conflicting IDs exclude the original and later variants; inconsistent merchant centre/region/type excludes that merchant's accepted rows. Audit counts include these exclusions and must reconcile to all source rows. Source or config/adapter changes during a build discard the unpublished output. Files are staged, checksummed and published only on success; existing versions are never overwritten.

`schemas/dataset-v1.json` defines receipt fields and the line-item/refund/weather/quality boundaries. Current CSVs contain receipt totals, not items: foreign item records must first group by source + merchant + receipt and validate tender/currency before any split. Refunds require original-receipt links and cumulative checks; the supplied schema has no such link, so flagged refund rows are quarantined. Missing days, payment outages and closures are **not** filled as zero sales.

## Forward-time and merchant splits

Version 1 uses explicit 2025 windows: training before **1 September**, validation from **1 September through 31 October**, test from **1 November**. A seeded SHA-256 merchant assignment reserves 20 of 100 hash buckets for merchant holdout (an approximate fraction, not an exact merchant quota). All receipts of a held-out merchant stay out of training, across every time window. `time_split` remains available so future evaluation can select its held-out **test** window separately.

The full build contains **403,423 train**, **88,511 validation**, **92,980 test** and **190,858 merchant-holdout** receipts. Fit preprocessing, feature selection and model parameters on `split=train` only. Do not fit on all rows then split; do not pool the holdout's earlier dates into training. No features, weather joins, baselines or models are produced in Phase 10. Digital receipt amounts describe synthetic digital revenue, not total revenue, profit or actual weather-income loss.

## Source inventory and foreign research candidates

`data/sources-v1.json` records primary publisher links, attribution, metadata-level licence findings and eligibility gates for the three Mendeley datasets and Café Data 2.0. Candidate **raw files have not been downloaded or inspected**, and none of their rows are imported. The Mendeley pages advertise CC BY 4.0; Café supplemental-data reuse terms remain unverified. Digital-payment eligibility must be established from original files before any import; foreign currency, timezone, merchant identity and overlap cannot be guessed or relabelled as Singapore observations.

The ignored local source inventory hashes 15 existing transaction/weather/reference artifacts and records their actual columns, counts and presence. Local-copy origin/licence verification is separate from classifying a source as an official-Singapore candidate. The main historical rain sample has **43,329 station-day records on 701 distinct dates** from 2017-01-01 to 2026-11-06, not exhaustive daily coverage. A WBGT mapping exists but a full observed WBGT input archive is absent. See `../data/README.md`; none of these files automatically qualify as reviewed policy evidence or approved ML weather labels.

## Useful for

- Building transaction parsing, schema validation and daily/hourly aggregation.
- Testing income baseline methods with forward-time splits.
- Testing digital-payment scenarios and collection interfaces in simulation.
- Exercising model/recommendation interfaces without changing claims rules.

`gross_margin_rate_assumed` is an assumption, not measured profit. Phase 10 checks receipt validity, IDs, mapping consistency and splits; validated refund linkage, verified real-world coverage and empirical weather-loss labels remain unavailable. The supplied CSVs are not yet directly connected to the existing `.npz`-based research training scripts; a versioned adapter is needed.

## What is missing

The earlier package README lists merchant profiles, weather scenarios, daily/weekly panels, compressed receipts, generator/validator scripts and calibration metadata. **Those companion files are not present in this supplied dataset folder.** Do not claim they were recovered or that the original generation process is reproducible from these CSVs alone. The original description is preserved in `../docs/reference/DATASET_ORIGINAL_README.md`.

Read a small sample without loading the entire dataset:

```python
import pandas as pd
sample = pd.read_csv('dataset/DayCover_transactions_part_1.csv', nrows=1000)
```

For full processing, iterate `pd.read_csv(..., chunksize=100_000)`. Preserve source rows, file checksums and provenance; write validated/derived data to a separate output location. No dataset was regenerated or model trained during this workspace separation.

The raw CSVs are local inputs and are ignored for later source publication. Dataset packaging/licences and any large-file upload must be reviewed explicitly when publishing is requested.
