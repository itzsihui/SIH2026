# FinTech / InsurTech Track — Income Insurance (your assigned track)
Sources: "[Ext] SIH 2026 Industry Track Problem Statements" (Drive), SIH infopack, live checks of NEA/MOM data on 7 Nov 2026. Items marked ASSUMPTION are my illustrations, not facts. Back-test before you quote them.

## 1. The statement
"How might we reimagine insurance, powered by data and AI, so that climate risk protection becomes affordable, accessible, and actionable for every vulnerable household and SME in Singapore?"
Partner: Income Insurance (ex-NTUC Income, social enterprise, NTUC Enterprise). Net zero pledge 2050. Group schemes through NTUC unions (many platform workers are union members).

## 2. Why now (from the brief)
- Singapore hotter and wetter; haze this year longest since 2015.
- Days above 35C about 21/yr now, could reach 41–351/yr by 2100.
- 1 Dec 2026: four more MOM heat-stress measures become mandatory (training, cool drinking water, emergency cooling, protective clothing).
- Open real-time weather/air data + AI make pricing and automatic payout cheaper.

## 3. The gap Income describes
- Households: flood cover for contents/renovation only inside voluntary comprehensive home policies.
- Workers: about 71,600 regular platform workers (2025). Work injury compensation covers injury, NOT income lost when they stop work because of haze/heat/rain.
- SMEs: property cover exists, business interruption needs physical damage first. No cover for weather income loss.
- Mass events: haze/heat hit everyone at once (accumulation risk), claims assessment is slow and costly, money arrives late.

## 4. Prior art (use for "what exists" judging criterion C)
- Income Droplet (2018): pays up to 60% of fare if raining at pick-up on ride-hailing; premium S$1–9.60/day, dynamic with NEA rain forecast, RPA checks receipts.
- Singlife rainfall travel cover (S$150), Swiss Re PSI haze cover for businesses (2018). None reach households, workers, small traders.
- SEWA India heat-index cover: 21k to ~250k members, thresholds reset after a zero payout year, 6–8 week payouts.
- Delhi gig workers trial: Rs200 automatic on first heatwave forecast day cut lost days ~2/3, but low willingness to pre-pay.
- China ZhongAn 37C cover: sold 200k, paid nothing in cool summer, regulator warned about gambling-like products.
- Meituan: pays premium for 3M riders, pays on diagnosis not temperature.
- Japan PayPay heatstroke cover Y100/day, 400k+ policies (medical, mostly families).
- Korea: Jeju day-labourer heat cover works (government-funded); KB stallholder cover got zero subscribers (nobody paid premium).
- Igloo x DANA (Indonesia, Sep 2026): IDR500 at checkout, IDR50k payout at 2.5 mm satellite rain, no hardware (3 weeks old).
- BlockBima Nairobi: rain trigger reduces loan repayments, settled in a day, 86% preferred.
- Jakarta flood card, Caribbean LPP, Guatemala MiCRO: failure lessons (single gauge not trusted, unaffordable 13% rate, triggers tightened after 100% loss ratio).
- FloodFlash UK: needs a sensor per premise, which this brief rules out.
Lesson to quote: schemes died on (a) basis risk, (b) nobody wants to pre-pay, (c) first season paid nothing.

## 5. Hard constraints (breaking one costs points)
1. Offered by or with Income as licensed insurer (MAS fair dealing + disclosure).
2. Insurable interest: sell only to people who would really lose income/property.
3. Say plainly when it does not pay (one sentence at sale). Use several trigger levels.
4. Back-test the trigger on past NEA/PUB data: how often a customer loses income with NO payout.
5. Use an index people already act on: NEA WBGT heat-stress levels, 24h PSI bands, PUB flood sensors, MSS rain gauges. Independent, published, decades of history, fallback if feed fails. Explain worksite vs station gap.
6. Decide who pays: member, platform, employer, union, or time-limited start-up subsidy with an end date. No permanent subsidy.
7. Pay when needed (fast).
8. Cap payable days per season, bundle heat + rain + haze, budget reinsurance (haze hits everyone).
9. Affordability: a few dollars per week/month; expenses within ~20% of premium. Refs: Philippines caps micro-premium at 7.5% of daily minimum wage, Malaysia Perlindungan Tenang RM50–75/yr, APAC avg microinsurance US$13/yr.
10. Trigger + payout + exclusions must fit in one SMS in the customer's language; customer can say it back.
11. PDPA: collect only needed data. AI pricing explainable and not pricing out the most needy (MAS FEAT).
12. Complement statutory cover (work injury compensation from 1 Jan 2025, MOM rest breaks). Do not duplicate injury cover.
13. No new hardware as the core. No crypto/token insurance. No ideas needing law change. No climate ideas without an insurance element. No big corporates / reinsurance / cat bonds / national infrastructure.

## 6. In scope
Users: lower-income households, renters, seniors incl. union members in flood/heat-exposed homes; outdoor and platform workers (taxi/PHV, delivery, cleaners, construction); SMEs (hawkers, neighbourhood shops, home-based).
Directions: parametric or hybrid products on public weather/air data; responsible AI/alt data for cheaper underwriting/pricing/claims; bundling insurance with risk reduction (cooling, flood barriers) or premium rewards; plain-language multilingual explaining/selling.
Income's own open question (case study SmartBiz360, launched Oct 2026, covers property + malware + up to 100 days BI): extend a simple low-cost package to climate-related income loss (heat, haze, flash floods) for SMEs, with public data + AI for pricing and triggers, premiums affordable.

## 7. What a strong 36-hour outcome is (their words)
A product proposal covering, each with justification:
concept/design, target group(s), simple pricing logic + unit economics, claim parameters + exclusions, impact on financial protection and affordability, market competitiveness, distribution proposal, how AI/data is integrated.
Must-haves: offered by/with Income; independent verifiable trigger data; user understands what they pay for and when they get paid in under a minute; minimal personal data, explainable AI; no new hardware for the core.

## 8. Data (checked live 7 Nov 2026, all keyless)
- WBGT: api-open.data.gov.sg/v2/real-time/api/weather?api=wbgt. 30 stations, updated about every 10 min, station lat/long, WBGT value, heat-stress category. Right now all stations 23.7–25.0C = "Low".
- Rainfall: api-open.data.gov.sg/v2/real-time/api/rainfall. 91 stations, 5-minute totals, mm.
- Also on data.gov.sg: air temperature, PSI (24h), flood-prone area data from PUB, MSS gauges. Historical series needed for the back-test: pull them before you fly (Singapore wifi at hotel is fine but do it from India now).
- MOM heat-stress bands: under 31C basic measures; 31–32.9C hourly hydration, 10-min breaks for heavy work at 32C+; 33C+ at least 15 min rest per hour for strenuous work, redeployment of at-risk workers. From 1 Dec 2026 training, cool water, cooling aids, protective clothing mandatory.
- NOTE for design: WBGT 33C+ is rare in Singapore, so a single 33C trigger would almost never pay (the "first season paid nothing" failure). Use tiers (e.g. 31 / 32 / 33) and combine with PSI bands and rain.
- PSI bands: 0–50 good, 51–100 moderate, 101–200 unhealthy, 201–300 very unhealthy, 300+ hazardous. Verify the exact tiers on NEA before using.
- Other links in the doc: NEA V3 climate study, Income Stallholder brochure, Income Enhanced Home brochure, MSE written reply on hawker insurance (4 Aug 2026), NTUC platform-worker article, MOM labour force 2025, MAS environmental risk guidelines, MAS FEAT, MAS fair dealing.

## 9. Judging fit (infopack)
A Problem understanding + alignment (evidence: data, user/mentor input, research). B Solution + commercialisation (1–3 core features working: live demo / clickable mock-up / recorded walkthrough; scope fits 36h). C Innovation + differentiation (know competitors, SG/India transferable insights). D Pitch + Q&A (clear user, problem, solution, ask; teamwork, balanced SG/IN presenters).
Semis 5 min pitch + 15 Q&A (be in room 30 min early, FinTech room SR 3-09). Finals 5 + 5. Top 8 teams, 2 per track.

## 10. Concept directions (pick ONE with the team)
A. "Heat/haze/rain income day cover" for platform workers. Trigger tiers from WBGT at nearest station + PSI + rain. Payout of a fixed S$ per lost day, capped days/season. Sold via union/platform in one SMS. Premium paid by worker + platform/union co-pay + time-limited subsidy shown on premium line. Distribution: NTUC unions and platform partners.
B. SME micro business-interruption add-on to SmartBiz360 for hawkers/neighbourhood shops: trigger = flash-flood alert near the shop (PUB sensors) or haze PSI days, payout lump sum. This directly answers Income's own open question.
C. Household flood/heat bundle for lower-income renters through union group scheme, pays instant cash relief on PUB flood sensor trigger, with a risk-reduction reward (e.g. free fan/cooling kit or flood barrier discount).
Your edge: you can build a working trigger engine + back-tester + auto-payout simulation quickly, and you know verifiable-trigger-to-payout design from AgriTrust. Keep hardware and blockchain out of it.

## 11. Illustrative unit economics (ASSUMPTION, replace with back-test)
Premium = (P(trigger day) x days exposed x payout) / (1 - loading), loading about 20% max per brief.
Example only: if a tier triggers 8 days a year at a station, payout S$30/day, expected loss S$240/yr, premium about S$300/yr = S$25/month = about S$6/week. Check against affordability and expense limit. Add reinsurance for haze accumulation (all customers trigger together): cap days, cap per-event pool.
Also show: payout in 24 h via PayNow to the customer, no claims form.

## 12. Pitch skeleton (5 minutes)
1) Customer story (one delivery rider, Tuesday of haze, loses S$). 2) Gap + data (71.6k platform workers, no income cover, MOM rules mean they stop). 3) Product in one SMS (trigger, payout, "may not pay when..."). 4) Live demo: live NEA feed, trigger fires, payout simulated, back-test chart (how often it would have paid in last N years, and how often a loss without payout). 5) Unit economics + who pays + subsidy end date. 6) Compliance: MAS fair dealing, PDPA, FEAT explainable pricing, no hardware. 7) Distribution via NTUC/platform. 8) Ask: pilot with Income for one union cohort.
Q&A prep: basis risk (station vs worksite), moral hazard/insurable interest, first-season-pays-nothing, who funds, haze accumulation, why not Droplet, why not just government subsidy.

## 13. Questions to ask Income reps (Sun 15 Nov 12:30 consultations)
- Which partners/unions can distribute first (NTUC, platform associations)? Any data on lost income days?
- Premium ceiling, payout floors, claim speed expectation, reinsurance appetite for haze.
- Will Income share historical claim or customer segment data, or only public data?
- Is PayNow payout acceptable under their ops, and what ID/KYC is needed at sale?

## 14. Do before you fly (7 days)
1. Download historical rainfall, WBGT, PSI, temperature series from data.gov.sg; build trigger tier tables and a back-test script.
2. Draft a one-SMS product text in English + Mandarin/Malay/Tamil stubs.
3. Build a clickable mock-up of the buy screen and the "you were paid" screen.
4. Read: Income Stallholder brochure, MOM heat stress page, SEWA results, Droplet.
5. Pick 3 candidate concepts and a scoring grid (affordability, trigger clarity, distribution, compliance, demo-ability).
6. On 10 Nov: share the data/back-test starter with your 5 teammates.

---
# DEEP RESEARCH ADDENDUM (7 Nov 2026) — verified facts, with sources

## A. Back-test data reality (this decides your product design)
| Series | Coverage | Use |
|---|---|---|
| WBGT (NEA, data.gov.sg d_87884af1...) | 15-min averages, only Feb 2025 – Nov 2026 (~21 months) | Too short for "decades of history". Use it to calibrate a model, not to price alone |
| Daily rainfall + temperature (MSS historical daily records) | from 1980, CSV by station/month | Long history. Build a WBGT-proxy from temperature + humidity and validate it on the 21 months of real WBGT |
| 24-hour PSI (data.gov.sg historical) | Apr 2014 – Jul 2026 | Covers 2015, 2019 and the 2026 haze. Good for haze tier back-test |
| Real-time rainfall | 91 stations, 5 min | Live trigger demo |
| Real-time WBGT | 30 stations, ~10–15 min | Live trigger demo (currently all "Low", 23.7–25.0C) |
| PUB flood-prone areas | Jan 2022 – Jan 2025; flood-prone area now only about 28 ha (was 3,200 ha in the 1970s) | Flood is rare and local: weakest peril for a mass product. Use for SME shops in hotspots only |
| PUB sensors | 1,000+ water-level sensors, 500+ CCTV, real-time flood alert API; 650 more sensors by end-2028 | Flash-flood trigger candidate |
Implication: say "we calibrated tiers on 21 months of WBGT and extended with 40+ years of temperature/rain, and 12 years of PSI". Judges and Income reps will respect honest data limits (judging criterion A and D).

## B. Official thresholds you can anchor on
- NEA/MSE heat stress advisory: Low under 31C WBGT, Moderate 31 to under 33C, High 33C and above.
- MOM outdoor work: hourly 10-minute breaks for heavy work at 32C+, at least 15 minutes rest per hour at 33C+; four more measures mandatory 1 Dec 2026 (training, cool water, emergency cooling, protective clothing).
- PSI: unhealthy 101–200, very unhealthy 201–300, hazardous 300+. NEA daily haze advisories begin when 24-hour PSI exceeds 100; N95 distribution at "very unhealthy".
- 2026 haze is real: 24-hour PSI first entered unhealthy on 4 Sep 2026 (first time since 2023) and was still unhealthy in all regions on 13 Oct 2026. That is a ready-made live case study for your demo (how many days would your cover have paid in Sep–Oct 2026?).
- Caveat: those MOM/NEA rules bind employers. Platform workers are not employees, so nobody is obliged to give them paid rest. That is the exact protection gap.

## C. Who your customers are (numbers)
- Platform Work Associations registered under the Platform Workers Act from 7 Jan 2025: NTA (taxi), NPHVA (private hire), NDCA (delivery). Eligible workers about 67,600 (20,800 taxi, 31,800 private hire, 15,300 delivery). The brief says about 71,600 regular platform workers (MOM 2025). Cite both honestly.
- Work injury compensation covers injury, not lost days. Union members also get S$250 grocery vouchers on injury and access to the NTUC-U Care Fund. So distribution through NTUC associations is real, and a "NTUC-U Care Fund-style top-up" is a credible payer.
- Income: median full-time platform worker S$2,000/month (2023), private hire S$2,500 (higher than delivery and taxi). So a lost day is roughly S$80–100 of gross income (ASSUMPTION: 2,000 / ~22 days).
- IPS survey (2022, 1,000+ delivery riders): almost half would deliver anyway in bad weather because they cannot afford the lost income. Product framing: "paid not to ride when unsafe". This is also your moral-hazard answer: the payout removes the incentive to ride in haze.
- Hawkers: about two-thirds of cooked-food stallholders already buy insurance (NEA survey); NEA is reviewing making insurance compulsory. Income Stallholder Insurance: premium from S$0.30/day, S$109–218/yr, closure-of-stall cover up to 120 days at S$100/150/200 per day. SmartBiz360 (Oct 2026): up to 100 days business interruption but only after property damage. A weather-triggered, no-damage-needed add-on to the stallholder policy is a minimal, believable extension (and benchmarks your pricing: S$109–218/yr for a whole bundle).

## D. Evidence on what works and what fails
- SEWA / ICICI Lombard / Swiss Re heat cover: launched May 2023 for 50,000 women; 2024 payout when temperature breached 41.6–46.1C for 2 consecutive days = 50% of sum assured; 92% (46,242) of members in 16 districts were paid, averages about US$7.4 to US$10.3 each, total about US$590k. 2023 paid nothing because thresholds were too high. Lesson: tier thresholds, use consecutive-day rules, reset to local history.
- Mahila Housing Trust (Ahmedabad) parametric heat cover: women pay Rs90 for 4 months, true cost under Rs400 (about 4x subsidy). J-PAL/RCT work shows take-up stays low without experiential learning and subsidy. Lesson: demand for pre-paid heat cover is weak; embed the premium (platform, union, checkout) rather than ask people to buy.
- Basis risk is the main failure mode: temperature did not trigger does not mean income was not lost.
- Igloo x DANA (Indonesia): launched 8 Oct 2026, IDR 500 premium (about 2.8 US cents) buys IDR 50,000 if satellite rain at the buyer's GPS location is 2.5 mm or more on the day of purchase; no claim form, embedded in QRIS checkout. Check the pricing yourself: a 100:1 payout-to-premium ratio means either a very rare trigger or a subsidised/marketing product. Do not copy the ratio.
- Droplet (Income, 2018): premium S$1–9.60/day priced off NEA rain probability, pays up to 60% of fare when raining at pick-up, RPA receipt checks. It never reached workers, households or traders.

## E. Regulation to cite correctly
- MAS FEAT principles (fairness, ethics, accountability, transparency) and Veritas toolkit (open-source fairness/explainability metrics, includes insurance-pricing use case).
- NEW: MAS issued AI risk-management guidelines for financial institutions on 7 Oct 2026 covering conventional AI, generative AI and AI agents. Governance and core risk expectations apply from 7 Oct 2027, AI lifecycle controls from 7 Oct 2028. Requirements: board/senior management accountability, an AI inventory (including embedded third-party AI), risk-materiality assessment (impact, complexity, reliance), fairness and explainability where AI affects underwriting, genuine human oversight with authority to override, third-party AI accountability. In your pitch: list your AI components in an inventory table, mark materiality, show a human override on pricing and on claim disputes, and show the explanation text a customer sees.
- MAS Guidelines on Fair Dealing (revised May 2024) and PDPA (consent, purpose, minimal data) as in brief.

## F. Design rules that follow from the evidence
1. Use multi-tier triggers, not one threshold: heat (WBGT 31 / 32 / 33), haze (PSI 101 / 151 / 201), rain (e.g. nowcast or gauge-based, back-tested). Use consecutive-day logic for heat and haze.
2. Pay a fixed amount per lost day, capped days per season (S$/day tied to lost earnings of ~S$80–100 gross).
3. Choose who pays: platform and union co-pay plus a time-limited subsidy shown on the premium line with an end date (brief rule). Worker pays a few dollars per week at most.
4. Show the no-pay case explicitly in the SMS ("You may lose income and get no payout when the PSI stays under 101").
5. Basis-risk fix: assign trigger station by user's usual zone (cluster of stations) and offer "nearest of N stations" so a single gauge is not the only source, plus a fallback feed.
6. Reinsurance/accumulation: haze hits every customer at once. Show a per-event payout cap and pooled tail (reinsurance quote placeholder). Brief says reinsurance itself is out of scope, but "budget for it" is required.
7. Keep AI small and explainable: use it for tier calibration, price personalisation by exposure (hours worked, zone), fraud checks on eligibility. Provide per-customer explanation and a human override.

## G. Highest-value questions to ask the Income reps (Sun 15 Nov, 12:30)
1. Can we assume the union/platform pays the premium for pilot cohorts? Who is the contract holder (association or Income)?
2. Do you have lost-work-day or claims data for hawkers or platform workers? If not, which proxy do you trust?
3. Acceptable loss-ratio and expense limit (the brief says expenses within about 20% of premium)?
4. Is a PayNow payout acceptable end to end (KYC at onboarding, payout within 24 hours)?
5. Reinsurance appetite for haze accumulation and how it affects the premium.

## H. Pre-flight tasks (do in India this week)
1. Download MSS daily temperature/rain 1980–2026 for 5 stations (Changi, Paya Lebar, Ang Mo Kio, Jurong West, Tengah) and the PSI history; compute how many days per year each tier would fire; check how many of those would have been "real income-loss days".
2. Calibrate a WBGT proxy from temperature+humidity using the 21 months of real WBGT.
3. Build the demo: live feed → tier → payout simulator → "you were paid" SMS → back-test chart.
4. Prepare a one-page "who pays and subsidy end date" table and an AI inventory table (MAS 7 Oct 2026 style).
5. Draft the SMS in English + Mandarin + Malay + Tamil with a teammate who reads them.

## Sources
- NTUC platform-worker protections: https://www.ntuc.org.sg/uportal/news/NTA-NPHVA-NDCA-Secure-Stronger-Protection-Platform-Workers/
- MSE written reply on hawkers insurance: https://www.mse.gov.sg/latest-news/written-reply-to-parliamentary-question-on-insurance-for-hawkers/
- NEA heat stress advisory (MSE press release): https://www.mse.gov.sg/latest-news/press-release-heat-stress-advisory/
- data.gov.sg WBGT dataset: https://data.gov.sg/datasets/d_87884af1f85d702d4f74c6af13b4853d/view
- Historical 24-hr PSI: https://data.gov.sg/dataset/historical-24-hr-psi
- Flood-prone areas: https://data.gov.sg/dataset/flood-prone-areas ; PUB flood forecasting: https://www.pub.gov.sg/Public/KeyInitiatives/Flood-Resilience/Flood-Forecasting-and-Monitoring
- MOM heat stress measures: https://www.mom.gov.sg/heat-stress-measures-for-outdoor-work
- Income Droplet: https://www.income.com.sg/about-us/corporate-information/press-releases/income-launched-singapores-first-rainsurance-to
- Income Stallholder Insurance brochure: https://www.income.com.sg/kcassets/ca4620ee-b077-4c71-b055-8049ccf1cdc5/Stallholder%20Insurance_EN_2024%20web.pdf
- MAS AI guidelines for insurers (Clyde & Co, Oct 2026): https://www.clydeco.com/zh/insights/2026/10/making-ai-work-responsibly
- SEWA / Swiss Re structure: https://www.swissre.com/our-business/public-sector-solutions/insights/parametric-structure-for-sewa-in-south-east-asia.html ; Insurance Journal 2024 payouts: https://amp.insurancejournal.com/news/international/2024/06/12/779147.htm
- Mahila Housing Trust heat cover: https://www.thestar.com.my/aseanplus/aseanplus-news/2026/05/10/too-hot-to-work-too-poor-to-stop-how-insurance-protects-indias-informal-workers-during-heatwaves
- Igloo x DANA: https://www.reinsurancene.ws/igloo-and-dana-launch-parametric-rain-protection-insurance-for-indonesians/
- 2026 haze: https://www.thestar.com.my/aseanplus/aseanplus-news/2026/10/13/haze-in-singapore-persists-24-hour-psi-remains-unhealthy-for-all-regions
- IPS platform workers research: https://lkyspp.nus.edu.sg/ips/news/details/ips-working-paper-no.-47-current-realities-social-protection-and-future-needs-of-platform-food-delivery-workers-in-singapore
