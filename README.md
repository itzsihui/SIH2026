# SIH 2026 - Team FIN-2

Team repository for the Singapore-India Hackathon 2026 (FinTech / InsurTech track, problem owner: Income Insurance).

## The idea (working title: DayCover+)
A weather-income cover for Singapore's hawkers. When public NEA data shows haze (and, as a pilot, very heavy rain), the stallholder is paid automatically by PayNow, with no claim form. Delivered on WhatsApp and a web/mobile app, with a rules engine that decides, a digital twin that helps design the product, and humans who approve any change. This is a suggestion under discussion, not a final decision.

## Live backend (Railway)
- API: https://sih2026-production-5cd1e09d.up.railway.app
- Health check: https://sih2026-production-5cd1e09d.up.railway.app/api/v1/health
- All endpoints: https://sih2026-production-5cd1e09d.up.railway.app/docs

**Auto-deploy:** Railway redeploys on every push to `main` of this repo. It builds from the `ML pipeline` folder:
- Root Directory: `ML pipeline`
- Build: `pip install -r requirements-daycover.txt`
- Start: `uvicorn src.daycover.api:app --host 0.0.0.0 --port $PORT`

So backend changes go in `ML pipeline/` here and land on `main` (via PR). Changes made only in other repos or branches are **not** deployed.

Mobile app builds point at the API with:
```
flutter build apk --dart-define=API_BASE=https://sih2026-production-5cd1e09d.up.railway.app
```
Simulation only: no real payments. The pilot ledger is SQLite unless `DAYCOVER_PILOT_BACKEND=postgres` and `DAYCOVER_PILOT_DATABASE_URL` are set in Railway, so it resets on every redeploy.

## Where things are
- Team build code lives here. Suggested layout, to be agreed:
  - `engine/` trigger rules, data adapter, simulated payout ledger and audit log
  - `app/` web / PWA app (stall view and insurer dashboard)
  - `payments/` PayNow payout simulation
  - `models/` pricing and digital-twin code
  - `docs/` pitch, slides, notes

## Ground rules
- Official brief: independent public data, understood in about a minute, minimal personal data, no new hardware, no crypto or token insurance, Singapore scope.
- Never commit passports, visas, tickets, IDs, bank details, call recordings or API keys.
- Cite a source for every external fact; mark numbers as computed, assumed or unverified.
- Use short branches and clear commit messages; tell the team before changing someone else's folder.

## Timeline
Semi-final 16 Nov, final 17 Nov 2026 (Singapore). Aim: a working thin slice (engine, simulated payout, WhatsApp sandbox flow, app) before the event.
