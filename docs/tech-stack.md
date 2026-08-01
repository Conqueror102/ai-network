# Tech Stack & Tooling — AiNetwork

Chosen around skills you already have (Python/FastAPI, JS/TS, Node/Express/Nest/Next, React Native/Expo) — zero new languages to learn for v1.

## 1. The stack

| Layer | Choice | Why this over the alternatives you know |
|---|---|---|
| **Mobile app** | React Native + **Expo** (TypeScript) | You know it; one codebase for iOS/Android; Expo gives push notifications, OTA updates (critical for fixing bugs *during* an event day), camera/QR scanning out of the box. |
| **Proximity (radar "right here" mode)** | `react-native-ble-plx` (BLE phone-to-phone) | No venue hardware: phones advertise rotating anonymous tokens and listen while the radar screen is open. Requires a **custom Expo dev-client build** (BLE isn't in Expo Go) — plan for this from the first EAS build. |
| **Backend API** | **FastAPI** (Python 3.12) | You know it; async-native for WebSockets; and the AI layer (Anthropic SDK, embeddings, pydantic structured outputs, future ML on match data) lives naturally in Python. Choosing Nest would split the AI work into a second service — not worth it at this stage. |
| **Organizer dashboard** | **Next.js** (TypeScript) | You know it; server components fine for dashboards; deploys free on Vercel; shares TS types with the mobile app via a small shared package. |
| **Database** | **PostgreSQL + pgvector** | One database for relational data AND embeddings — no separate vector DB to operate. Managed: Neon or Supabase (Supabase also gives you storage + auth helpers if wanted). |
| **Cache / realtime glue** | **Redis** (Upstash) | Presence TTLs, wave rate limits, WebSocket pub/sub across instances, job queues. |
| **Background jobs** | **ARQ** (or Celery) | Match batch runs, morning-after summaries, wave expiry sweeps, batch AI calls. ARQ is async-native and pairs cleanly with FastAPI. |
| **AI — language** | **Claude API**, model `claude-opus-4-8` | Intro drafting, why-you-two, icebreakers, tone rewrite, goal parsing (structured outputs), safety screening. Use the **Batches API** (50% off) for overnight/non-urgent generation. |
| **AI — embeddings** | **Voyage AI** (`voyage-3` family) | Anthropic doesn't ship embeddings; Voyage is the standard pairing. Stored in pgvector. |
| **Auth** | Phone/email OTP via **Twilio Verify** / **Resend** + JWT (or Clerk if you'd rather buy it) | Verified-human requirement; keep tokens short-lived, refresh flow in app. |
| **Push** | **Expo Push Notifications** | Free, built into Expo. |
| **Payments** | **Paystack** (NG/Africa) + **Stripe** (international) | v2 ticketing + organizer billing; v1 organizer billing can be manual invoices. |
| **Storage** | S3-compatible (Supabase Storage / Cloudflare R2) + CDN | Profile photos. |
| **Hosting** | API: Railway / Fly.io / Render · Dashboard: Vercel · Mobile: EAS Build → App Store / Play | Cheap, fast to ship, region near first event. |
| **Errors/observability** | Sentry (API + app) + structured JSON logs | Event day is a live-fire exercise; you need to see failures in real time. |

## 2. Repository layout (monorepo)

```
ainetwork/
├── apps/
│   ├── mobile/            # Expo app (TypeScript)
│   │   ├── app/           # expo-router screens
│   │   ├── src/{api,components,stores,hooks}/
│   │   └── app.json
│   ├── dashboard/         # Next.js organizer dashboard
│   └── api/               # FastAPI backend
│       ├── app/
│       │   ├── modules/
│       │   │   ├── auth/
│       │   │   ├── events/        # events, zones, check-in, gating
│       │   │   ├── profiles/      # event_profiles, goals
│       │   │   ├── matching/      # pipeline, scores, feed
│       │   │   ├── waves/         # intro cards, state machine
│       │   │   ├── chat/          # conversations, WS, wingman endpoints
│       │   │   ├── ai/            # Claude client, prompt registry, embeddings
│       │   │   ├── organizer/     # dashboard APIs, analytics, announcements
│       │   │   └── safety/        # blocks, reports, moderation
│       │   ├── core/              # config, db, redis, deps, middleware
│       │   └── workers/           # ARQ jobs
│       ├── migrations/            # alembic
│       └── tests/
├── packages/
│   └── shared-types/      # OpenAPI-generated TS client + shared enums
└── docs/                  # these documents
```

Type safety across the boundary: FastAPI auto-generates OpenAPI → generate the TS client (`openapi-typescript` / `orval`) into `packages/shared-types`, consumed by both mobile and dashboard. One source of truth for every payload.

## 3. Dev tooling

| Concern | Tool |
|---|---|
| Python | `uv` (env + deps), `ruff` (lint/format), `pytest`, `mypy` |
| TypeScript | `pnpm` workspaces, `biome` or eslint+prettier, `vitest` |
| DB migrations | Alembic |
| API testing | pytest + httpx; seeded fake-event script (200 fake attendees with goals) for matching-engine development |
| Mobile builds | EAS Build + EAS Update (OTA) |
| CI | GitHub Actions: lint, test, build, deploy on main |
| Secrets | Environment vars per platform; never in repo |

## 4. Cost sketch (v1, one event ≤ 1,000 attendees)

| Item | Est. monthly |
|---|---|
| Hosting (API + DB + Redis) | $20–60 |
| Claude API (drafts/explanations; batch where possible) | $30–150 per event* |
| Embeddings | < $5 |
| Twilio OTP | ~$0.05/verification |
| Sentry / Vercel / EAS | Free tiers |

*Rough: ~1,000 attendees × ~10 AI generations each × ~1K tokens ≈ 10M tokens → manageable; overnight batches at 50% off; prompt caching cuts input costs further. Measure at the pilot and tune (drop to lower effort for the safety screen, batch the explanations).

## 5. Build order (suggested 12-week path to first event)

| Weeks | Milestone |
|---|---|
| 1–2 | Monorepo scaffold, auth (OTP + JWT), profile CRUD, event CRUD + QR check-in |
| 3–4 | Goals (AI parsing w/ structured outputs), embeddings, directory, gating |
| 5–6 | Matching pipeline + feed + "why you two" |
| 7–8 | Wave state machine + intro cards + push notifications |
| 9–10 | Chat (WS) + wingman (icebreakers, tone, suggestions) + tap-to-exchange |
| 11 | Organizer dashboard (live attendance, announcements), safety (block/report), polish |
| 12 | Load test with seeded fake event, dry run, ship to pilot event |

Radar, session matching, ROI reports, exhibitor capture: immediately after the pilot (v1.5), informed by what the pilot teaches.
