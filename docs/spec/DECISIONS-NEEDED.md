# Decisions Needed (owner: Victor)

Open items a builder cannot decide alone. Everything else in the spec is decided — build it as written.

| # | Decision | Options / context | Needed by |
|---|---|---|---|
| 1 | Product name + bundle IDs | Affects app store IDs, deep-link scheme (`ainet://` placeholder), domains | M0 |
| 2 | First pilot event | Which event, date, expected attendance, organizer relationship | M4 (informs load + copy) |
| 3 | Organizer pricing tiers | e.g. free ≤ 100 attendees / ₦X per 500 / custom — pilot can be free | M8 |
| 4 | SMS provider for NG | Termii primary + Twilio backup recommended (00 §3); confirm after delivery-rate test | M1 |
| 5 | Hosting pick | Decided 2026-11-14: Render (API/worker/cron) + Vercel (web) + Cloudflare (DNS/WAF/R2) | Done |
| 6 | Legal | Privacy policy + ToS (NDPA 2023 compliant), business entity for payments | M8 (pilot), hard for v2 payments |
| 7 | Office Hours policy details | Price bounds final, dispute SLA, charity list | v2 |
| 8 | Premium pricing | Monthly vs event-pass amounts | v2 |
| 10 | First payment provider | Decided 2026-11-14: **Bachs** (https://bachs.io/) behind the `PaymentProvider` adapter. Still to check: bulk payouts to third parties for Office Hours (11 §9.4) | Done (payouts check before v2) |
| 11 | Default LLM provider per task after pilot | Re-run evals across providers with pilot data; keep or switch per task (06 §1a) | Post-pilot |
