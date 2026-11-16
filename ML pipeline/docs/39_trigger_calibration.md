# DayCover+ trigger calibration for Issue #4

The `2026.11-draft2` hackathon baseline uses **70 mm in one Singapore calendar day**, **S$150 annual haze maximum within the five-paid-day limit**, and **the highest hourly 24-hour PSI in the stall’s region each Singapore day**. Commercial pricing and terms remain subject to Income's pilot review.

## Rain threshold and spatial basis risk

The comparison covers 701 sampled dates from 2017–2026. The replay portfolio contains 123 representative stalls, one per hawker centre.

| Month | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Sampled dates | 59 | 57 | 60 | 58 | 60 | 59 | 59 | 60 | 60 | 60 | 55 | 54 |

| Metric | 70 mm | 80 mm |
|---|---:|---:|
| Qualifying open stall-days out of 81,510 with valid policy readings | 883 | 537 |
| Annualised trigger days per stall before the one-event cap | 3.96 | 2.41 |
| Stall-years with ≥1 observed eligible trigger out of 1,228 with valid observations | 625 | 453 |
| Observed capped payouts across all sampled years, including partial 2026 | S$18,750 | S$13,590 |
| Policy triggers without a proxy trigger (95% CI) | 56.0% (40.3–75.6%) | 55.0% (33.8–85.1%) |
| Proxy triggers without a policy trigger (95% CI) | 21.4% (11.3–39.6%) | 14.8% (4.1–40.2%) |
| Rain claims / assumed premium, 2017–2025, observed sample / pooled Poisson scenario | 15.3% / 27.2% | 11.0% / 22.6% |

**Method.** The policy uses the assigned gauge when valid and otherwise the nearest valid gauge within 5 km. The proxy is the median of at least two other valid gauges within 5 km of the stall. The comparison excludes scheduled closures and uses the same 78,421 paired stall-days for both thresholds. For 70 mm, 381 pairs triggered both, 484 triggered only the policy, and 104 triggered only the proxy. The rates are `484 / (381 + 484)` and `104 / (381 + 104)`. The percentile intervals use 2,000 bootstrap draws, resampling whole dates within each calendar month. The proxy measures gauge disagreement. A pilot with consented stall-level takings is needed to estimate how that disagreement translates to loss and payout mismatches.

Each threshold is applied to both the policy reading and the proxy reading. This replay follows the active policy's gauge selection. The [earlier spatial study](20_rain_spatial_basis.md) used the nearest available gauge and counted the share of neighbouring gauges that crossed the line, which produces different disagreement rates.

Fallback was used in 17,245 of 81,510 observed open stall-days (21.2%), so the fallback rule belongs in the disclosure. The separate portfolio backtest uses 640 rain dates in 2017–2025, reports observed payouts after the one-event cap, and estimates a pooled Poisson scenario for a full year. The scenario assumes independent trigger days and homogeneous exposure. The two claim figures are scenarios, distinct from the bootstrap intervals.

**Decision.** Keep 70 mm for the hackathon baseline. It reaches 172 more sampled stall-years than 80 mm, while the one-event cap limits rain exposure to S$30 per stall-year. The intervals are wide and the comparison does not establish a clear spatial advantage for 80 mm. Keep 80 mm as a shadow comparison.

## Haze-day definition and monetary cap

The sensitivity replay covers 2015–2025. The timestamped archive and committed daily-max series each cover 20,095 region-days including 31 December 2014 for the first consecutive-day check. Noon is available for 20,090 of those region-days. The comparison below restricts all three definitions to those same 20,090 region-days. The two maximum series match on every paired reading.

| Regional PSI definition | Haze payout at S$150 cap | Haze payout at S$300 cap | Portfolio days with payouts at S$150 cap |
|---|---:|---:|---:|
| Highest hourly 24-hour PSI, calculated from the raw archive | S$37,530 | S$47,550 | 17 |
| 12:00 SGT 24-hour PSI | S$26,130 | S$35,610 | 9 |
| Committed daily-max 24-hour PSI | S$37,530 | S$47,550 | 17 |

| Full committed daily-max replay | S$150 cap | S$300 cap |
|---|---:|---:|
| 2015 payouts | S$18,450 | S$27,180 |
| 2019 payouts | S$13,890 | S$15,180 |
| 2015–2025 payouts | S$37,530 | S$47,550 |
| 2015–2025 loss ratio at assumed S$2/week | 26.7% | 33.8% |
| Stall-years reaching the monetary cap | 176 | 0 |

**Decisions.** Use the daily maximum of hourly 24-hour PSI. It retains the higher readings that a noon snapshot can miss and fits the daily evaluation window. Keep the S$150 monetary cap for the hackathon baseline. It reduces modelled haze payouts by S$10,020 (21.1%) across 2015–2025, while the largest single-day 2015 payout still totals S$7,380. Maximum combined liability under the pilot rules is S$180 per stall-year. The replay uses calendar years and the commercial design targets policy years. Expenses and reinsurance are outside these figures.

## Reproduce

From the repository root:

```bash
python -m scripts.calibrate_triggers
python -m scripts.backtest_simulator
python -m scripts.backtest_simulator --rain-mm 80 --out /tmp/daycover-backtest-r80.json
```

Outputs are [the trigger-calibration results](../results/trigger_calibration.json) and [the dashboard backtest](../public/data/backtest_results.json). Run `python -m scripts.load_history` against the demo database to refresh its historical replay events after updating the rules.
