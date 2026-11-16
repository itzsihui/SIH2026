# DayCover+ 3.0 — Hawker Transaction Dataset v0.1

**Status: completed synthetic prototype dataset — NOT real Singapore merchant transactions.**

This package provides transaction-level, merchant-level and stall-day-level data to develop the DayCover+ **income baseline**, **four-week premium collection simulator**, **cash/digital fairness checks**, app/dashboard UX and ingestion APIs. It is generated deterministically and calibrated against one published Singapore e-payment aggregate.

It is **not valid evidence of actual Singapore hawkers' sales losses, weather elasticities, policy claim frequencies, underwriting profitability or real-world model accuracy.** In particular, the weather scenarios are invented for integration testing. Do not train and market a weather-impact model from this as if the relationship has been discovered empirically.

## Contents

| File | Granularity | Purpose |
|---|---|---|
| `transactions_SYNTHETIC.csv.gz` | One invented POS receipt | Train/test hourly revenue baselines, merchant transaction monitoring, payment-ledger ingestion and collection tests |
| `daily_panel_SYNTHETIC.csv.gz` | One stall on one date | Aggregate sales, missing/open days, simulated counterfactuals and chronological train/validation/test splits |
| `merchant_profiles.csv` | One fictional stall | Centre, trade type, shelter, trading hours, cash/digital share assumption, estimated margin |
| `weather_scenarios_SYNTHETIC.csv` | One date × simulated PSI region | Fictional rainfall/PSI episodes used for exercising the trigger/impact pipeline; **NOT NEA observations** |
| `weekly_collection_SIMULATION.csv` | One stall × calendar week | Hypothetical cent-per-digital-sale accrual against a prorated example premium. **No money moved** |
| `sample_5000_transactions.csv` | First 5,000 receipts | Convenient sample for quick inspection/import |
| `calibration_report.json` | Whole dataset | Record totals and comparison against the official Singapore benchmark |
| `generate_dataset.py` | Source generator | Reproducibly regenerates all data from a fixed RNG seed |
| `validate_dataset.py` | QC script | Validates daily/weekly totals, unique receipt IDs, positive tickets, provenance, and annual obligations |
| `DATA_DICTIONARY.md` | Schema documentation | Column definitions, value meaning and leakage warnings |

## Record counts (seed 20261116, 2025)

- 100 **fictional** hawker stalls in 10 **fictional** centres across 5 simulated PSI regions.
- 365 calendar days = **36,500 stall-day** records.
- **2,216,326 receipt records**, including **775,772 electronic payments** and **1,440,554 cash payments**.
- About **21.254 digital receipts per participating stall per calendar day**, close to the August 2024 IMDA benchmark of approximately **21.318**.
- Simulated digital average receipt **S$7.89**, close to published aggregate estimate **S$7.89**.
- The cash share, individual stall income, weather-response coefficients, event frequencies and ticket distributions are **assumptions** and have not been observed in real Singapore hawker records.

## Published aggregate used for calibration

The 10 October 2024 IMDA release reports for **August 2024**: about **7.6 million electronic transactions**, **S$60 million** payment value, and **more than 11,500 stallholders** offering e-payments. We use 11,500 as an approximate denominator: **7,600,000 / 11,500 / 31 ≈ 21.318 digital transactions per stall-day**, and **S$60,000,000 / 7,600,000 ≈ S$7.895 per e-payment**.

Source: https://www.imda.gov.sg/resources/press-releases-factsheets-and-speeches/press-releases/2025/government-subsidy-under-hgd-programme-extended-for-another-year

Limitations: this is a programme-wide aggregate from 2024, includes stallholders beyond the exact population of 100 synthetic stalls, and provides no individual customer, cash, margin or weather-loss information. Its date differs from the generated **2025** data. Calibration is illustrative, not a statistical fit to merchant microdata.

## Original POS research that can improve v0.2 (NOT YET IMPORTED)

1. Engel et al., **Anonymous Transactional Dataset**, *Data in Brief*, 2026, DOI 10.1016/j.dib.2026.112519; public dataset version 2: https://data.mendeley.com/datasets/kcgf45y24m/2 — **53,820 observed transactions**, three Indonesian outlets, Jan–Sep 2025, CC BY 4.0. The raw dataset could not be downloaded in this execution environment; **none of its rows or empirical distributions are present**.
2. Cazier et al., **Sandwich Analytics**, https://data.mendeley.com/datasets/9hntk3wbwc/1 — observed restaurant sales and weather from US locations, CC BY 4.0; **not imported**.
3. Research decisions: https://github.com/harsh-pandhe/sih2026-research-findings/blob/main/findings/19_multi_peril_financial_optimization.md — candidate hawker product only, not a commercial quotation.

When original data can be downloaded, store separately with licences/attribution and run a distribution comparison before rebuilding. **Do not relabel Indonesian/US receipts as Singapore hawker observations.**

## Reproduction

```bash
python -m pip install numpy
python generate_dataset.py --out . --stalls 100 --year 2025 --seed 20261116
python validate_dataset.py --folder .
```

The compressed CSV has a header and uses Singapore local naive timestamps with `_sgt` explicitly in the column name. All stall and transaction IDs are invented.

For a quick run:

```bash
python generate_dataset.py --out ./small --stalls 20 --year 2025 --seed 20261116
```

Do not use this dataset to make valid PayNow instructions or collect premium. `SGQR_NETS_SIM` is a synthetic payment-method label, not evidence of a NETS integration.

## Collection illustration and 4-week design

- The proposed research candidate (Finding 19 Plan 4) models an **illustrative S$87 annual premium** and **S$150 combined annual benefit cap**. These terms are subject to Income review and are **not issued policy conditions**.
- `weekly_collection_SIMULATION.csv` assumes **S$0.02 accrued per electronic receipt**, but caps accrual at each week's **prorated due premium** (rather than automatically collecting S$2.21 and overcharging against S$87/yr).
- Total illustrative premium obligation equals **S$87 per merchant over 2025**, including prorated partial first/last calendar weeks. Uncollected amounts remain outstanding; **no implied sponsor funding**.
- A four-week locked collection schedule, legitimate provider-initiated settlement, failure handling, refunds and policy renewal accounting require independent implementation and contractual approval. These rows test mechanics, not live collection.

## Weather, payout and loss labels

`weather_scenarios_SYNTHETIC.csv` includes invented regional rain and haze conditions. Those are suitable only for **unit/integration testing** of weather-data parsing and research scenarios. They are **not real NEA/PUB readings**, not indicative of 2025's actual rainfall/haze, and must never be used as independent evidence for triggers or pricing.

`daily_panel_SYNTHETIC.csv.gz` includes fields `counterfactual_sales_sgd_simulated` and `estimated_weather_loss_sgd_simulated` created by the generator. These are **simulator knowledge**, not observable training labels in real practice. For production-like evaluation, isolate them from features and use them only to check simulator mechanics.

To develop a legitimate loss-response model, join *observed* merchant sales from a consented provider with actual NEA event timestamps, opening hours, cleaning closures, local holidays, and non-event controls. Keep actual data separate and version the policy trigger definition.

## Suggested use today

1. Build the transaction ingestion/API using `transactions_SYNTHETIC.csv.gz`.
2. Test hourly/daily demand baseline against held-out 2025 dates; first fit a day-of-week / time-of-day statistical model, then evaluate ML approaches. Don't use future dates in training.
3. Test weekly micropayment caps and cash-heavy shortfalls against `weekly_collection_SIMULATION.csv`.
4. Test missing-merchant fallback and profile recommendation logic.
5. Replace synthetic assumptions with legally obtained actual transactions and real NEA readings **before claiming empirical protection improvements**.

## How much real data is actually needed?

For a hackathon **pipeline demonstration**, this 2.2M-row synthetic fixture is plenty. For meaningful baseline calibration, as little as **20–50 consented merchants with 3–6 months of data** can provide an initial dataset, depending on consistency and coverage. For substantive weather-loss estimation, a stronger target is **100–200 merchants monitored for 12–24 months or longer**, with multiple genuine weather disruptions and appropriate controls; severe haze is rare, so real haze-effect identification can require several years or an external historical merchant panel. Record count alone cannot establish adequacy: effective weather-event count, time coverage, shop diversity and cash recording matter much more.
