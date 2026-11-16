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

The provided original README declares the data synthetic. Inspection of the first 1,000 rows in each file found `data_origin=synthetic_calibrated_to_imda_aggregate`. This inspection is not a complete quality audit. These are not established observations of real hawkers or verified weather-income losses.

## Useful for

- Building transaction parsing, schema validation and daily/hourly aggregation.
- Testing income baseline methods with forward-time splits.
- Testing cash/digital scenarios and collection interfaces in simulation.
- Exercising model/recommendation interfaces without changing claims rules.

`gross_margin_rate_assumed` is an assumption, not measured profit. Refund semantics, duplicate IDs, timestamp validity, merchant consistency, coverage and split leakage still need a full audit before training. The supplied CSVs are not yet directly connected to the existing `.npz`-based research training scripts; a versioned adapter is needed.

## What is missing

The earlier package README lists merchant profiles, weather scenarios, daily/weekly panels, compressed receipts, generator/validator scripts and calibration metadata. **Those companion files are not present in this supplied dataset folder.** Do not claim they were recovered or that the original generation process is reproducible from these CSVs alone. The original description is preserved in `../docs/reference/DATASET_ORIGINAL_README.md`.

Read a small sample without loading the entire dataset:

```python
import pandas as pd
sample = pd.read_csv('dataset/DayCover_transactions_part_1.csv', nrows=1000)
```

For full processing, iterate `pd.read_csv(..., chunksize=100_000)`. Preserve source rows, file checksums and provenance; write validated/derived data to a separate output location. No dataset was regenerated or model trained during this workspace separation.

The raw CSVs are local inputs and are ignored for later source publication. Dataset packaging/licences and any large-file upload must be reviewed explicitly when publishing is requested.
