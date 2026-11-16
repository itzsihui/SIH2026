# DayCover+ pilot pricing, billing and subsidy

Issue #7 decision proposal for Income Insurance, 13 November 2026.

| Decision | Recommendation | Status |
|---|---|---|
| Premium | S$104 per policy-year, equivalent to S$2/week. Evaluate monthly instalments of about S$8.67. | Indicative pilot price. Income must confirm its costs, risk appetite and terms. |
| Collection | Monthly GIRO direct debit via eGIRO enrolment, administered by Income. | Preferred route. DayCover+ product eligibility, first debit and bank terms are open. |
| Subsidy | Offer an optional S$2 monthly credit for the first six billed months if a sponsor funds it. | Sponsor unconfirmed. Use the full indicative price in the base case. |

## 1. Pricing on the calibrated rules

The pricing model reads the published replay for 123 representative stalls using the 70 mm rain threshold, S$150 haze cap and Singapore daily maximum of hourly regional 24-hour PSI. The 2017–2025 overlap gives S$30.11 per policy-year of combined claims using observed sampled rain payouts and S$42.45 using the pooled Poisson rain scenario. For the pricing view, retain all 11 haze years, including 2015, and fill the two missing rain years with the respective nine-year mean. This gives **S$43.65 and S$55.99** of scenario claims per policy-year. The filled rain years are modeled inputs. The two columns are scenarios and do not form a confidence interval. [Calibrated rules and replay](39_trigger_calibration.md) · [Published backtest input](../public/data/backtest_results.json)

Assume expenses of 20% of gross premium, excluding collection fees. Add S$3.00 per policy-year for monthly collection in the central fee scenario. Use S$15 per policy-year as an illustrative ceded premium for the annual reinsurance layer below. Annual contribution equals gross premium less modeled claims, expenses, collection fees and ceded premium, plus modeled recoveries. Amounts exclude taxes and the cost of capital.

| Weekly equivalent | Annual premium | Expenses | Before reinsurance, sampled rain / pooled rain | After reinsurance, sampled rain / pooled rain |
|---:|---:|---:|---:|---:|
| S$1.50 | S$78 | S$15.60 | S$15.75 / S$3.41 | S$12.32 / S$1.35 |
| S$2.00 | S$104 | S$20.80 | S$36.55 / S$24.21 | S$33.12 / S$22.15 |
| S$2.50 | S$130 | S$26.00 | S$57.35 / S$45.01 | S$53.92 / S$42.95 |
| S$3.00 | S$156 | S$31.20 | S$78.15 / S$65.81 | S$74.72 / S$63.75 |

In the pooled-rain scenario, the price needed for a **10% illustrative contribution target** is S$1.54–S$1.82/week at ceded premiums of S$10–S$20 per policy-year with the modeled recovery credit. At S$2/week the base-case contribution is S$22.15 (21.3%), or S$9.21 (8.9%) if the ceded premium is paid and zero recovery credit is used in pricing. This supports retaining S$2/week as the pilot discussion price while Income validates claims assumptions, fixed onboarding and servicing costs, the treaty quote, capital and hawker affordability.

## 2. What the insurer still bears in a bad year

Illustrate an annual aggregate layer paying up to S$10,000 above S$9,594 of combined eligible claims on the 123-stall cohort. The attachment equals 75% of the cohort’s S$12,792 gross premium at the reference price and stays fixed in the model. Annual result includes expenses and collection fees. The reinsured case also includes the S$1,845 illustrative ceded premium and recovery. This is a sensitivity for discussion with Income and a reinsurer.

| Stress for 123 stalls | Gross claims | Layer recovery | Retained claims | Result without cover | Result with cover |
|---|---:|---:|---:|---:|---:|
| 2015 haze alone | S$18,450 | S$8,856 | S$9,594 | −S$8,585.40 | −S$1,574.40 |
| 2015 haze plus maximum rain payout | S$22,140 | S$10,000 | S$12,140 | −S$12,275.40 | −S$4,120.40 |
| 2019 with observed sample rain | S$15,240 | S$5,646 | S$9,594 | −S$5,375.40 | −S$1,574.40 |
| 2019 with pooled rain scenario | S$17,107.18 | S$7,513.18 | S$9,594 | −S$7,242.58 | −S$1,574.40 |

The 2015 combined stress reaches the modeled combined payout cap of S$180 per policy-year. Income must confirm its capacity to fund payouts as they fall due and its appetite for the residual loss. The annual reinsurance recovery is modeled on an incurred basis and provides no assumption about when cash arrives. The modeled years are too few to estimate the return period of these losses reliably.

## 3. Collect monthly through Income, subject to confirmation

| Route | Evidence and decision |
|---|---|
| **GIRO with eGIRO enrolment** | ABS describes eGIRO as digital setup for recurring GIRO. Income documents eGIRO setup in My Income for issued Life, Health and Personal lines policies, and lists Commercial products among the first-payment GIRO exceptions. Request confirmation of DayCover+ classification and eligibility, the first-payment flow and the monthly mandate. [ABS eGIRO](https://www.abs.org.sg/e-payments/eGIRO) · [Income premium payment methods](https://www.income.com.sg/support/premium-payment-methods) |
| **PayNow QR** | Income documents scan-and-pay for selected products and rejects transfers sent to its UEN for premium payment. Stripe’s PayNow implementation requires customer authorisation for every payment. Keep a bill-specific QR as a manual first-payment or retry fallback if Income supports it for this product. [Income premium payment methods](https://www.income.com.sg/support/premium-payment-methods) · [Stripe PayNow FAQ](https://support.stripe.com/questions/paynow-faq) |
| **Payer standing instruction** | DBS documents scheduled fixed-amount transfers to a designated account. This is a payer-created transfer. For this pilot, prefer a billing-organisation mandate that Income can match to a policy and reconcile. [DBS standing instructions](https://www.dbs.com.sg/personal/support/bank-local-funds-transfer-setup-recurring-funds-transfer.html) |

DBS publishes a general electronic GIRO collection benchmark of S$0.20 and S$1 per unsuccessful collection. Treat these as reference fees pending an Income quote. The model charges the successful fee once per collected instalment and assumes 5% incur one additional failed-attempt fee before recovery. It assumes all scheduled instalments are eventually collected. Income should provide actual decline and recovery rates before launch. [DBS corporate fee schedule](https://www.dbs.com.sg/corporate/forms-and-guides/deposit-account-and-transaction-fees)

| Fee per successful debit | Weekly collection per policy-year | Monthly collection per policy-year |
|---:|---:|---:|
| S$0.05 | S$5.20 | S$1.20 |
| S$0.20 | S$13.00 | S$3.00 |
| S$0.50 | S$28.60 | S$6.60 |

Proposed instalments are S$8.67 for months 1–8 and S$8.66 for months 9–12, totaling S$104. Confirm who issues the first bill, how the mandate and debit references map to a policy, what happens on a return, when reminders and retries run, and which grace or lapse rules Income applies. Reconcile each attempted debit against the bank’s outcome and the policy ledger. For payouts, keep insurer-authorised PayNow disbursement as the proposed rail, with recipient verification, payout status, retry and reconciliation handled by Income. [ABS PayNow](https://www.abs.org.sg/e-payments/pay-now)

## 4. Subsidy option and decision record

Offer S$2 off each of the first six monthly bills for a funded cohort. Gross premium remains S$104 and the hawker pays S$92 over the first policy-year if all six credits apply. Show the S$6.67 first-six-month charge, the final subsidised bill date and the return to S$8.67 in month seven. For 50, 100 and 200 participating hawkers, reserve **S$600, S$1,200 and S$2,400** respectively for credits, plus any separately agreed administration budget.

Use Income-approved eligibility for licensed stall operators at participating pilot centres, one award per policy, subject to a capped funded cohort. Record credit use against the sponsor commitment and reconcile unused funds. If the pilot advances, obtain written confirmation of sponsor identity, amount, eligibility, funding dates, administration and sunset terms before announcing the subsidy. The base case assumes hawkers pay the full indicative premium.

**Decisions for Income.** Confirm the indicative price and affordability test, actual expense and debit fees, acceptable retained stress and risk capacity, eGIRO eligibility and the first-premium flow. Ask whether Income can bring a funding partner and what proof is needed before naming one.

Reproduce the pricing JSON from the repository root with `python -m scripts.price_pilot`. [Machine-readable results](../results/pilot_pricing.json)
