# PRD — AiNetwork (working title)

**Version:** 0.1 · **Date:** 2026-07-11 · **Owner:** Victor

## 1. Vision

An event networking platform where an AI "wingman" does the scary parts of networking — discovery, matching, first contact, icebreaking — so humans only do the part that matters: the real conversation. Not a replacement for human networking; *a friend you get* at every event.

## 2. Problem

At conferences and events:

- **Discovery is broken.** Among 500–5,000 attendees, finding the 5 people worth your time is luck.
- **Initiation is terrifying.** Introverts (and most people) won't cold-approach strangers. The walk over is the barrier, not the conversation.
- **Follow-up dies.** Business cards and LinkedIn adds convert to nothing; relationships go cold within a week.
- **Organizers can't prove value.** They sell tickets and sponsorships with no data showing their event created real connections.

## 3. Core principles (product constitution)

1. **Rejection-proof by design.** All first contact is double opt-in. Declines are silent. Nobody ever feels rejected.
2. **AI advises and drafts; humans approve and meet.** The AI never sends anything autonomously in v1. Approval-first is the trust model, not a setting.
3. **Anything that makes the human moment feel manufactured is banned.** Anything that makes the human better-prepared is welcome.
4. **Privacy by architecture.** No precise location, no map pins, no distance numbers, no real addresses. Proximity only as coarse buckets ("right here" / "at the event"), and only via Bluetooth range — which requires being physically present, so radar can never tell you more than your own eyes could.
5. **The organizer is the customer; the attendee is the user.** Distribution happens at the event door (QR check-in), not the app store.

## 4. Personas

| Persona | Description | Primary pain |
|---|---|---|
| **The Introvert Builder** | Developer/founder, hates cold approaches, great in 1-on-1s | Initiation anxiety, bad discovery |
| **The Deal Hunter** | Sales/BD professional, attends to generate pipeline | Time pressure, lead qualification |
| **The Organizer** | Runs conferences/meetups, 200–5,000 attendees | Attendance ops, proving ROI to sponsors |
| **The Exhibitor** | Company with a booth, pays for leads | Lead capture is clunky and expensive |

## 5. Product surfaces

1. **Attendee mobile app** (React Native/Expo) — profile & persona, event browsing/apply, QR check-in, matching feed, intro cards, chat with AI wingman, radar "say hi", per-event contact CRM, follow-up reminders.
2. **Organizer web dashboard** (Next.js) — event creation, gating rules, QR generation, live attendance, announcements, analytics/ROI reports, monetization tools.
3. **Backend platform** (FastAPI) — matching engine, chat infra, presence, AI layer, payments.

## 6. Feature scope

### v1 — "One great event" (MVP, target: run at 1 real event)

| # | Feature | Notes |
|---|---|---|
| 1 | Auth + verified identity | Phone/email OTP; real human verified to platform; display persona per event |
| 2 | Attendee profile + per-event goals | Structured goal objects, AI parses free text/voice into schema |
| 3 | Event creation + QR check-in + gating | Organizer sets open/apply-only; scan at door marks attendance |
| 4 | Event room: attendee directory | Only checked-in attendees, reciprocal visibility |
| 5 | Matching engine | Two-way goal scoring, top-10 feed with "why you two" |
| 6 | Intro flow (double opt-in) | AI-drafted intro card → one-tap approve → recipient accepts/declines silently; "maybe later" resurfaces once next morning |
| 7 | 1:1 chat with AI wingman | AI-seeded icebreakers, reply suggestions, tone control (formal/casual/warm/funny) |
| 8 | Meet logistics | Suggest time + named meeting point; tap-to-exchange contact logs a real meeting |
| 9 | Organizer dashboard (basic) | Event setup, live attendance count, announcements push |
| 10 | Safety basics | Block (bidirectional, permanent), report, message retention policy |

### v1.5 — "Serendipity + proof"

- **Radar / "say hi"** — two layers, no venue hardware: (1) event-wide discoverable list of checked-in attendees (always works); (2) "right here" mode — Bluetooth phone-to-phone proximity while the radar screen is open, nearest-first in coarse buckets ("right here" / "in the area"), never exact distance. Photo-required visibility, ghost mode, wave lifecycle with silent expiry, mutual-wave instant match. Zone QRs are **not** part of radar — they survive only as optional organizer session-attendance analytics.
- **Session-aware matching** — shared-session signal + icebreaker.
- **Post-event summary** — "you met 9 people, 3 drafted follow-ups."
- **Organizer connection-ROI report** — accepted intros, meetings made, attendee-quality breakdown.
- **Exhibitor lead capture** — booth QR → tap-to-exchange → lead list export.

### v2 — "The relationship layer"

- **Office Hours** — organizer-approved VIPs (speakers, investors, notable guests) offer paid 15-min meeting slots (set price or donate to charity); attendees book and pay in-app; platform takes 15–20%. Solves VIP opt-in (price filters their spam) and adds a revenue stream. Guardrails: separate section of the app, never mixed into the match feed; tap-to-exchange confirms the meeting happened; no-show → refund.
- Follow-up reminders + nurturing suggestions (AI drafts check-ins, shares relevant articles).
- **City graph** — self-declared coarse area, visible only to accepted connections; post-event "3 of your DevCon connections are in Lagos" meetup suggestions; pre-event same-city pairing; travel mode.
- Voice notes with AI tone shaping.
- Ticketing (simple paid events, Stripe + Paystack).
- Sponsored meeting points, sponsor tiles, featured events in discovery.
- Attendee premium tier.

### Explicitly out of scope (all versions)

- Autonomous avatar-to-avatar conversations (AI-to-AI negotiation).
- "Flirt" mode or dating features at professional events.
- Precise location, distances to individuals, map pins on people.
- Real street addresses for social features.
- Public reputation ratings of people.
- Always-on "people near me in daily life" outside event context.

## 7. Monetization

| Stream | Who pays | When |
|---|---|---|
| Event SaaS (tiered by attendee count) | Organizer | v1 |
| Exhibitor lead capture (per booth) | Exhibitor | v1.5 |
| Connection-ROI premium reports | Organizer | v1.5 |
| Sponsor inventory (meeting points, tiles) | Sponsors via organizer | v2 (one sponsor slot trialled at pilot, see 7.2) |
| Sponsor ad slots: sponsored pushes, goal-matched booth nudges, sponsored post-event recap | Sponsors via organizer | v2 |
| Sponsor lead / impact reports (views, taps, booth visits, contacts exchanged) | Sponsors via organizer | Unscheduled (see DECISIONS-NEEDED #9) |
| White-label branding (event colours, logo, custom name) | Organizer | Unscheduled, higher tier (see DECISIONS-NEEDED #9) |
| Pre-event matching & engagement (matches sent 2–3 days before doors open) | Organizer | Unscheduled, higher tier (see DECISIONS-NEEDED #9) |
| Ticketing fee (% per paid ticket) | Attendee (pass-through) | v2 |
| Office Hours booking fee (15–20% per paid VIP meeting) | Attendee (VIP earns the rest) | v2 |
| Attendee premium (advanced search filters, unlimited waves, AI meeting briefs, who-viewed-you) | Attendee | v2 |

**Free/paid red lines:** basic directory browsing, matching, and daily waves stay free forever (network liquidity is the product's oxygen). Premium buys *tools for yourself* — filters, volume, briefs — never *access to others*: no paid ranking boosts, no paid placement in match feeds, ever.

### 7.1 Sponsor advertising through the organizer

Organizers already sell sponsorship packages. Everyone at the event has the app open, so in-app sponsor slots give organizers a new, measurable thing to sell, and turn the product from a cost into a revenue source for them.

Formats:
- **Sponsor tile** in the event room / home screen ("Coffee by X, booth 4").
- **Sponsored meeting points** — the suggested meet spot becomes the sponsor's lounge or booth.
- **Sponsored announcements** — capped at 1–2 pushes per attendee per day so people don't mute the app.
- **Goal-matched booth nudges** — "You're hiring developers; Y is at booth 7." Shown only when the attendee's own goals match the sponsor's declared offer.
- **Sponsored post-event recap** — "Your event summary, brought to you by Z."
- **Sponsor impact report** — aggregate views, taps, booth visits and contacts exchanged, so the organizer can prove value and charge more next year.

How we earn: either (a) sponsor slots unlock in a higher organizer tier, or (b) a revenue share of 15–20% on what sponsors pay the organizer for in-app inventory. Revenue share is preferred for early pilots because it costs the organizer nothing upfront.

Guardrails (extend the red lines above):
1. Sponsors appear **beside** matches, never **as** matches. No sponsor is ever presented as a person you should meet, and sponsor spend never affects match scores, feed order or wave queues.
2. Sponsors see **aggregates only**. An individual attendee's contact reaches a sponsor only when that attendee exchanges it themselves (booth tap-to-exchange).
3. Every sponsored surface is clearly labelled as sponsored.

### 7.2 Sequencing

| Stage | Revenue focus | Why |
|---|---|---|
| Pilot (event 1) | Free for the organizer; trial **one** paid sponsor slot | A sponsor paying anything is the strongest early proof of willingness to pay |
| Events 2–10 | Organizer SaaS tiers + exhibitor lead capture | Simple, familiar purchases for organizers and exhibitors |
| Repeat organizers | Ticketing fee, Office Hours, attendee premium | Need trust, volume and repeat usage first |

**Pilot sponsor slot delivery.** No v1 surface carries a sponsored label today, so the pilot slot needs one small addition to v1 scope: a single **sponsor tile** in the event room (sponsor name, logo, one line, booth/location), rendered with a fixed "Sponsored" label by the client (not editable by the organizer), configured by the organizer in the dashboard and screened by `safety_screen`. Organizer announcements are **not** used for sponsor content, because they have no sponsor identity or label field. If this addition is not accepted into v1, the pilot slot is out of scope and the pilot tests willingness to pay with a signed letter of intent from a sponsor instead.

### 7.3 Two-sided dependency

Organizers bring distribution and money; attendees create all the value organizers pay for (connections, sponsor views, booth leads). Early on we depend on organizers to get into each event. Over time, if attendees keep their profile and connections across events (follow-ups, city graph), they arrive at the next event already on the app, and organizers come to depend on us. Rule of thumb: **sell to organizers, build for attendees.**

## 8. Success metrics

**North star:** confirmed in-person meetings per checked-in attendee (via tap-to-exchange).

| Metric | v1 target at first event |
|---|---|
| Check-in → profile completion | ≥ 70% |
| Attendees who send ≥1 intro | ≥ 40% |
| Intro accept rate | ≥ 35% |
| Accepted intro → real meeting | ≥ 30% |
| Post-event D7 app retention | ≥ 25% |
| Organizer willing to pay for next event | Yes/No (the only metric that really matters) |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Cold start / low opt-in at event | Organizer-led distribution: check-in **is** the app install; app is the event's official tool |
| Harassment via chat/radar | Double opt-in everywhere, structured first contact (no free text), block/report day one, photo-required radar |
| AI-drafted messages feel fake | Human approval on everything; drafts trained on user's own voice/goals; tone controls |
| Feature creep before first event | v1 list above is frozen; new ideas go to v1.5+ backlog |
| Chat data liability | Retention policy, GDPR/NDPR-style handling, encryption at rest, minimal PII |
| Organizer sales cycle slow | Start with 1 friendly event (meetup/mid-size conf) where we have a relationship |

## 10. Open questions

- Working name + branding.
- First target event (which, when, expected attendance).
- Pricing anchors for organizer SaaS tiers.
- Office Hours: price bounds, no-show/refund policy details, who qualifies as "VIP" (organizer-approved vs platform criteria).
