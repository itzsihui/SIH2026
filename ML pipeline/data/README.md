# Weather, reference and model data

This folder is separate from `../dataset/`, which contains the supplied transaction CSVs.

| Location | Contents | How to interpret it |
|---|---|---|
| `raw/rainfall_daily_stations_2017_2026.csv` | Historical sampled station-day rainfall | Sampled coverage, not a complete daily archive; absence is unknown |
| `raw/rainfall_stations.csv` | Gauge metadata | Used for assignment and historical fallback research |
| `raw/psi_daily_max_combined_2014_2026.csv` | Existing regional daily PSI summary | Verify observation definition and coverage before operational use |
| `raw/hawker_closures.csv` | Centre coordinates/closure reference | Representative centres, not verified individual merchant identity |
| Other `raw/` files | Existing public-data and research inputs | Preserve source, units, dates, missingness and corrections |
| `processed/` | Centre/gauge/region mappings and processed climate tables | Derived research artifacts; not automatically approved policy assignments |
| `processed/model/` | Existing metrics, model summaries and experiment books | Research outputs; do not treat them as validated Singapore hawker loss evidence |

Canonical resumable API ingestion is in `src/daycover/weather_ingestion.py`; the earlier freshness-only parser remains in `ingestion.py`. Raw bytes/hashes, fetch times, station metadata history and provisional observation revisions are stored in the selected local canonical ledger, not written over these CSVs. The schema distinguishes five-minute rainfall observations from complete Singapore-day totals. Missing/stale/incomplete data never becomes fabricated zeroes or final denials. Phase 5 now persists daily candidates/reviewed versions, sourced closure corrections and reviewed gauge-selection snapshots. Missingness and conflicts remain explicit. Rain finalization remains gated on authoritative interval-labelling verification, and the Phase 6 engine now consumes only qualified reviewed evidence for simulation entitlements. Payment execution remains disconnected. See `../docs/README.md` for commands, official source attribution and the difference between observed metadata and verified historical station mappings.

The original model scripts also expect inputs that are not currently supplied, including full history under `raw/full/`, some `processed/*.csv.gz` files and synthetic QR-history `.npz` files. Existing JSON reports alone cannot reproduce a training run. Check prerequisites before downloading or training.

Required provenance classes for future dataset builds: observed foreign, official Singapore, calibrated synthetic and consented Singapore. Keep raw versions and licensing/attribution records separate from generated features and labels. Never overwrite raw inputs to make a test pass.

## Phase 10 inventory and derived digital dataset

`data/sources-v1.json` is the versioned source catalogue; `.venv/bin/python -m scripts.inventory_dataset_sources --out data/processed/digital-source-inventory-v1.json` records checksums, columns, row/date counts, access date and explicit local-copy licence/origin uncertainty. Use a new output name when rebuilding. The inventory does not download, approve, join or rewrite sources.

The 2017–2026 main rain sample has 43,329 station-day records but only 701 distinct dates; it is not a complete daily archive. Missing observations remain unknown. The older `daily_weather_records.csv` is separate coverage, not proof that the main sample is complete. `centre_wbgt_map.csv` is a derived location mapping, not an observed WBGT time series; flood/closure references likewise do not establish verified event labels. Synthetic transaction centres have no approved mapping to real centres, so Phase 10 creates no weather-income joins. The operational rain interval gate remains open.

`processed/digital-v1.1/` holds the digital-only supplied-synthetic receipts, audit, manifest and forward-time/merchant splits described in `../dataset/README.md`. Generated digital versions and local inventories are ignored. No model, zero-sales imputation, cash extrapolation or real-world loss target is generated.
