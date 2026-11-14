# 10 — Build Plan & Test Strategy

Milestones are sequential; each has a **Definition of Done (DoD)** — all items checkable, no "mostly done". Solo-builder pacing ≈ 12–14 weeks to pilot; parallelize if more hands.

## v0 — Lean pilot build (≈ 6 weeks solo) — use this before M0–M8

Purpose: prove the core loop at one real event before building the full plan. Same stack and architecture as the full spec, smaller scope. Attendee client is the PWA (00 §3a).

| Week | Scope | Done when |
|---|---|---|
| 1 | Monorepo, FastAPI skeleton, Postgres+pgvector, Redis, ARQ, CI; Next.js app with attendee (PWA) + organizer route groups; `LLMProvider` + `PaymentProvider` + `OtpSender` interfaces; Langfuse wired | `docker compose up` runs the stack; a test AI call shows up as a trace |
| 2 | OTP auth (Termii + Turnstile + fraud caps), profile, events CRUD, rotating door QR, check-in, organizer live counter | Sign up and check in on a real phone in < 90 s |
| 3 | Event profiles, goals + `goal_parser`, embeddings, **contact exchange (QR) with AI note + next-morning follow-up draft** | Two phones exchange contacts; follow-up draft appears next morning |
| 4 | Matching feed + `match_explainer` (pre-computed), waves with intro card + silent decline, block/report | Invariant tests: silent decline, blocks absolute, first contact structured |
| 5 | Chat over WS (ticket auth) + **wingman** (`icebreakers`, `chat_assist` streaming), web push + in-app inbox, one sponsor tile | Chat works with AI off; wingman evals pass in CI |
| 6 | Load test (k6), security invariants incl. tenant/organizer/sponsor scope, AI dashboards + alerts + kill switches, runbooks, dry run with 20 people | All `tests/invariants/*` green; dry run done; go/no-go for pilot |

Deferred to after the pilot: BLE radar and the Expo app, session QRs, ROI report, exhibitor booths, Office Hours, premium, ticketing.

## M0 — Foundations (week 1)
Monorepo scaffold (pnpm workspaces + uv); FastAPI skeleton with module layout, health route, error envelope middleware, request-id logging; Alembic + initial migration (users, auth, devices); docker-compose dev stack; CI green (lint+type+test all packages); Expo app boots with dev client (BLE lib linked from day 1); Next.js dashboard boots; orval codegen pipeline works.
**DoD:** `docker compose up` + `pnpm dev` gives a running stack; a change to a FastAPI schema fails CI until TS client regenerated.

## M1 — Auth & profile (week 2)
OTP request/verify (Twilio + Resend), JWT + rotating refresh + family revocation, /me CRUD, photo presign→commit→variants→moderation stub (screen returns allow until 06 wired), devices.
**DoD:** signup on a real phone in < 90 s; refresh-token reuse revokes family (test); photo appears after "approval".

## M2 — Events & check-in (weeks 3–4)
Organizer org + events CRUD + publish; door QR TOTP + door-screen page; apply/approve; check-in endpoint + idempotency; event room bootstrap; announcements + push pipeline (Expo sender worker); dashboard: create event, applications, live counter (WS).
**DoD:** end-to-end on two phones: create event on dashboard → publish → apply → approve → scan rotating QR from laptop screen → checked in → receive announcement push.

## M3 — Event profiles, goals, AI parse (week 5)
Event card sheet + visibility enum enforcement; goals CRUD; `ai` module: client, registry, `goal_parser` (structured outputs), `safety_screen` (live); Voyage embeddings worker; seed script with 200 fake attendees.
**DoD:** free-text goal → parsed form → saved → embedded (visible in DB); malicious note blocked by screen; seeded event queryable.

## M4 — Matching engine (weeks 6–7)
Stages 1–5 per 05; match_scores upsert; feed endpoint; skip; `match_explainer` (live + batch paths) with groundedness validator; recompute jobs; feedback logging.
**DoD:** on seeded event, Victor/Sara worked example (05 §10) reproduces score 0.83 ± tolerance; feed returns in < 300 ms from cache; explanations cite only real signals (validator test); one-sided VC pair ranks below mutual pairs.

## M5 — Waves (week 8)
Wave create with card build + note screen; inbox/sent (sender-state masking!); respond actions; mutual detection; resurface + expiry jobs; rate limits; pushes.
**DoD:** invariant tests pass: silent decline byte-identical sender view; 6th wave in hour → 429; maybe_later resurfaces exactly once at 09:00 (time-warp test); mutual wave auto-connects.

## M6 — Chat & wingman (weeks 9–10)
WS gateway + Redis fan-out; conversations/messages + read receipts; icebreakers on create; `chat_assist` streaming; meet planner; tap-to-exchange (QR token, dual confirm, connections + consent-based contact share).
**DoD:** two phones chat in real time through 2 API instances; kill AI key → chat still works, wingman shows graceful error; tap-to-exchange creates mutual connection and organizer meeting counter increments.

## M7 — Safety, polish, ops (week 11)
Blocks (joined into every surface — run invariant suite), reports + internal moderation view, data export/delete, retention jobs, notification preferences + quiet hours, Sentry, metrics, mission-control dashboard, runbooks, load test (k6: check-in burst 20 rps, chat 50 msg/s, radar 40 rps sustained 10 min, p95 < 500 ms).
**DoD:** all `tests/invariants/*` green in CI; load test passes on staging; restore drill done.

## M8 — Pilot event (weeks 12–13)
Dry run with 20 friends at a meetup; fix; then pilot event live with on-site presence.
**DoD (pilot metrics from PRD §8):** ≥ 70% checkin→profile, ≥ 40% send a wave, ≥ 35% accept rate, ≥ 30% accepted→meeting, organizer says yes to paying next time. Post-mortem doc written; v1.5 backlog (radar BLE, session boost, ROI report, exhibitor capture, morning-after) re-prioritized from real data.

## v1.5 (post-pilot, ~4 weeks)
Radar Layers 1+2 (01 §9, BLE spike first: 2-day feasibility test on 4 device models), session QRs + boost, ROI report, exhibitor booths, morning-after summaries, in-app notification center.

## Test strategy

| Layer | Tooling | Gate |
|---|---|---|
| Unit (services, scoring math) | pytest, hypothesis for scoring properties (symmetry, clamps, geometric-mean monotonicity) | CI |
| API integration | pytest + httpx against test DB (transactional fixtures) | CI |
| **Invariant suite** | dedicated `tests/invariants/` per 08 §4 | CI, blocking |
| Contract | OpenAPI snapshot + orval drift check | CI |
| E2E | Playwright (PWA) flows: signup, checkin, wave, chat, contact exchange; Maestro once the Expo app exists (v1.5) | pre-release |
| Load | k6 scripts in repo | pre-event |
| AI evals | golden sets per 06 §7 (goal parse, groundedness, safety, wingman, red-team); run on any prompt, model or provider change | CI (blocking on regression) |

## Standing risks while building

| Risk | Watch/mitigate |
|---|---|
| BLE flakiness across Android OEMs | v1.5 spike before committing UI; Layer 1 is the fallback story |
| OTP delivery in NG | test Twilio NG routes in M1, keep Termii as backup provider abstraction |
| AI latency spikes on event day | all sync AI calls have timeout + fallback; pre-generate explanations |
| Scope creep | anything not in this spec goes to `DECISIONS-NEEDED.md`, not into code |
