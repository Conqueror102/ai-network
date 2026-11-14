# Decisions Needed (owner: Victor)

Open items a builder cannot decide alone. Everything else in the spec is decided — build it as written.

| # | Decision | Options / context | Needed by |
|---|---|---|---|
| 1 | Product name + bundle IDs | Affects app store IDs, deep-link scheme (`ainet://` placeholder), domains | M0 |
| 2 | First pilot event | Which event, date, expected attendance, organizer relationship | M4 (informs load + copy) |
| 3 | Organizer pricing tiers | e.g. free ≤ 100 attendees / ₦X per 500 / custom — pilot can be free. Also: sponsor slots as a higher tier vs a 15–20% revenue share (PRD §7.1) | M8 |
| 4 | SMS provider for NG | Twilio Verify vs Termii primary (test delivery rates in M1) | M1 |
| 5 | Hosting pick | Railway vs Fly.io (both approved; pick once at M0) | M0 |
| 6 | Legal | Privacy policy + ToS (NDPR compliant), business entity for payments | M8 (pilot), hard for v2 payments |
| 7 | Office Hours policy details | Price bounds final, dispute SLA, charity list | v2 |
| 8 | Premium pricing | Monthly vs event-pass amounts | v2 |
| 9 | Schedule for new organizer revenue features | Sponsor impact reports, white-label branding and pre-event matching (PRD §7) are not in any build milestone yet; assign them to v1.5 or later. Also accept or reject the pilot sponsor tile (PRD §7.2) | Before v1.5 planning |
