# 01 — Product Specification (exact feature behavior)

Each feature: purpose → rules (numbered, testable) → edge cases → analytics events. Versions: **[v1]** ship for pilot event, **[v1.5]** immediately after, **[v2]** later. Analytics events are logged server-side to the `analytics_events` table (see 02 §16).

## 1. Onboarding & Auth [v1]

**Purpose:** verified-human accounts with minimal friction.

Rules:
1. Sign-up requires exactly one verified channel: phone (SMS OTP) **or** email (code). 6-digit OTP, expires 10 min, max 5 attempts, then a new code is required. Resend cooldown 60s.
2. On first verification, create `users` row + issue JWT pair. Profile completion happens after auth, progressively (skippable except display name).
3. Session model: access token 15 min, refresh token 30 days, rotating (each refresh invalidates the previous refresh token; reuse of a rotated token revokes the whole family — see 08 §2).
4. One account per phone/email. Re-verification of an existing channel = login, not signup.
5. Deleting account: soft-delete immediately (`users.deleted_at`), hard-delete PII after 30 days via job. Conversations show "Deleted user".

Edge cases: OTP delivery failure → allow channel switch; clock skew → server time authoritative; user signs up mid-event → full flow must be completable in < 90 seconds (measure it).

Analytics: `auth.otp_sent`, `auth.verified`, `auth.signup_completed`, `profile.completed`.

## 2. User profile (global) [v1]

Fields: `real_name` (private, verification only), `display_name`*, `photo_url`, `headline` (≤ 80 chars), `bio` (≤ 600), `role_title`, `company`, `industry` (picker), `skills` (≤ 10 tags, picker+freeform), `links` (≤ 5 URLs, validated), `home_area_code` (picker, optional, v2 surfaces).

Rules:
1. `display_name` required before joining any event.
2. Photos: uploaded to R2 via presigned URL; server generates 512px and 128px variants; original discarded. Content-moderation screen (AI, see 06 §4.6) before the photo becomes visible; until approved, placeholder initials avatar shown.
3. Global profile is the template; per-event `event_profiles` can override display name/photo/headline (see §4).

## 3. Events: create, discover, apply, check in [v1]

### 3.1 Organizer creates event
1. Organizer account = `organizers` org + `organizer_members` (roles: `owner`, `staff`). Any authed user can create an organizer org (self-serve).
2. Event fields: name*, description, venue name*, city* (picker), address (free text, shown only to registered attendees), `starts_at`*, `ends_at`*, capacity (optional), `gating` = `open` | `apply`, cover image, sessions (optional list: title, room, starts/ends).
3. On publish, server generates: one **door QR** (rotating token, see rule 3.4), per-session QRs (static), event deep link.
4. Door QR token rotates every 60s (TOTP-style, seeded per event) rendered on the organizer's "door screen" web page — prevents remote check-ins from a screenshot. Printed fallback QR (static, organizer can enable) accepted with the tradeoff logged.

### 3.2 Discovery & registration (attendee)
1. Event list: upcoming public events, filterable by city; events the user registered for pinned on top. Search by name.
2. `open` events: "Register" → instant `event_applications` row with `status='approved'`.
3. `apply` events: "Apply" → `status='pending'`; organizer approves/rejects in dashboard (bulk actions). Push on decision.
4. Private events: `visibility='unlisted'` — join only via deep link/QR.

### 3.3 Check-in
1. Attendee scans door QR → `POST /v1/events/{id}/checkin`. Server validates token freshness (±90s window) and application status.
2. If `gating='apply'` and not approved → response `checkin_not_approved`, app shows polite "This event requires approval — apply here."
3. Successful check-in: create `checkins` row (`zone_id` NULL), unlock event room, enqueue `matching.compute_for_user`, increment organizer live counter (WS push to dashboard).
4. Re-scanning is idempotent (one check-in row per user/event/day).
5. Walk-up (no prior registration) at `open` events: register+check-in in one step.

### 3.4 Session QRs [v1.5]
Scanning a session QR writes `checkins` row with `zone_id`. Used ONLY for: organizer session analytics + shared-session match boost. Never displayed to other attendees, never feeds radar.

Analytics: `event.registered`, `event.applied`, `event.checkin`, `event.session_checkin`.

## 4. Event profile & visibility [v1]

1. On first entry to an event room, user completes an **event card**: display name (prefilled), photo (prefilled), headline, "what I bring" (`offer_text`, ≤ 200 chars), and visibility.
2. Visibility levels (single enum, exact semantics):
   - `hidden`: not in directory, not in radar, not matchable. Can still browse nothing (reciprocity), can chat with existing connections.
   - `directory`: appears in directory and matching; not in radar list.
   - `radar`: everything in `directory` + appears in radar (Layer 1 + Layer 2). **Requires an approved face photo** (server enforces).
3. Default visibility = `directory` (chosen at event-card step, user must actively pick — no dark patterns; copy explains each level).
4. Reciprocity enforcement: directory browsing requires ≥ `directory`; radar browsing requires `radar`.

## 5. Goals [v1]

1. A user has 1–3 active goals per event, each: `intent` (enum: `hire, get_hired, raise, invest, sell, buy, learn, cofounder, partner, meet`), `target` (roles[], industries[], stage[] — all optional), `offer` (text ≤ 300), `priority` (1..3, unique per user/event).
2. Input UX: user types or dictates free text → AI parses to the structure (06 §4.1) → **user reviews an editable form** → save. User can also fill the form manually, skipping AI.
3. Goals are editable anytime; every save re-embeds and enqueues incremental re-match.
4. Goals expire at event end (`status='archived'`); "carry to next event" is one tap when joining a new event.

Edge: unparseable input → AI returns `intent='meet'` + raw text as offer, form opens for manual fix. Offensive content → safety screen blocks with generic "couldn't save this" + report to moderation log.

Analytics: `goal.created`, `goal.ai_parsed`, `goal.edited`.

## 6. Matching & match feed [v1]

Full algorithm in `05-matching-engine.md`. Product rules:

1. Feed shows up to 10 cards, of which up to 2 are wildcards (labeled "Wildcard — outside your goals, might be interesting").
2. Each card: photo, display name, headline, **"why you two"** (1–2 sentences, grounded), matched-goal chips, actions: `Introduce me`, `Skip`, `View profile`.
3. `Skip` hides the card for this event and logs a negative label. Skipped users can still wave at the skipper (skip is private).
4. Feed refresh: on check-in, on goal edit, and every 30 min during event hours; pull-to-refresh allowed (min 60s throttle).
5. Feed excludes: blocked (both ways), already-waved (any status), existing connections, `hidden` users, self.
6. Empty state (< 3 candidates): show directory search entry point + "waiting for more check-ins".

Analytics: `match.feed_viewed`, `match.card_skipped`, `match.card_expanded`.

## 7. Waves & intro cards [v1]

The wave is the ONLY first-contact mechanism (match feed and radar both create waves).

1. Sender taps `Introduce me` (feed) or `Say hi` (radar/directory) → server builds the **intro card**: sender's event card + "why you two" (feed source) or "you're both at {event}" (radar source) + optional one-liner the sender writes (≤ 140 chars, must pass AI safety screen before the wave is created; on fail, sender sees "try different wording", wave not created).
2. Sender confirms a preview → wave created with `status='pending'`. Push to recipient.
3. Recipient actions: `Accept` / `Not now` / `Maybe later`.
   - Accept → conversation created, both notified, wingman seeds icebreakers.
   - Not now → `status='not_now'`. **Sender-visible state remains "pending" forever.** No push, no read receipt, nothing.
   - Maybe later → `status='maybe_later'`; job resurfaces the card to the recipient at 09:00 recipient-local next day, once (`resurfaced=true`). Second ignore/decline → `not_now` silently.
4. Rate limits: free tier 5 waves per rolling hour per event (premium: unlimited [v2]); 1 wave per (sender, recipient, event) ever; recipient-side inbox cap 50 pending (overflow waves queue and deliver as slots free — protects popular people).
5. Mutual pending waves (A→B and B→A both pending): server auto-accepts both, creates conversation, both get "You noticed each other 🎉" push.
6. Expiry: at `event.ends_at + 24h`, all `pending`/`maybe_later` waves → `expired` silently.
7. Wave send while recipient checked out/left: allowed (they see it when they open the app).

Analytics: `wave.sent`, `wave.accepted`, `wave.not_now`, `wave.maybe_later`, `wave.mutual`, `wave.expired` (aggregates only for organizer analytics; individual decline events never exposed).

## 8. Chat & wingman [v1]

1. Conversations are strictly 1:1, born from an accepted wave (or auto-created between connections [v2 follow-ups]). Immutable `event_id` origin.
2. On creation, wingman posts a **system-styled block visible to both**: shared context + 2–3 icebreakers (both see the same ones; transparency beats pretending).
3. Message rules: text ≤ 2,000 chars; images [v1.5]; no messages to/from blocked users (server rejects, client hides thread).
4. Wingman panel (sender-side only, private):
   - `Draft for me` — generates a message from conversation context + user's goal.
   - `Rewrite` — user's draft + target tone (`professional`, `casual`, `warm`, `brief`). ("Flirt" is not a tone. Professional app.)
   - `Suggest replies` — 3 short options from last 10 messages.
   - All outputs are editable text inserted into the input box; **never auto-sent**.
5. `ai_assisted` flag stored per message (analytics only; never shown to counterpart).
6. Meet planner: either side taps `Meet up` → picker of organizer-defined meeting points + time slots (next 15-min boundaries) → other side accepts/proposes-new → both get calendar-style reminder push 10 min before.
7. Tap-to-exchange: user A shows personal QR (rotating token), B scans → both prompted "Confirm you met {name}?" → both confirm → `connections` rows (mutual) with `met_confirmed_at`, contact details exchanged per each user's share settings (email/phone/links toggles), organizer meeting counter +1.
8. Read receipts: single check = delivered, double = read (per-conversation mute of receipts not offered — keep simple).

Analytics: `chat.message_sent` (with `ai_assisted`), `wingman.draft_used`, `wingman.rewrite_used`, `meet.proposed`, `meet.confirmed`, `exchange.completed`.

## 9. Radar [v1.5]

### Layer 1 — event-wide list
1. `GET /v1/events/{id}/radar` returns discoverable (`visibility='radar'`) checked-in users. Requires caller `visibility='radar'` (reciprocity). Order: `right_here` bucket first (if Layer 2 data), then recent check-in desc.
2. Each row: photo (required for radar), display name, headline, `Say hi` button (creates wave, source=`radar`).

### Layer 2 — "right here" (BLE)
3. Opening the radar screen: client requests a broadcast token (`POST /v1/events/{id}/radar/token`), advertises it via BLE, scans for peer tokens, and every 10s posts heard `{token, rssi}` pairs to `POST /v1/events/{id}/radar/sightings`.
4. Server resolves tokens → users, filters to mutually-discoverable non-blocked pairs, maps RSSI to buckets server-side: `right_here` (RSSI ≥ −65 dBm, tune at pilot) / `in_the_area` (heard at all). Response updates list ordering + bucket chips. Client NEVER receives RSSI values.
5. Tokens: random 8-byte IDs, TTL 5 min, one active per user/event; server keeps mapping in Redis (`radar_tokens`). New token auto-issued on expiry while screen open.
6. Broadcasting stops ≤ 30s after radar screen closes/backgrounds. Presence in Layer 1 list is unaffected.
7. Ghost mode: one tap on radar screen → `visibility` drops to `directory` for this event (leaves radar list AND stops broadcast AND removes browse access — same reciprocity rule).
8. Permission UX: Bluetooth permission requested only on first radar open, with a plain-language explainer sheet. Denial → Layer 1 list still works, banner explains what "right here" would add.

Analytics: `radar.opened`, `radar.ble_active`, `radar.wave_sent`, `radar.ghosted`.

## 10. Contacts CRM & post-event [v1 basics, v1.5 summary, v2 nurturing]

1. [v1] Chat list auto-groups by event (current event pinned during event days). Contact card shows: event met, meeting confirmed?, notes (private free text), shared links.
2. [v1.5] Morning-after job (09:00 local, day after `ends_at`): push + in-app summary — people connected, meetings confirmed, drafts of follow-up messages (approve-to-send each).
3. [v2] Follow-up reminders (no reply in 7 days after event); cross-event history ("crossed paths 3 times"); city-graph features (pre-event same-city list, post-event same-city meetup suggestion, travel mode — PRD v2, user stories US-605..607).

## 11. Organizer dashboard [v1]

1. Live view: check-in count (WS-updated), check-in rate sparkline, session counts [v1.5].
2. Announcements: compose (≤ 300 chars) → push + in-app banner to all checked-in attendees. Rate limit 1 per 10 min (anti-spam), staff role required.
3. Attendee management: application approve/reject (for `apply` events), search, export CSV (name, company, headline — never contact details without attendee opt-in).
4. [v1.5] ROI report: waves sent/accepted, conversations started, meetings confirmed, top industries/roles present. Aggregates only; never per-attendee decline data.
5. [v1.5] Exhibitor mode: booth entity + booth QR; attendee scans → tap-to-exchange flow with booth (consent screen shows exactly what's shared); exhibitor lead list export.

## 12. Office Hours [v2]

1. Organizer marks users as `vip_approved` for their event. VIP creates slot blocks: duration 15 min fixed, price (min ₦2,000 / $2; max ₦200,000 / $200) or `charity=true` (payout to organizer-chosen charity), quantity, time range, meeting point.
2. Attendee books → Paystack/Stripe payment held → booking `status='booked'`. Both get reminders. Tap-to-exchange at the slot confirms → `completed` → payout minus 20% platform fee (charity: 10%).
3. No tap-to-exchange within slot + 30 min → attendee prompted "did it happen?"; disputes go to manual review queue; VIP no-show → automatic refund.
4. Cancellation: attendee ≥ 2h before → full refund; VIP cancels → full refund + VIP reliability counter −1 (3 strikes → delisted for event).
5. Hard rule: Office Hours listings appear ONLY in the "Office Hours" tab. Never in match feed, directory ranking, or radar.

## 13. Premium (attendee) [v2]

Free forever: directory browse, match feed, 5 waves/hour, chat + basic wingman.
Premium (monthly or event-pass): advanced directory filters (role/industry/stage/goal), unlimited waves, AI meeting briefs, who-viewed-me, post-event contact export. **Never**: ranking boosts, wave queue priority, visibility advantages.

## 14. Trust & safety [v1]

1. Block: from any profile/chat/card. Effects: both removed from each other's directory/radar/feed/chat; existing conversation hidden both sides; permanent; cross-event; no notification to blocked party.
2. Report: reasons enum (`harassment`, `spam`, `impersonation`, `inappropriate_content`, `other`+text). Auto-attaches last 20 messages if from chat. Moderation queue in an internal admin view; actions: warn, suspend event access, ban.
3. Auto-flags: > 10 `not_now` in one event → wave sending paused for event + review; safety-screen fails ≥ 3 → same.
4. Data rights: `GET /v1/me/export` (async job → email link), `DELETE /v1/me` (soft → 30-day hard).
