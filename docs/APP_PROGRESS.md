# DayCover Pay: Part 1 app progress (FIN-2 / Algo Sapiens)

Status as of 2026-11-16. Everything here is a **sandbox**: mock Singpass, mock wallet money, no real payments, no real insurer.

## Download and try it

| What | Link |
|---|---|
| **Android app (APK, about 32 MB)** | https://daycover-pay.vercel.app/DayCover.apk |
| iPhone / any browser (installable web app) | https://daycover-pay.vercel.app/app/ |
| Website and landing page | https://daycover-pay.vercel.app |
| Insurer portal (needs the passcode, ask Harsh) | https://daycover-pay.vercel.app/insurer |
| Operator console | https://daycover-pay.vercel.app/console |
| Engine contract (what Part 2 calls on us) | https://daycover-pay.vercel.app/docs/ENGINE_CONTRACT.md |
| Privacy, Terms, Help | `/privacy`, `/terms`, `/help` on the same site |

Android: open the link on the phone, allow "install unknown apps" for the browser, install. The APK is debug-signed (fine for the demo, not for a store). iPhone: open the web link in Safari, Share, Add to Home Screen.

Demo logins and the mock Singpass people are on the sign-in screen of the app.

## What the app does

**Customer** (UPI / Google Pay style): scan a stall QR with the camera, or open a pay link; pay from the DayCover Wallet; top up, send and request money, activity receipts you can share, scratch-card rewards.

**Hawker**: total sales, wallet balance, Withdraw and Send, a 14-day chart, filter chips, and a transaction drawer for every sale (read, share, copy reference). A permanent QR (payer types the amount) plus a printable sign, or a set-amount QR. A Cover tab shows the live deduction.

**Onboarding**: mock Singpass or sign-up, stall setup with hawker centre picked from the engine's own list, required agreements (weekly deduction, payout to wallet), and **opt-in** choices that are off by default: use my past sales for my deduction rate, weather-impact research, keep my transactions (0 to 90 days). All editable later under Me, Your data choices.

**Insurer portal**: overview with the contract picker and a side-by-side comparison, hawkers (and per-hawker pages), customers, transactions, payouts, analytics. Feasibility replay of real PSI (2014 on) and rain (2017 on) under either contract.

## The money flow (what our backend does)

1. Each QR sale accrues a small deduction held against the stall, up to a **weekly cap**.
2. Once a week (Sunday 23:59 SGT) one debit moves the held amount into the **company cover-money account** (ledger refs such as `CMP-COVER-2026-W34`).
3. When Part 2 decides a climate trigger paid, it sends a **signed payout instruction**. We credit the hawker wallet from the company account, once only (idempotent on `instruction_id`).
4. Part 2 can push a rate card per stall (weekly cap and rate) to us.

Under the M1 contract the system runs today (`daycover-pilot-m1-2026.11-v1`): S$104 a year, so the weekly cap is S$104 / 52 = **S$2 for everyone**. Only the **rate** is personal, set from the hawker's own weekly QR sales when they opt in, so the cap is reached evenly. Cash sales are never touched.

## Integration with the Part 2 engine (Railway)

| Item | State |
|---|---|
| Engine public API read by the app (rules, contract, hawker centres, health) | Working. The app shows live terms (S$104, 70 mm rain, haze caps) and the 123 centres. |
| Signed payout into our wallet, `POST /api/engine/payouts` | Working. Tested with the exact payload the bridge in `app_wallet_bridge.py` builds (extra fields ignored, response matches what the bridge expects). Repeat gives `duplicate:true`, bad signature gives 401, unknown stall 404, over S$200 gives 400. |
| Rate card push, `POST /api/engine/rate-cards` | Working on our side. |
| Stall id mapping | The engine's `HC###` ids are **not** our centre numbers. We map by centre **name**. The engine sends `centre_name` in the payload, which is what we need. `HC123 Zion Riverside` is not in our list. |
| Rate quote from the engine (`POST /api/v1/quotes`) | Adapter written. Needs an engine login (alias and password) for our backend, not yet provided. |
| Our daily sales to their `transactions/ingest` and `collections/suggested-cap` | Not wired yet. Waiting on a login with the right scopes. |
| Our Sunday collection total to their `collections/.../confirm` | Not wired yet, same reason. |

## Known gaps

- **Contract not chosen.** We run M1 (S$104, monthly in their text) while their repo also carries a Plan 4 research candidate (S$150 annual combined cap, illustrative premium S$87). The team and Income need to pick one; our system can switch with one admin call.
- Our deduction is weekly. Their text says monthly GIRO. The numbers agree (S$104 a year) but the wording should match.
- Retention days are stored but not yet enforced. Heat and flood are not wired (the rules say not payable).
- iPhone web app is built but not tried on a real iPhone. The Android APK is debug-signed.
- Everything is simulation: no real bank, no real Singpass, no real insurer approval.

## Where the code is

Repository `harsh-pandhe/sih2026-fin2`, branch `app-wallet-gateway`: Flutter app in `mobile/daycover_app`, Vercel backend in `daycover-pay-system/vercel-app`, docs in `docs/` (including `ENGINE_CONTRACT.md`).
