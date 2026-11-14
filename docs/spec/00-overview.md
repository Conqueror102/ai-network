# 00 — System Overview & Conventions

**Status:** Build-ready specification v1.0 · 2026-07-14
**Rule for readers (human or AI):** this spec is prescriptive. Where it states a decision, build it exactly that way. Do not introduce alternatives. If something is genuinely unspecified, follow the conventions in this file, then flag it in `docs/spec/DECISIONS-NEEDED.md`.

## 1. What we are building

AiNetwork is an event-networking platform with three deliverables:

1. **Attendee app** — v0/v1: installable web app (PWA, Next.js + TypeScript) opened from the check-in QR. From v1.5 (BLE radar): React Native (Expo, TypeScript), iOS + Android from one codebase. See §3a.
2. **Organizer web dashboard** — Next.js (TypeScript).
3. **Backend platform** — FastAPI (Python 3.12) monolith + background workers, PostgreSQL, Redis.

Core loop: attendee checks into an event via QR → declares goals → engine computes two-way matches → AI drafts intro cards → double-opt-in intros → AI-assisted chat → physical meeting confirmed by tap-to-exchange → post-event CRM and follow-ups. Organizers get check-in ops, announcements, and connection-ROI analytics.

## 2. Document map (read in this order)

| Doc | Contents |
|---|---|
| `00-overview.md` | This file: conventions, fixed stack, glossary |
| `01-product-spec.md` | Every feature's exact behavior: rules, states, edge cases, analytics |
| `02-domain-model.md` | Full database schema: tables, columns, constraints, indexes |
| `03-api-spec.md` | Every HTTP endpoint: auth, request/response shapes, errors, rate limits |
| `04-flows.md` | Sequence flows for every user journey |
| `05-matching-engine.md` | Matching algorithm: formulas, weights, jobs, feedback loop, worked example |
| `06-ai-layer.md` | Every AI call: prompt contract, model config, schemas, fallbacks, cost control |
| `07-realtime.md` | WebSocket protocol, push notification catalogue, delivery semantics |
| `08-security-privacy.md` | Auth design, authorization matrix, threat model, retention, invariants |
| `09-infrastructure-scaling.md` | Deploy, environments, CI, observability, capacity math, scaling stages |
| `10-build-plan.md` | Milestones with definitions of done, test strategy |

The older `docs/*.md` (PRD, user-stories, architecture, tech-stack) remain as context/rationale; **on any conflict, `docs/spec/` wins.**

## 3. Fixed technology decisions

These are final. Each row lists what was rejected so nobody re-litigates.

| Decision | Choice | Rejected & why |
|---|---|---|
| Backend | FastAPI, Python 3.12, single modular monolith | NestJS (splits AI work into a second service); microservices (operational overhead for a 1–3 person team) |
| ORM / migrations | SQLAlchemy 2.x (async) + Alembic | Raw SQL everywhere (no type safety); Django (sync-first, heavier) |
| DB | PostgreSQL 16 + pgvector extension | Separate vector DB (Pinecone/Qdrant — extra system to operate); MongoDB (relational data, joins everywhere) |
| Cache/queues/presence | Redis 7 (managed) | In-process caches (multi-instance WS needs shared pub/sub) |
| Background jobs | ARQ (async, Redis-backed) | Celery (sync-first, heavier config) |
| Attendee app (v0/v1) | **PWA** in Next.js (App Router, TypeScript), Tailwind + shadcn/ui, browser camera API for QR | Native app at pilot (install friction at the venue door; BLE is not needed until v1.5) |
| Attendee app (v1.5+) | Expo SDK (latest stable) + React Native, TypeScript, `expo-router`; EAS Build with custom dev client (BLE requires it) | Native Swift/Kotlin (two codebases); Flutter (team knows RN); Expo Go (no BLE support) |
| BLE | `react-native-ble-plx` | Nearby/UWB APIs (fragmented, unnecessary precision) |
| Dashboard | Next.js (App Router), TypeScript, deployed on Vercel | Embedding dashboard in mobile app (organizers work on laptops) |
| API style | REST + WebSocket, versioned under `/v1` | GraphQL (adds complexity; OpenAPI codegen gives us typed clients anyway) |
| Client typing | OpenAPI schema → generated TS client (`orval`) in `packages/shared-types` | Hand-written API clients (drift) |
| Auth | Email/phone OTP → JWT access (15 min) + rotating refresh (30 days) | Third-party auth SaaS (cost, lock-in; revisit if OTP delivery becomes painful) |
| LLM | **Provider-agnostic** `LLMProvider` interface (06 §1a). Default provider Claude, routed per task: small model for `safety_screen` / `match_explainer`, mid model for `goal_parser` / `chat_assist` / `icebreakers`; top model only where evals show the mid model falls short. Exact model IDs pinned in config | One model for every task (cost and latency on event day); hard-coding one vendor's SDK across the code (lock-in); LangChain (heavy abstraction; the thin interface is enough) |
| Embeddings | Voyage AI `voyage-3.5`, 1024 dims, cosine distance | OpenAI embeddings (no strong reason; Voyage pairs well with Claude stack) |
| Push | v0/v1: **Web Push** (VAPID) from the PWA, with in-app inbox and SMS/WhatsApp fallback for critical events (iOS web push needs home-screen install). v1.5+: Expo Push | Raw FCM/APNs (Expo wraps both) |
| Payments | **`PaymentProvider` adapter** (create checkout, verify webhook, refund, payout). First implementation: **Bachs** (bachs.io: hosted checkout for cards, bank transfer, mobile money and stablecoins; subscriptions + usage billing + dunning; NGN/GHS/KES/ZAR settlement; Python SDK + signed webhooks), used first for organizer SaaS subscriptions. Paystack (subaccounts/splits) is the planned second adapter for marketplace flows that need split payouts (Office Hours, ticketing, sponsor revenue share) unless Bachs confirms split support. Pilot billing: manual invoices | Calling one provider's SDK directly from business logic (switching cost) |
| Object storage | Cloudflare R2 (S3-compatible) + CDN | — |
| Hosting | API, ARQ worker and cron: **Render** (Frankfurt region, paid instances on event days); web apps: **Vercel**; DNS/WAF/R2: **Cloudflare**; DB: Neon; Redis: Upstash. Keep API, DB and Redis in the same EU region | Kubernetes (massively premature); Cloudflare Workers for the API (poor fit for long-lived WebSockets and Python background workers); Render free tier (sleeps) |
| OTP / messaging | **Termii** primary for NG SMS + WhatsApp OTP, Twilio Verify as backup behind one `OtpSender` interface; Resend for email; **Cloudflare Turnstile** on OTP request | Single SMS provider (NG delivery risk) |
| AI observability | **Langfuse** (traces, prompt versions, evals, cost) + own `ai_calls` table | Building tracing UI ourselves; LangSmith (tied to LangChain) |
| E2E tests | Playwright (PWA) ; Maestro from v1.5 (native) | — |
| Error tracking | Sentry (API, mobile, dashboard) | — |

## 3a. Revision 2026-11-14 (v0 decisions)

Agreed in the 2026-11-14 brainstorm with Victor; supersedes earlier rows above where they differ:
- Attendee client is a PWA until BLE radar (v1.5). Expo-specific items elsewhere in the spec (EAS, Expo Push, `react-native-ble-plx`) apply from v1.5.
- The AI layer is provider-agnostic (06 §1a); Claude is the default provider, not a hard dependency.
- Payments, OTP and push sit behind swappable adapter interfaces.
- The wingman (`chat_assist`, `icebreakers`) is **in v0 scope**.
- A lean v0 plan (10 §v0) precedes the full M0–M8 plan.

## 4. Global conventions (apply everywhere)

### Identifiers
- All primary keys are **ULIDs** stored as `TEXT` (26 chars, sortable by time). Generated server-side (`python-ulid`). Prefixed for debuggability: `usr_`, `evt_`, `epf_`, `gol_`, `wav_`, `cnv_`, `msg_`, `con_`, `blk_`, `zon_`, `chk_`, `tok_`, `ohs_`, `bkg_`, `rpt_`, `ann_`, `org_`.

### Time & money
- All timestamps: `TIMESTAMPTZ`, stored UTC, serialized ISO-8601 with `Z`.
- Money: integer minor units (`kobo`, `cents`) + ISO currency code. Never floats.

### JSON API conventions
- `snake_case` keys everywhere.
- Every list endpoint: cursor pagination — `?cursor=<opaque>&limit=<1..100, default 25>`; response `{"items": [...], "next_cursor": "..." | null}`.
- Error envelope (always):
```json
{"error": {"code": "wave_limit_reached", "message": "Human-readable explanation", "details": {}}}
```
- Error codes are stable strings (kebab-free snake_case), enumerated per endpoint in `03-api-spec.md`.
- Idempotency: all POST endpoints that create money- or message-side-effects accept an `Idempotency-Key` header (stored 24h in Redis; replay returns the original response).

### Code conventions
- Backend modules live in `apps/api/app/modules/<name>/` with `router.py`, `service.py`, `models.py`, `schemas.py`, `jobs.py` (if any). Routers contain no business logic; services contain no HTTP concerns.
- Every DB access goes through the module's service. Cross-module calls go service→service, never router→foreign service.
- All AI calls go through `modules/ai` — no other module imports any LLM or embedding SDK.
- Feature flags: simple `settings.flags` dict from env; no flag SaaS.

### Non-negotiable product invariants (enforced in code review; tests required)
1. **Double opt-in:** no free-text reaches a user from someone they haven't accepted. First contact is always a server-constructed card.
2. **Silent declines:** `not_now` produces zero observable signal to the sender (no status change, no timing signal).
3. **No precise location:** no endpoint returns distance, direction, coordinates, or raw signal strength. Proximity is only `right_here` / `in_the_area` bucket labels between mutually discoverable users.
4. **Money never touches ranking:** premium status and Office Hours cannot influence match scores, feed order, or wave queues.
5. **Blocks are absolute:** every people-returning query joins against `blocks` in both directions; blocks are permanent and cross-event.
6. **AI drafts, humans send:** no AI-generated content is delivered to a counterpart without an explicit user action.
7. **Grounded explanations:** AI match explanations may cite only signals present in the provided match-components payload.

## 5. Glossary

| Term | Meaning |
|---|---|
| **Event profile** | A user's identity *within one event* (display name/photo, headline, offer). Users have one per event. |
| **Goal** | Structured per-event object: what the user wants (intent + target + offer + priority). |
| **Wave** | Any first-contact attempt (from match feed or radar). Carries an intro card. One per (sender, recipient, event). |
| **Intro card** | Server-constructed payload: sender's card + "why you two" + optional AI-screened one-liner. The only form of first contact. |
| **Match feed** | Ranked top-10 (plus wildcards) of two-way-scored candidates, refreshed per schedule. |
| **Radar** | Discovery surface: Layer 1 = event-wide discoverable list; Layer 2 = BLE "right here" proximity buckets. |
| **Discoverable** | `event_profiles.visibility = 'radar'` — in radar list, photo required. `'directory'` — in directory/matching only. `'hidden'` — matched-only... see 01 §8. |
| **Tap-to-exchange** | Both phones confirm a physical meeting (QR shown by one, scanned by other). Creates mutual `connections` with `met_confirmed_at`. |
| **Connection** | Mutual relationship record; unlocks post-event visibility (home area, follow-ups). |
| **Wingman** | The AI assistant surface inside chat: icebreakers, drafts, tone rewrites, reply suggestions, meeting briefs. |
| **Office Hours** | v2: paid bookable slots offered by organizer-approved VIPs. Separate surface from matching. |
| **Zone / session QR** | Organizer analytics only (session attendance). Never part of radar. |
