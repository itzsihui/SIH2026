# SIH 2026 - Team FIN-2

Team repository for the Singapore-India Hackathon 2026 (FinTech / InsurTech track, problem owner: Income Insurance).

## The idea (working title: DayCover+)
A weather-income cover for Singapore's hawkers. When public NEA data shows haze (and, as a pilot, very heavy rain), the stallholder is paid automatically by PayNow, with no claim form. Delivered on WhatsApp and a web/mobile app, with a rules engine that decides, a digital twin that helps design the product, and humans who approve any change. This is a suggestion under discussion, not a final decision.

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
