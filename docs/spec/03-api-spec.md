# 03 — API Specification

Base URL: `https://api.<domain>/v1`. Auth: `Authorization: Bearer <access_jwt>` unless marked *(public)*. Content type `application/json`. Errors use the envelope from 00 §4; per-endpoint error codes listed as `→ code`. Cursor pagination per 00 §4. The FastAPI app auto-publishes OpenAPI at `/openapi.json`; the generated TS client in `packages/shared-types` is the only client allowed in mobile/dashboard code.

## 1. Auth

| Method & path | Body → Response | Errors |
|---|---|---|
| `POST /auth/otp/request` *(public)* | `{channel: "phone"\|"email", destination}` → `{request_id, resend_after_s: 60}` | `invalid_destination`, `otp_rate_limited` |
| `POST /auth/otp/verify` *(public)* | `{request_id, code}` → `{access_token, refresh_token, user: User, is_new: bool}` | `otp_invalid`, `otp_expired`, `otp_attempts_exceeded` |
| `POST /auth/refresh` *(public)* | `{refresh_token}` → `{access_token, refresh_token}` (rotates) | `refresh_invalid`, `refresh_reused` (revokes family) |
| `POST /auth/logout` | `{refresh_token}` → `204` | — |

JWT claims: `sub` (user id), `exp`, `iat`, `premium` (bool), `jti`. Signed HS256 with `JWT_SECRET` (rotatable via `kid` header).

## 2. Me & profile

| Endpoint | Notes |
|---|---|
| `GET /me` → `User` | Full own profile incl. private fields |
| `PATCH /me` | Partial update of profile fields (01 §2). → `validation_error` |
| `POST /me/photo/presign` → `{upload_url, key}` | R2 presigned PUT (max 8 MB, jpeg/png/webp) |
| `POST /me/photo/commit` `{key}` | Triggers variant generation + moderation screen; `photo_status='pending'` |
| `POST /me/devices` `{expo_push_token, platform}` | Upsert device |
| `GET /me/export` → `{job_id}` | Async data export (email link when ready) |
| `DELETE /me` → `204` | Soft delete |

## 3. Events

| Endpoint | Notes |
|---|---|
| `GET /events?city=&q=&cursor=` *(public)* | Published public events; registered ones pinned |
| `GET /events/{id}` | Detail; `address` only if registered/approved |
| `POST /events/{id}/apply` → `{status}` | `open` events: instant `approved` |
| `POST /events/{id}/checkin` `{qr_token}` → `{checked_in: true, event_room_unlocked: true}` | → `qr_invalid`, `qr_stale`, `checkin_not_approved`, `event_not_live` |
| `POST /events/{id}/session-checkin` `{qr_token}` → `204` | Zone/session scan (analytics) |
| `GET /events/{id}/room` | Aggregate bootstrap: my event_profile, counts, my feed freshness, meeting points |
| `GET /events/{id}/announcements?cursor=` | In-app announcement history |

## 4. Event profile & goals

| Endpoint | Notes |
|---|---|
| `PUT /events/{id}/profile` | Create/update my event card `{display_name, display_photo_url?, headline?, offer_text?, visibility}` → `radar_requires_photo` if `visibility='radar'` without approved photo |
| `GET /events/{id}/profiles/{user_id}` | Public view of someone's event card. → `not_visible` if hidden/blocked |
| `GET /events/{id}/directory?q=&cursor=` | Browsable list (reciprocity: my visibility ≥ directory). Premium-only params [v2]: `role=`, `industry=`, `stage=`, `intent=` → `premium_required` |
| `POST /events/{id}/goals/parse` `{text}` → `{goal: GoalDraft}` | AI parse; does NOT save |
| `POST /events/{id}/goals` `{intent, target, offer, priority}` → `Goal` | Validates, embeds async |
| `PATCH /goals/{id}` / `DELETE /goals/{id}` | Edit/archive; triggers re-match |

## 5. Matching

| Endpoint | Notes |
|---|---|
| `GET /events/{id}/matches` → `{items: MatchCard[], computed_at}` | `MatchCard = {user_id, display_name, photo_url, headline, why: string, matched_chips: string[], wildcard: bool, score_bucket: "high"\|"medium"}` — raw scores never exposed |
| `POST /events/{id}/matches/{user_id}/skip` → `204` | Hides + logs `feed_skip` feedback |

## 6. Waves

| Endpoint | Notes |
|---|---|
| `POST /events/{id}/waves` `{to_user, source, note?}` → `Wave` | Server builds card. → `wave_already_exists`, `wave_limit_reached` (429), `note_rejected` (safety screen), `recipient_unavailable` (hidden/blocked — same error for both, indistinguishable by design) |
| `GET /events/{id}/waves/inbox?cursor=` | My received pending/maybe_later waves (cards) |
| `GET /events/{id}/waves/sent?cursor=` | My sent waves — status shown as only `pending` or `accepted` (all other states render as `pending`) |
| `POST /waves/{id}/respond` `{action: "accept"\|"not_now"\|"maybe_later"}` → accept: `{conversation_id}`; else `204` | → `wave_not_pending` |

## 7. Chat

| Endpoint | Notes |
|---|---|
| `GET /conversations?cursor=` | Grouped client-side by `event_id`; includes peer card, last message, unread count |
| `GET /conversations/{id}/messages?cursor=` | Newest-first pages |
| `POST /conversations/{id}/messages` `{body, ai_assisted?, idempotency via header}` → `Message` | Also fanned out via WS. → `conversation_blocked` |
| `POST /conversations/{id}/read` `{last_message_id}` → `204` | Read receipts |
| `POST /conversations/{id}/meet` `{meeting_point, at}` → meet_proposal message | Counterpart accepts via same endpoint `{accept_message_id}` |
| `GET /events/{id}/meet-spots?at=` | Numbered meeting spots (`M3 · Coffee stand`, optional hint) with a coarse `busy` level around `at` and one `suggested` (the quietest). Propose with `{spot_id, at, spot_me?}`; accept with `{accept_message_id, spot_me?}` |
| `POST /conversations/{id}/meet/{message_id}/status` `{spot_me?, arrived?}` | "How to spot me" (80 chars, only the two people see it, erased a day after the meeting) and "I'm here" (confirmed meetings, from 30 min before to 1 h after; pushes the other person once) |
| `POST /conversations/{id}/meet/{message_id}/sharing` `{on}`; `POST\|GET .../position` `{lat, lng, accuracy_m}` | Two-way location sharing for one confirmed meet-up. Both must turn it on; positions accepted from 30 min before to 15 min after, and it ends when both tap "I'm here". Returns the other person's distance (10 m steps) and compass direction, never coordinates. Positions live only in Redis (5 min TTL) |
| `GET/POST /events/{id}/meeting-spots`, `PATCH .../{spot_id}` (organizer) | Manage numbered spots. Numbers are never reused; a removed spot is switched off |
| `POST /ai/assist` `{conversation_id, action: "draft"\|"rewrite"\|"suggest_replies", text?, tone?}` → `{options: string[]}` | Rate limit 30/h free. → `ai_unavailable` (degrade gracefully) |
| `POST /ai/brief` `{event_id, user_id}` → `{brief}` [v2 premium] | Meeting prep brief |

## 8. Radar [v1.5]

| Endpoint | Notes |
|---|---|
| `GET /events/{id}/radar?cursor=` | Layer-1 list; requires my `visibility='radar'` → `radar_requires_visibility`. Items carry `bucket: "right_here"\|"in_the_area"\|null` |
| `POST /events/{id}/radar/token` → `{token, ttl_s: 300}` | BLE broadcast token |
| `POST /events/{id}/radar/sightings` `{sightings: [{token, rssi}]}` → `{buckets: {user_id: bucket}}` | Server resolves + buckets; max 1 req / 10 s |
| `POST /events/{id}/radar/ghost` → `204` | Sets visibility to `directory` |

## 9. Connections & safety

| Endpoint | Notes |
|---|---|
| `POST /exchange/token` → `{qr_payload, ttl_s: 60}` | My tap-to-exchange QR |
| `POST /exchange/scan` `{qr_payload, event_id}` → `{peer_card, confirm_id}` | Then both call: |
| `POST /exchange/{confirm_id}/confirm` → `{connection}` | Creates mutual connections + `met_confirmed_at` |
| `GET /connections?event_id=&cursor=` | My CRM list |
| `PATCH /connections/{id}` `{notes}` | Private notes |
| `POST /blocks` `{user_id}` → `204` / `DELETE` not offered (permanent) | |
| `POST /reports` `{subject_id, reason, detail?, conversation_id?}` → `204` | |

## 10. Organizer (role-gated: organizer_members of the event's org)

| Endpoint | Notes |
|---|---|
| `POST /organizers` / `POST /organizers/{id}/members` | Org management |
| `POST /organizers/{id}/events` / `PATCH /events/{id}` | CRUD; publish sets `status='published'` |
| `GET /events/{id}/door-screen` *(public page token)* | Rotating QR page (dashboard renders) |
| `GET /events/{id}/applications?status=&cursor=` / `POST /applications/{id}/decide` `{approve: bool}` | |
| `GET /events/{id}/stats/live` | `{checked_in, capacity, checkins_last_hour: [..]}` (also via WS topic) |
| `POST /events/{id}/announcements` `{body}` → `Announcement` | Push fan-out. → `announcement_rate_limited` |
| `GET /events/{id}/stats/report` [v1.5] | ROI aggregates (waves, accepts, conversations, meetings, industry mix) |
| `GET /events/{id}/attendees/export` | CSV; respects consent flags |

## 11. Office Hours [v2] — summarized

`POST /events/{id}/vips` (organizer), `POST /events/{id}/office-hours` (VIP creates slots), `GET /events/{id}/office-hours`, `POST /office-hours/{slot_id}/book` (payment init → provider redirect/webhook), `POST /bookings/{id}/dispute`. Payment webhooks: `POST /webhooks/paystack`, `POST /webhooks/stripe` (signature-verified, idempotent).

## 12. Rate limits (Redis token buckets, per user unless noted)

| Scope | Limit |
|---|---|
| OTP request | 3 / 10 min per destination; 10 / day |
| Waves | 5 / rolling hour / event (premium unlimited) |
| `POST /ai/assist` | 30 / h free, 120 / h premium |
| Messages | 20 / min |
| Radar sightings | 6 / min |
| Announcements | 1 / 10 min per event |
| Global default | 120 req / min per user; 20 req / min per IP unauthenticated |

Rate-limited responses: HTTP 429, `{error: {code: "...", details: {retry_after_s}}}`.
