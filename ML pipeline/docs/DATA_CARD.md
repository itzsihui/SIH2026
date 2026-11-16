# DayCover dataset: data card

Status: 15 Nov 2026, draft 1. Rebuild with `python scripts/fetch_history.py`, then
`python scripts/build_dataset.py`, then `python scripts/synthesize_stalls.py --world <world>`.
Raw downloads (`data/raw/full/`) and large panels (`*.csv.gz`) are git-ignored; every one of them is
reproducible from the scripts.

## 1. Real data (public, independent, verifiable)

| ID | Dataset | Source | Coverage | Used for | Known issues and decisions |
|---|---|---|---|---|---|
| D1 | Daily station records: rain total, wettest 30/60/120 min, temperature, wind | MSS / weather.gov.sg daily CSVs | Jan 2009 to Oct 2026, 105 stations, 349k station-days | Rain triggers, rain frequency model | "—" means no reading and is kept as missing, never zero. Wettest-hour fields exist only 2014 to early 2020, so the short-storm rule has less history than the daily rule |
| D2 | Rain gauge coordinates | data.gov.sg real-time rainfall API station lists (probed 2016-2026) + repo list | 94 of 105 gauges | Centre-to-gauge mapping | 11 gauges have no published coordinates and are excluded: S80 Sembawang, S72 Tanjong Pagar (to 2015), 8 reservoir gauges and S130 (all new in 2026) |
| D3 | 5-minute rain | data.gov.sg real-time rainfall API | Dec 2016 onward, heavy-rain days + all of 2026 | Rain inside trading hours, 2026 replay | Pending download |
| D4 | 24-hour PSI, hourly, 5 regions | data.gov.sg Historical 24-hr PSI + real-time API for Oct-Nov 2026 | 1 Apr 2014 to 7 Nov 2026, no missing days | Haze trigger and model | Daily value = maximum hourly 24-hr PSI over the SGT calendar day (all 24 hours). 2014 is a partial year |
| D5 | WBGT, 15-minute, with heat-stress level | data.gov.sg WBGT API | Feb 2025 onward; 15 stations, 30 by Nov 2026 | Heat shadow rule | Too short to price heat. Pending full download |
| D6 | ONI (El Nino) and DMI (Indian Ocean Dipole) | NOAA CPC / PSL | 1950 / 1870 to 2026 | Haze timing analysis | DMI not yet published after May 2026 |
| D7 | Hawker centres with cooked-food stall counts | NEA Hawker Centres GeoJSON (data.gov.sg) | 2026 snapshot | Exposure | 129 listed; 120 operating with stalls > 0 = 6,665 cooked-food stalls (consistent with ~6,900 stalls in the 2026 rental support) |
| D8 | Cleaning and works closures | NEA (repo `hawker_closures.csv`) | 2026 | Exclusion | Matched to 119 centres by location (<= 150 m). Only 2026 exists, so history uses an approximation |
| D9 | PUB hotspots (19) and flood-prone areas (36) | PUB PDFs, Feb 2026 and Nov 2025; typed into `data/raw/pub_flood_locations.csv` | Current lists only | Rating flag and pilot site choice, never a trigger | Street descriptions; geocoded with OneMap and checked by hand. Not historical, so cannot train anything |
| D10 | Income Stallholder, SmartBiz360, Enhanced Home | Income brochures and T&Cs | 2024-2026 | Benefit design, price benchmarks | Stallholder "Closure of Stall" trigger wording not published |
| D11 | V3, MAS ENRM + Transition Planning, MSE 4 Aug 2026, MOM heat page, NTUC Jan 2025 | Government sources | - | Scenarios, compliance, market size | V3 gives end-of-century values only. MOM page does not itself state the WBGT 32/33 C rest-break rule (in the linked infographic) |

## 2. Geographic mapping (all deterministic, no look-ahead)

| Mapping | Rule | Result |
|---|---|---|
| Centre to rain gauge | For each policy year, the nearest gauge among those with >= 90% valid days in the PREVIOUS year; 2nd-nearest as fallback when the 1st has no reading that day | Mean distance 1.3-1.7 km (2.5 km in 2010); 97.3% of centre-days use gauge 1, 2.5% gauge 2, 0.18% missing |
| Centre to PSI region | Nearest of NEA's five regional reference points | Approximation: NEA does not publish region boundaries |
| Centre to WBGT station | Nearest station reporting in the reference month | Re-run once the full WBGT download finishes |
| Centre to PUB locations | Distance to nearest geocoded hotspot / flood-prone area | Pending geocoding |

Frozen-mapping rule: the 2026 test uses the gauges that existed in 2025. The 2026 network expansion (39 to 92 gauges) is not used, because a policy priced in December 2025 could not have used it.

## 3. Synthetic data (only where no public data exists)

| What | Why synthetic | Anchored on | Main assumptions |
|---|---|---|---|
| Stall population (6,665 stalls) | No stall-level public data | Real stall counts per centre (D7); owner age median 60 (MSE 2021) | Customers/day lognormal, median 120; ticket median S$6; gross margin 40-60% -> median S$359 gross profit/day |
| QR share of sales | No 2025/26 figure | Aug 2023: 5.4m e-payment tx/month across >11,000 stallholders, about 19/stall/day (EnterpriseSG MR049/23) | Central 25% of transactions (median 28 QR tx/day); worlds low_qr 15%, high_qr 50% |
| Weather response of customers | No measured loss data | 2026 haze: Tekka stalls -30% to -60% (The Star); team loss model 20-45% | Haze drop 20% at PSI 150, 35% at 200, 50% at 300; rain drop up to 45% scaled by mm and by the share of rain in trading hours; small heat effect; stall sensitivity varies; delivery offsets 15% |
| Daily QR panel | Needed to test cover sizing and collection | REAL centre weather each day (D1, D4, D8) | Poisson customers, rest day per week, closures = 0 sales |

Rules for synthetic data:
1. It tests the mechanics (cover sizing, premium collection, basis-risk measurement) and how results move when assumptions move. It is never presented as evidence of real losses.
2. Every number is in `params.json` with its basis; three loss worlds and two QR worlds are always reported together.
3. Weather inputs are always real; only behaviour is synthetic.
4. A pilot with consented QR data replaces it.

## 4. Open items
- D3 (5-minute rain) and D5 (WBGT) downloads in progress; D9 geocoding not yet run.
- Coordinates for S80 Sembawang and S72 Tanjong Pagar.
- MOM heat-stress infographic (WBGT bands and rest breaks) not yet read.
- Stallholder Insurance "Closure of Stall" trigger definition (ask Income).

## 5. Audit, 15 Nov 2026 (verdict: not yet final)

Checks that passed
- D1: no duplicates, no negative or >300 mm days (max 250.2 mm, S07, 16 Jul 2010), temperatures 22.8-38.0 C, tmin never above tmax.
- D1 against the 5-minute API on 28,893 shared station-days: median difference 0.0 mm, 95th percentile 0.2 mm, correlation 0.993. At the 70 mm line they agree on 288 of 296 heavy days (8 disagree). The contract must name ONE settlement source.
- D4: every day 1 Apr 2014 - 7 Nov 2026, PSI 16-322, no gaps; API tail joins the history cleanly on 1 Oct 2026.
- Centres: 120, no duplicate names or coordinates; 0.0-1.2% of centre-days lack rain after the gauge-2 fallback.

Problems found and decisions
1. Rain frequency: a 70 mm day occurs 3.3 times per centre-year (2010-2025), not 2.1 (Admiralty alone). 2021: 7.2; 2025: 6.5; 2026 to October: 1.9. Pricing must use the centre-level figure.
2. Daily-file network thins: only 40-47 gauges have >=90% complete daily files in 2020-2025, although the 5-minute API carries 60-90 gauges. Yishun centres end up 4-5.4 km from their gauge (Yishun Park 5.4 km, over the 5 km limit). Decision: download 5-minute rain for EVERY day from 2017 and build daily and trading-hours totals from it; use the daily files for 2010-2016.
3. PSI regions disagree on 69% of haze days (south vs central: 45%). The region is therefore priced and stated in the policy ("your PSI region: South"), and the 2026 test reports a sensitivity using each centre's two nearest regions. NEA publishes no region boundaries.
4. 20 station-days had a wettest hour above the daily total: sub-daily values set to missing and flagged (`qc_flag`).
5. PUB geocoding: the first automatic run was wrong for about a third of locations; hand-chosen anchors are in `pub_flood_locations.csv`; re-run pending.
6. WBGT network grew from 8 to 20+ stations during 2025-2026; the heat mapping is frozen on Jan 2026 stations.

## 6. Update, 15 Nov 2026: WBGT and PUB complete

WBGT (D5): 652 days, 1 Feb 2025 - 14 Nov 2026, 1,100,058 readings, no duplicates, 3,192 missing values.
Network: 8 stations (Feb 2025) -> 15 (Sep 2025) -> 20 (Jan 2026) -> 30 (Aug 2026). NEA's level labels match
the values exactly (Low <= 30.9, Moderate 31.0-32.9, High >= 33.0). Centres map to the 20 stations reporting in
Jan 2026 (mean 1.9 km, max 5.3 km). Between 11:00 and 17:00, a mapped station reached 'High' on 3.8% (2025) and
5.6% (2026) of days, but 'High' for 3+ hours on only 0.19% of centre-days. Conclusion: a "High for 3 hours" heat
trigger would almost never pay a hawker; heat stays a shadow peril for hawkers and the main peril for the
outdoor-worker product.

PUB (D9): 54 of 55 locations placed with hand-chosen anchors (Hong Kah Area excluded); two-anchor midpoints span
0.13-0.90 km. 25 centres are within 500 m of a listed location, 38 more within 1 km. The 1 km band flags 63 of 120
centres (most of the dense city centre), so it does not discriminate; only the 500 m flag is used, and only for
rating and pilot-site choice. Proximity to a listed road does not mean the centre itself floods.

## 7. Fix, 15 Nov 2026: wettest-hour columns after 2020
MSS changed the daily-file headers from "Highest 30/60/120 Min Rainfall" to "... min ..." in 2020. The parser matched
case-sensitively, so wettest-hour values looked missing from 2020. Fixed (case-insensitive match). Wettest-hour data
is now available 2014-2026 (87-98% of station-days). Cross-check with team Canopy: wettest hour >= 50 mm occurs
2.55 days per centre-year (2014-2025) in our data vs ~2.8 at Canopy's median gauge; >= 70 mm 0.38 vs ~0.4. Daily
total >= 70 mm: 3.24 days per centre-year.

## 8. Premium structure (added 15 Nov 2026)
Premium is computed per peril and billed as one amount. prem_rain S$550,190 (51.6%) + prem_haze
S$516,860 (48.4%) = premium_2027 S$1,067,051. 5,326 stalls pay for both perils, 869 for haze only
(no rain cover offered, nothing charged for it), 126 for rain only. One payout per centre-day at the
highest peril triggered, 6-day annual cap, so it is one policy with two triggers rather than two
stacked policies. Justification for pricing the perils apart and pooling the risk together:
cover-weighted annual claims for rain and haze correlate at -0.88 over 2010-2026, and bundling cuts
the volatility of the annual claims total by 22.4%. Re-rated annually, not monthly.

## 9. Reinforcement-learning reinsurance policy (added 15 Nov 2026)
Tabular Q-learning, 36 states (capital bucket x ENSO signal x years since last haze) x 9 stop-loss
structures, 60,000 episodes, all 324 state-action pairs visited. Results in
data/processed/model/rl_reinsurance_results.json. The agent cuts solvency-breach probability from
18.4% (static 1.5x/3x) to 16.1% and improves the worst-5% ten-year outcome by S$30,048, at a cost of
0.9% of expected profit; the best hand-written rule tried reaches only 20.1%.
Haze probability inside the environment is a non-parametric two-bucket Laplace-smoothed estimate
(ONI MJJ > +0.5: 3 of 4 seasons severe; <= +0.5: 0 of 9), chosen after a ridge logistic version proved
either near-separable (ridge 1e-3, 0.6% -> 99%) or signal-free (ridge 2.0, expected loss inflated to
S$714k). With 3 severe seasons on record no fitted classifier is honest; the two-bucket estimate is.
KNOWN LIMIT, disclosed: the capital dimension of the learned policy is monotone as theory requires,
but the ENSO dimension is not (mean attachment La Nina 2.23, mild El Nino 1.60, strong El Nino 2.62).
That dimension is partly fitting noise from 3 severe seasons. The RL policy is therefore proposed as a
capital-triggered overlay on the filed static structure, refitted annually, not as a replacement.
