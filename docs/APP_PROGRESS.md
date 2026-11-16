# DayCover Pay: Part 1 app progress (FIN-2 / Algo Sapiens)

Status as of 2026-11-16, evening. Everything here is a **sandbox**: mock Singpass, mock wallet money, no real payments, no real insurer.

## Download and try it

| What | Link |
|---|---|
| **Android app (APK, about 38 MB)** | https://daycover-pay.vercel.app/DayCover.apk |
| iPhone / any browser (installable web app) | https://daycover-pay.vercel.app/app/ |
| Website and landing page | https://daycover-pay.vercel.app |
| Insurer portal (needs the passcode, ask Harsh) | https://daycover-pay.vercel.app/insurer |
| Admin console (activity feed needs the admin token) | https://daycover-pay.vercel.app/console |
| Engine contract (what Part 2 calls on us) | https://daycover-pay.vercel.app/docs/ENGINE_CONTRACT.md |
| Privacy, Terms, Help | `/privacy`, `/terms`, `/help` on the same site |

Android: open the link on the phone, allow "install unknown apps" for the browser, install. If an older DayCover is installed, the new one installs over it. The APK is debug-signed (fine for the demo, not for a store). iPhone: open the web link in Safari, Share, Add to Home Screen.

Demo logins and the mock Singpass people are on the sign-in screen of the app. Anyone can also sign up as a hawker or a customer.

## Tested end to end (live, over mobile data, no cable)

84 automated checks against the live system all pass, plus a payment made through the app's own screens. Covered: hawker sign-up and onboarding, consents, the cap and rate, customer top-up and payment by wallet and by bank, set-amount and permanent QR, refused and duplicate payments, hawker withdraw and send, customer send and request, rewards, signed payouts and rate cards from the engine, the insurer portal, the admin locks, and every web page. Camera scan to pay works on Android (fixed today: the release build was breaking the scanner).

## What the app does

**Customer** (Google Pay style): scan a stall QR with the camera, enter a code, or open a pay link; pay from the DayCover Wallet or a bank; top up, send and request money, activity receipts you can share, scratch-card rewards.

**Hawker**: Today screen with balance and quick actions, total sales, Withdraw and Send, charts, a transaction drawer for every sale (read, share, copy reference), a permanent QR plus a printable sign or a set-amount QR, and a Cover tab with the live deduction and the engine's terms.

**Onboarding**: sign-up or mock Singpass, stall setup with the hawker centre picked from the engine's own list, two required agreements (weekly deduction, payouts to wallet) and three **opt-ins, off by default**: use my past sales for my cap, weather-impact research, keep my transaction history (0 to 90 days). All editable later under Me, Your data choices.

**Insurer portal**: overview (feasibility verdict, 8 headline numbers, contract comparison, loss ratio by year of real weather, risk by region, how light the deduction can be, income impact, weekly collections, payouts), hawkers with a page each, customers, transactions, payouts, analytics.

**Admin console**: demo controls, an activity feed (new accounts, payments, every money movement), the company cover-money account, and the engine status.

## The money flow (what our backend does)

1. Each QR sale holds a small part toward the hawker's **weekly cap**. Cash is never touched.
2. Sunday 23:59 SGT: one debit per hawker into the **company cover-money account** (refs like `CMP-COVER-2026-W34`). Never more than the yearly premium in total.
3. When the engine decides a trigger paid, it sends a **signed payout instruction**; we pay the hawker's wallet once (idempotent on `instruction_id`). It counts toward the stall's yearly haze and rain limits.
4. The engine can also push a cap and rate for a stall.

**The cap is dynamic, using the engine's own rule** (`suggest_weekly_cap`, `configs/collection-v1.json`): base S$104 / 52 = **S$2 a week**. If the hawker opts in to "use my past sales" and has at least 30 days of QR sales, the cap becomes 1.5% of their average weekly QR sales, kept between S$2 and S$4. The yearly price stays S$104; a busier hawker just pays it off sooner. The deduction rate is the cap divided by their average weekly QR sales.

## Integration with the Part 2 engine (Railway)

| Item | State |
|---|---|
| Rules, contract, hawker centres, health | **Live.** Every number we show matches the engine field for field. |
| Signed payout into our wallet, `POST /api/engine/payouts` | **Working** with the exact payload `app_wallet_bridge.py` builds. Repeat = `duplicate:true`, bad signature 401, unknown stall 404, over S$200 400, stall in its 28-day wait = `rejected` with a reason. No payout has come from the engine itself yet: please switch the bridge on (`DAYCOVER_APP_WALLET_BRIDGE=1` and `ENGINE_SHARED_SECRET`). |
| Rate card push, `POST /api/engine/rate-cards` | **Working.** |
| Stall id mapping | `HC###` ids are mapped by centre **name**; always send `centre_name`. `HC123 Zion Riverside` is not in our list. |
| Quote, daily sales (`transactions/ingest`, `collections/suggested-cap`), Sunday confirmation (`collections/.../confirm`) | **Waiting on a token.** Our backend reads it from `RAILWAY_TOKEN`. It needs the scopes `coverage:read`, `transactions:read`, `transactions:retain` and `billing:collect`, and a grant for every stall (a `coverage:read`-only token covers the quote only). |

## Mock vs real (short)

- **Real:** the engine's terms and centres, NEA weather records used for the replay, our money logic (deduction, Sunday debit, company account, signed payouts, limits), consents and the retention wipe.
- **Mock:** Singpass, all wallet money, the bank payment step, PayNow withdraw and send, the weekly debit (no GIRO), the 2025 sales history (synthetic), the demo clock, scratch-card rewards. On the engine side: settlement and billing are simulation only, the contract is not insurer-approved, and final rain decisions are blocked by an unverified NEA rainfall timestamp rule.

Full list: `docs/MOCK_VS_REAL.md` in `harsh-pandhe/sih2026-fin2`.

## Still open

- **Pick one contract** (M1 S$104 vs Plan 4 candidate) with the team and Income. Our system switches with one admin call.
- **Engine token** with the four scopes above, and **switch the bridge on**.
- Wording: we collect weekly; the engine text says monthly GIRO (same yearly total).
- Production would need: a real signing key for the APK, a test on a real iPhone, real Singpass, a licensed wallet or bank, and an approved insurer.

## Where the code is

Repository `harsh-pandhe/sih2026-fin2`, branch `app-wallet-gateway`: Flutter app in `mobile/daycover_app`, Vercel backend in `daycover-pay-system/vercel-app`, docs in `docs/` (`ENGINE_CONTRACT.md`, `MOCK_VS_REAL.md`).
