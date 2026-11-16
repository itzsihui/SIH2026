# DayCover Pay — premium-at-checkout, fixed so it works (design v1, 13 Nov 2026)

Status: proposal for Harsh and Ankita. Phase 1 (NEA-triggered cover, rules decide, AI explains) is unchanged. This document makes the checkout idea defensible. Everything about the gateway is a demonstration on a mirror rail; it never claims to change SGQR.

## 1. The idea in one paragraph
A demo-mode payment gateway that mirrors the SGQR/PayNow customer flow. Hawkers choose a plan. A small, calculated share of their QR sales is set aside as the insurance premium until that period's instalment is met, then collection stops. When an NEA trigger is hit, the engine pays the hawker into their wallet the next day. The insurer sees sign-ups, QR sales, premium progress and accumulation. Hardware (soundbox, printed stands) is optional.

## 2. What the research supports
- **Small, frequent premium payments raise take-up.** A natural experiment with about 200,000 female microcredit customers reported 59–74% higher demand for insurance when they could pay in weekly instalments instead of one lump sum (summary of the Wagner/NYU study "Paying in Pieces"; I could not open the paper page, so confirm the figure before quoting). CGAP's guidance on mobile microinsurance also centres on premium payment method.
- **Embedding parametric cover in a national QR flow is already being done.** Igloo and DANA launched DANA Rain Protection (reported 8 Oct 2026): IDR 50,000 paid automatically when rainfall at the user's location reaches 2.5 mm that day, embedded into DANA's QRIS payment flow, validated with satellite precipitation data and GPS. The premium is not published. This is a precedent for our demo, not proof it sells.
- **SGQR facts.** SGQR is co-owned by MAS and IMDA; one label combines several schemes (PayNow is one of them); acquirers join as SGQR members. Merchant acquisition (processing payments for merchants) is a regulated payment service under the Payment Services Act, with Standard and Major Payment Institution licences (Standard is capped at S$3m monthly transactions per activity). So in real life DayCover does not run the rail; Income instructs a licensed acquirer.

## 3. Flaws in the first version and the fixes

| Flaw | Fix |
|---|---|
| Premium depends on sales, so it is hard to price and falls when it rains | **The price is fixed** (indicative S$104 a year, from `docs/41_pilot_pricing_and_billing.md`). The levy is only a *collection method*. Premium is split into monthly instalments (S$8.67 ×8, S$8.66 ×4). |
| Per-transaction S$0.02 and a S$2.21 weekly cap are arbitrary | Replace with a **calibrated levy rate per stall**: instalment ÷ expected monthly QR sales, reset each month from the trailing three months. The rate is shown as cents per sale. |
| Quiet weeks undercollect | **Monthly horizon with carry-forward** of up to one instalment, and a **year-end true-up** by bank debit for any remainder. The instalment cap stops collection once met. |
| Cash stalls would pay nothing | Eligibility needs a minimum QR share of sales; otherwise the plan falls back to bank debit. |
| "Auto sign-up without asking" | **Opt-in at QR activation** with the one-sentence disclosure, and a cooling-off period per Income's terms. Fair-dealing and PDPA require consent. |
| "AI decides the trigger from satellite and other factors" | **Triggers stay on NEA indices** that are independent, published and long-run. Satellite precipitation is a **cross-check or fallback**, not the decider. AI roles that are defensible: (a) forecast a stall's sales to calibrate the levy rate, (b) size payouts to expected loss within the caps, using consented sales data, (c) anomaly and fraud flags. None of these is built yet. |
| Dry-year credit | See section 5. |
| Hardware | Optional extra. The soundbox is simulated on the phone. A printed QR stand needs no hardware. |

## 4. Does the long-period premium work? (simulation, assumptions only)
`scripts/premium_accrual_sim.py`, 500 runs per profile. Assumptions: S$5 ticket, 10% of days hit by rain or haze with sales halved, calibrated rate, one-instalment carry-forward, year-end true-up. There is no real transaction data, so this shows the mechanics, not a forecast.

| Stall profile | Share of S$104 collected by the levy | Bank top-up per year | Average levy rate | Cents per S$5 sale |
|---|---:|---:|---:|---:|
| Light, 6 QR sales/day | 99.8% | S$0.22 | 1.04% | 5.2 |
| Medium, 14/day | 99.8% | S$0.16 | 0.44% | 2.2 |
| Busy, 30/day | 99.9% | S$0.10 | 0.20% | 1.0 |
| Declares 14/day, really sells 7 | 99.8% | S$0.23 | | |

What it shows: with a calibrated rate and carry-forward the hawker pays the same S$104 whatever they sell; only the cents per sale change. About half of the months met the instalment by the levy alone, which is why the carry-forward is needed. What it does not show: how real stalls behave, or whether hawkers accept a variable deduction.

## 5. Dry-year credit: handle with care
The replay (123 stalls, 2017–2025) found 400 of 1,107 stall-years (36%) with no paid event, but this is an upper bound: rain history is a sample covering about a fifth of days, and at 70 mm a stall averages about four trigger days a year, so true "no payout" years are probably few. Haze alone paid nothing in 923 of 1,107 stall-years (83%). A credit defined on "no payout at all" would rarely apply; one defined on "no haze payout" would apply to most stalls. Ankita's base-case contribution is about S$22 a policy-year, so a credit of 5% of premium (S$5.20) for a haze-free year costs about S$4.30 on average and is affordable. Decide the definition with Income, and price it into the premium before showing it as a benefit.

## 6. Using YouPI-PG as the base: what I found
- **Licence:** GitHub shows no licence and the repo has no licence file, so by default you may not copy or modify it. Ask the maintainers for permission, or use it only as reference.
- **Architecture:** it is built for India's UPI. It confirms payments by reading bank SMS and Gmail alerts and matching exact amounts, and it allows only one active payment session per receiving account at a time, with the others in a queue. That cannot serve a busy stall. Its README limits testing to about 20 payments a day per account and calls itself experimental.
- **Reusable:** the checkout page look, merchant admin shell, SDK layout and live-update plumbing.
- **To replace:** the rail (use a simulated SGQR/PayNow-style QR and simulated settlement events), the SMS and Gmail observers, the WhatsApp OTP login, and the single-session queue.
- **My estimate:** extending our own `phase2-gateway-demo/` is about a day. Reworking YouPI is three or more days, plus the licence question. For a demo-mode rail, ours is the faster route; borrow YouPI's ideas, not its code, unless the licence is sorted.

## 7. What to build for the demo (in order)
1. Plan chooser (Haze, Rain, Both) showing the annual price and monthly instalment.
2. Premium account for one stall: instalment target, levy rate, progress, "collection paused for this month".
3. Sales simulator ("100 sales") that runs the real accrual logic.
4. Trigger to payout: call the existing engine for a historical date and credit the wallet the next day.
5. Insurer admin: sign-ups, QR sales, premium accrued against schedule, shortfalls, payouts, accumulation.
6. Optional tab: soundbox simulator and printable QR stand.
Mark each screen as real (engine, rules, data) or simulated (rail, sales, wallet).

## 8. How to say it to the judges
"We can't change SGQR, so we built a mirror rail to show the idea. The price is fixed and actuarial; the checkout share only changes how it is collected. Triggers are NEA readings. AI forecasts sales to set the share and flags anomalies; it never decides a payout. In real life Income would use a licensed acquirer; this is a demonstration."

## 9. Open questions for Income and an acquirer
Can an acquirer deduct an instruction-based premium instalment before settlement? Who issues the policy and holds the money? Consent flow and cooling-off? Does it count as a regulated activity for DayCover? What does a stall's real QR share look like?

## Sources
[MAS SGQR](https://www.mas.gov.sg/development/e-payments/sgqr) · [IMDA SGQR launch](https://www.imda.gov.sg/Content-and-News/Press-Releases-and-Speeches/archived/IMDA/Press-Releases/2018/singapore-introduces-world-first-unified-payment-qr-code-sgqr) · [Reinsurance News on DANA Rain Protection](https://www.reinsurancene.ws/igloo-and-dana-launch-parametric-rain-protection-insurance-for-indonesians/) · [Paying in Pieces (Wagner/NYU)](https://wagner.nyu.edu/impact/research/publications/paying-pieces-natural-experiment-demand-for-life-insurance-under) · [CGAP: premium payment methods](https://cgap.org/node/2391) · [Payment Services Act guide](https://www.reedsmith.com/en/perspectives/2020/01/payment-services-act--a-guide) · [YouPI-PG](https://github.com/youpi-pg/YouPI-PG)
