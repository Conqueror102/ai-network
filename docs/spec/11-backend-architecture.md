# 11 — Backend Architecture & Engineering Standards

**Status:** Build-ready v1.0 · 2026-11-14
**Scope:** the FastAPI backend (`apps/api`): API, WebSocket gateway, background workers and scheduler. This doc is the "how we build it" companion to 02–09 (which say *what* to build). On a conflict about product behavior, 01–08 win; on a conflict about code structure, layering, tooling or engineering standards, this doc wins and supersedes the short "Code conventions" block in 00 §4.

Decisions this doc builds on (00 §3, §3a): Python 3.12, FastAPI modular monolith, SQLAlchemy 2 async + Alembic, Postgres 16 + pgvector on Neon, Redis on Upstash, ARQ, WebSockets + Redis pub/sub, Render (API/worker/cron) + Vercel (web) + Cloudflare (DNS/WAF/R2), provider-agnostic AI layer (no LangChain), Langfuse, swappable payment (Bachs first)/OTP/push adapters. Wingman, sponsor and ads modules are in scope.

---

## 1. Architecture principles

1. **Modular monolith, one deployable image.** One codebase, one Docker image, several process roles (`api`, `ws`, `worker`, `scheduler`). Modules have hard boundaries so any one of them could be extracted later, but nothing is extracted until load proves it must be (09 §6).
2. **Layered inside every module.** HTTP → service → repository → database. Each layer only calls the one below it. Business rules live only in services.
3. **Ports and adapters at every vendor edge.** Business code depends on an interface (`LLMProvider`, `PaymentProvider`, `OtpSender`, `PushSender`, `EmailSender`, `ObjectStorage`, `EmbeddingProvider`). Vendor SDKs are imported only inside their adapter.
4. **Postgres is the source of truth.** Redis holds only things we can lose or rebuild (cache, rate limits, presence, pub/sub, job queue). Any side effect that must not be lost goes through the transactional outbox (§7.3).
5. **Invariants in the schema and in tests, not in hope.** Constraints, unique indexes and CHECKs enforce data rules; `tests/invariants/` enforces product rules (00 §4, 08 §4/§6).
6. **Degrade, never fall over.** AI down → app works without AI. Redis down → REST-only mode. Push down → in-app inbox. Every external call has a timeout, a retry policy and a fallback (09 §7).
7. **Boring by default.** No new infrastructure without a written reason in `DECISIONS-NEEDED.md` (Kubernetes, Kafka, microservices, GraphQL stay non-goals).

---

## 2. Runtime topology

```
                     Cloudflare (DNS, TLS, WAF, rate-limit backstop, R2 + CDN)
                                         │
              ┌──────────────────────────┼───────────────────────────┐
              ▼                          ▼                           ▼
     Vercel: Next.js PWA         Render: api  (ROLE=api)      Render: ws (ROLE=ws)*
     + organizer dashboard       uvicorn, 2→4 instances        WebSocket gateway
                                         │                           │
                                         ▼                           ▼
                         ┌──────── Upstash Redis ───────────────────────┐
                         │ cache · rate limits · ARQ queues · pub/sub · │
                         │ presence · idempotency keys · WS tickets     │
                         └───────────────▲──────────────────────────────┘
                                         │
     Render: worker (ROLE=worker, ARQ)  ─┤      Render: scheduler (ROLE=scheduler, ARQ cron)
     queues: default, ai, notify        │
                                         ▼
                       Neon Postgres 16 + pgvector (PITR, Frankfurt)

  Outbound adapters: LLM providers (Anthropic default) · Voyage embeddings · Langfuse
                     Termii / Twilio (OTP) · Resend (email) · Web Push (VAPID)
                     Bachs payments (§9.4) · Sentry · Grafana Cloud
```

\* Stage 1 runs the WS endpoint inside the `api` role. The `ws` role is the same image with only the WS router mounted, switched on at stage 2 (09 §6). All roles share code; `ROLE` only decides what the entrypoint starts.

| Role | Entrypoint | What it runs |
|---|---|---|
| `api` | `app.entrypoints.api:app` | REST routers + (stage 1) WS router |
| `ws` | `app.entrypoints.ws:app` | WS router only |
| `worker` | `app.entrypoints.worker.WorkerSettings` | ARQ functions from every module's `jobs.py`; outbox relay |
| `scheduler` | `app.entrypoints.scheduler.SchedulerSettings` | ARQ cron jobs only (they enqueue work; they never do heavy work themselves) |

Migrations run as Render's pre-deploy command (`alembic upgrade head`), never from app startup.

---

## 3. Layers inside a module

```
   HTTP / WS / job / webhook        ← transport: parse, authenticate, authorize, call one service method
            │
        service.py                  ← use cases: business rules, transactions, emits domain events
            │
      repository.py                 ← all SQL for this module's tables; returns ORM models or DTOs
            │
        models.py                   ← SQLAlchemy 2 typed ORM models (only this module's tables)
```

| File | Owns | Must not |
|---|---|---|
| `router.py` | FastAPI routes, request/response schemas, `Depends` for auth/authz, HTTP status codes | contain business logic, open transactions, touch repositories or another module's service |
| `schemas.py` | Pydantic v2 request/response DTOs (`extra="forbid"` on input) | import ORM models into responses directly (always map) |
| `service.py` | Use-case methods, invariants, transaction boundaries, calls to ports, domain event emission | know about HTTP (`Request`, `HTTPException`, status codes) |
| `repository.py` | Queries for this module's tables only; block-filter helper applied to every people query | commit (the service's unit of work commits) |
| `models.py` | ORM models for tables this module owns | define relationships into another module's tables except by FK column |
| `errors.py` | Module's `DomainError` subclasses with stable `code` strings (03) | — |
| `events.py` | Domain event dataclasses this module publishes | — |
| `jobs.py` | ARQ job functions (thin: load context → call service) | contain business logic |
| `policies.py` | Authorization predicates (`can_read_conversation(user, conv)`) | — |
| `deps.py` | FastAPI dependencies specific to this module | — |
| `public.py` | **The module's only public surface**: re-exports its service interface, DTOs and events for other modules | export models or repositories |

### Dependency rules (enforced in CI by `import-linter`)

1. A module may import another module **only through `app.modules.<name>.public`**.
2. `app.core` and `app.adapters` never import from `app.modules`.
3. Vendor SDKs (`anthropic`, `openai`, `voyageai`, `pywebpush`, payment SDKs, `twilio`, `boto3`) may be imported only under `app/adapters/<port>/`.
4. Only `modules/ai` imports the `LLMProvider` / `EmbeddingProvider` ports (00 §4: "All AI calls go through `modules/ai`").
5. No import cycles between modules. If two modules need each other, one side switches to a domain event (§7.2).

### Cross-module data access
- Reads: through the other module's public service (e.g. `profiles.public.get_event_cards(user_ids)`), which returns DTOs, never ORM objects.
- Hot-path joins that cross modules (block filter, checked-in filter) use shared, read-only SQL helpers in `app/core/db/filters.py` so the rule is written once and tested once.
- Writes to another module's tables: never directly. Call its service or emit an event it handles.

---

## 4. Module catalogue

Each module owns its tables (02) and nothing else writes them.

| Module | Owns (tables / Redis keys) | Responsibilities | v0? |
|---|---|---|---|
| `identity` | `users`, `auth_otps`, `refresh_tokens`, `devices`, `push_subscriptions` | OTP request/verify, JWT issue/verify, refresh rotation + family revocation, `/me`, photo upload flow, data export / delete | ✅ |
| `organizers` | `organizers`, `organizer_members` | Orgs, members, roles (`owner`, `staff`), tenant scoping helpers | ✅ |
| `events` | `events`, `zones`, `event_applications`, `checkins`, `announcements` | Event CRUD + publish, rotating door QR (TOTP), apply/approve, check-in, live stats, announcements | ✅ |
| `profiles` | `event_profiles`, `goals` | Event cards, visibility, goals CRUD, triggers embedding + re-match | ✅ |
| `matching` | `match_scores`, `match_feedback`, `matching_config` | Pipeline stages 1–5 (05), feed, skip, feedback log, recompute jobs | ✅ |
| `waves` | `waves` | Intro cards, rate limits, silent decline, mutual detection, resurface/expiry jobs | ✅ |
| `chat` | `conversations`, `messages` | Conversations, messages (AES-GCM body), read receipts, meet proposals | ✅ |
| `wingman` | — (uses `ai` + `chat`) | `chat_assist`, `icebreakers`, `meeting_brief`; per-user AI quotas; streaming responses | ✅ |
| `connections` | `connections`, `exchange_tokens` (Redis) | Tap-to-exchange, consent-based contact share, CRM notes, follow-up drafts | ✅ |
| `safety` | `blocks`, `reports`, `moderation_actions` | Block (absolute), report, auto-flags, moderation queue, staff actions | ✅ |
| `notifications` | `notifications` (inbox), `notification_prefs` | `notify(user, category, payload)`: WS → push → SMS/WhatsApp fallback, quiet hours, collapse keys | ✅ |
| `realtime` | Redis `ws:*` channels, `ws:ticket:*` | WS ticket issue, socket registry, subscriptions, pub/sub fan-out (delivery only, 07) | ✅ |
| `ai` | `ai_calls`, prompt registry | `LLMProvider` routing, fallbacks, circuit breakers, prompt registry, safety screen, embeddings, Langfuse tracing, kill switches, cost budgets (06) | ✅ |
| `sponsors` | `sponsors`, `sponsor_booths`, `sponsor_leads` | Sponsor entities per event, booths, booth tap-to-exchange leads, aggregate impact report | Tile only in v0 |
| `ads` | `ad_placements`, `ad_impressions_daily` | Sponsored inventory: tiles, sponsored meeting points, sponsored pushes, goal-matched booth nudges; frequency caps; "Sponsored" label; impression/tap counters (aggregated) | Tile only in v0 |
| `billing` | `billing_accounts`, `invoices`, `payments`, `payouts`, `webhook_events`, `ledger_entries` | `PaymentProvider` (Bachs first): checkout, organizer subscriptions, invoices, webhooks, refunds, payouts | Port + Bachs adapter in staging; manual invoices allowed at pilot |
| `analytics` | `analytics_events`, rollup tables | Product event ingest (buffered), organizer ROI aggregates | ✅ (ingest) |
| `media` | — (R2 objects) | Presigned uploads, image variants, moderation hand-off | ✅ |
| `admin` | `audit_log` | `/internal/*` staff endpoints, IP allowlist, audit trail | ✅ (minimal) |

### Guardrails specific to sponsors / ads (PRD 7.1, 08 §6)
- `ads` and `sponsors` may **read** `profiles` goals (for goal-matched nudges) but `matching`, `waves` and the feed **never import** `ads`, `sponsors` or `billing`. This is an `import-linter` contract, which makes "money never touches ranking" a build failure, not a code-review hope.
- Sponsors receive aggregates only. The `sponsors.public` API has no method that returns a user id except `sponsor_leads`, which is written only by the attendee's own booth tap-to-exchange.
- The "Sponsored" label is a server-side enum the client renders; organizers can't edit or remove it.
- Every sponsor text goes through `ai.safety_screen` on save.
- Sponsored pushes go through `notifications` with a separate category, a 1–2 per attendee per day cap, and the user's mute toggle.

### New tables this doc adds to 02 (to be added in the first migrations)

```sql
CREATE TABLE outbox_events (           -- §7.3 transactional outbox
  id TEXT PRIMARY KEY,                 -- obx_
  topic TEXT NOT NULL,                 -- "waves.wave_accepted"
  payload JSONB NOT NULL,
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempts INT NOT NULL DEFAULT 0,
  processed_at TIMESTAMPTZ,
  last_error TEXT
);
CREATE INDEX outbox_pending ON outbox_events (available_at) WHERE processed_at IS NULL;

CREATE TABLE webhook_events (          -- dedupe inbound webhooks (payments, OTP DLRs)
  provider TEXT NOT NULL, provider_event_id TEXT NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL, processed_at TIMESTAMPTZ,
  PRIMARY KEY (provider, provider_event_id)
);

CREATE TABLE audit_log (               -- staff/organizer sensitive actions, exports
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, actor_role TEXT NOT NULL,
  action TEXT NOT NULL, target_type TEXT, target_id TEXT,
  org_id TEXT, event_id TEXT, ip INET, meta JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX ON audit_log (org_id, created_at);

CREATE TABLE push_subscriptions (      -- v0 Web Push (devices.expo_push_token is v1.5)
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL UNIQUE, p256dh TEXT NOT NULL, auth TEXT NOT NULL,
  user_agent TEXT, last_seen_at TIMESTAMPTZ NOT NULL
);
```

`notifications`, `notification_prefs`, `sponsors`, `sponsor_booths`, `sponsor_leads`, `ad_placements`, `ad_impressions_daily` and the `billing` tables get their full DDL in 02 when each module is built (§13). Money tables follow 00 §4: integer minor units + currency, never floats; `ledger_entries` is append-only.

---

## 5. Folder structure

Monorepo (pnpm workspaces for TS, `uv` for Python):

```
ai-network/
├── apps/
│   ├── api/                      # this doc
│   └── web/                      # Next.js: attendee PWA + organizer dashboard (route groups)
├── packages/
│   └── shared-types/             # orval-generated TS client from /openapi.json (committed)
├── infra/
│   ├── docker/                   # Dockerfile (multi-stage), compose files
│   ├── render.yaml               # Render blueprint: api, worker, scheduler (+ ws at stage 2)
│   └── k6/                       # load scripts
├── docs/
│   ├── spec/                     # 00–11
│   ├── adr/                      # architecture decision records (NNNN-title.md)
│   └── runbooks/                 # event-day, incident, secret rotation, restore drill
└── .github/workflows/            # ci.yml, deploy.yml, evals.yml
```

Backend:

```
apps/api/
├── pyproject.toml                # deps, ruff, mypy, pytest, import-linter config
├── uv.lock
├── alembic.ini
├── .env.example                  # every setting, with safe dummy values
├── Makefile                      # make dev | test | lint | migrate | revision | seed | evals
├── migrations/
│   ├── env.py
│   └── versions/                 # YYYYMMDD_HHMM_<slug>.py
├── app/
│   ├── entrypoints/
│   │   ├── api.py                # create_app(role="api")
│   │   ├── ws.py                 # create_app(role="ws")
│   │   ├── worker.py             # ARQ WorkerSettings: collects every module's jobs
│   │   └── scheduler.py          # ARQ cron table
│   ├── bootstrap.py              # app factory: middleware, routers, lifespan, DI container
│   ├── core/                     # framework-level, no business logic
│   │   ├── config.py             # pydantic-settings Settings (single source of config)
│   │   ├── db/
│   │   │   ├── engine.py         # async engine, session factory, pool settings
│   │   │   ├── base.py           # DeclarativeBase, naming convention, mixins (timestamps)
│   │   │   ├── uow.py            # UnitOfWork: one transaction per use case
│   │   │   ├── filters.py        # not_blocked(), checked_in() shared SQL helpers
│   │   │   ├── pagination.py     # opaque cursor encode/decode (ULID keyset)
│   │   │   └── types.py          # ULID type, encrypted text type (AES-GCM)
│   │   ├── redis.py              # client, key builder with namespaces
│   │   ├── security/
│   │   │   ├── jwt.py            # sign/verify with kid rotation
│   │   │   ├── hashing.py        # HMAC for OTP/refresh tokens, constant-time compare
│   │   │   ├── crypto.py         # AES-GCM envelope for messages.body
│   │   │   └── turnstile.py      # Cloudflare Turnstile verify
│   │   ├── auth.py               # current_user, require_checkin, require_org_role deps
│   │   ├── errors.py             # DomainError base + handlers → error envelope
│   │   ├── ratelimit.py          # Redis token bucket + FastAPI dependency
│   │   ├── idempotency.py        # Idempotency-Key middleware/dependency
│   │   ├── events.py             # domain event bus + outbox writer
│   │   ├── jobs.py               # enqueue helper, job context, idempotent job decorator
│   │   ├── flags.py              # feature flags + kill switches (env + Redis override)
│   │   ├── ids.py                # new_id("wav") → "wav_01J…"
│   │   ├── clock.py              # injectable now() for time-warp tests
│   │   ├── logging.py            # structlog JSON config, PII scrubber
│   │   ├── observability.py      # OpenTelemetry, Sentry, Prometheus metrics
│   │   └── middleware.py         # request id, security headers, timing, body size limit
│   ├── adapters/                 # ports (interfaces) + vendor implementations
│   │   ├── llm/        {port.py, anthropic.py, openai_compat.py, fake.py}
│   │   ├── embeddings/ {port.py, voyage.py, fake.py}
│   │   ├── payments/   {port.py, bachs.py, fake.py}
│   │   ├── otp/        {port.py, termii.py, twilio_verify.py, fake.py}
│   │   ├── email/      {port.py, resend.py, fake.py}
│   │   ├── push/       {port.py, webpush.py, expo.py, fake.py}
│   │   ├── storage/    {port.py, r2.py, fake.py}
│   │   └── tracing/    {port.py, langfuse.py, noop.py}
│   └── modules/
│       ├── identity/
│       │   ├── public.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   ├── service.py
│       │   ├── repository.py
│       │   ├── models.py
│       │   ├── errors.py
│       │   ├── events.py
│       │   ├── policies.py
│       │   └── jobs.py
│       ├── organizers/  events/  profiles/  matching/  waves/  chat/  wingman/
│       ├── connections/ safety/  notifications/  realtime/  sponsors/  ads/
│       ├── billing/     analytics/  media/  admin/
│       └── ai/
│           ├── public.py         # complete_task(), screen(), embed() — the only AI API
│           ├── router.py         # (none public; wingman/profiles expose the endpoints)
│           ├── routing.py        # task → [model chain] from config
│           ├── breaker.py        # per-model circuit breaker (Redis)
│           ├── budget.py         # per-user / per-event cost caps
│           ├── registry.py       # task → active prompt version (runtime flag)
│           ├── prompts/          # goal_parser.py (GOAL_PARSER_V1 …), one file per task
│           ├── schemas.py        # Pydantic output schemas per task
│           ├── validators.py     # groundedness, PII-leak, length/tone checks
│           ├── models.py         # ai_calls
│           └── jobs.py           # batch explainers, follow-up drafts
├── tests/
│   ├── conftest.py               # DB/Redis fixtures, app client, fake adapters, clock
│   ├── factories/                # polyfactory builders per model
│   ├── unit/<module>/            # pure service/scoring logic
│   ├── integration/<module>/     # API + DB through httpx.AsyncClient
│   ├── invariants/               # 08 §4 + §6: one file per invariant (blocking in CI)
│   ├── contract/                 # OpenAPI snapshot, error-code catalogue
│   └── evals/                    # golden sets + red-team (06 §7), run by evals.yml
└── scripts/
    ├── seed_event.py             # 200 fake attendees (09 §1)
    └── fixtures/
```

Naming: modules are plural nouns where they own a table of that name; files are snake_case; Pydantic DTOs end in `In` / `Out` (`WaveCreateIn`, `WaveOut`); services are classes named `<Module>Service` with methods named after use cases (`send_wave`, `respond_to_wave`), not CRUD verbs.

---

## 6. Configuration & secrets

- **One `Settings` class** (`pydantic-settings`), loaded once at startup, injected via a dependency. Nested groups: `db`, `redis`, `jwt`, `ai`, `otp`, `push`, `payments`, `storage`, `observability`, `flags`. No `os.getenv` anywhere else (ruff ban rule).
- **Fail fast:** missing or malformed required settings crash the process at boot with a readable error. Prod refuses to start with `fake` adapters or the default dev secrets.
- **Environments:** `ENV=dev|test|staging|prod`. `.env` only for dev; staging/prod use Render environment groups (one group per environment, shared by all roles).
- **Secrets:** never in the repo, logs, traces or error messages. `SecretStr` type for all secrets. Rotation runbook (09 §7): JWT dual secret (`JWT_SECRET`, `JWT_SECRET_NEXT` with `kid`), `MSG_ENC_KEY` with key id prefix on ciphertext so old rows stay readable.
- **Adapter selection by config:** `OTP_PRIMARY=termii`, `OTP_FALLBACK=twilio`, `PAYMENTS_PROVIDER=bachs`, `PUSH_PROVIDER=webpush`. AI routing lives in `ai_routing` config (06 §1a).
- **Feature flags / kill switches:** defaults from env, overridable at runtime from Redis (`flags:*`) via an internal endpoint, cached 10 s. Used for: per-AI-task kill switch, active prompt version, sponsor surfaces on/off per event, static door QR fallback.
- **Tunable business constants** (matching weights, rate limits) live in DB config rows (05 `matching_config`), not env.

---

## 7. Data, transactions, events and jobs

### 7.1 Database
- Driver `asyncpg`; SQLAlchemy 2 typed `Mapped[...]` models; `expire_on_commit=False`.
- **Unit of work per use case:** a service method opens one transaction (`async with uow:`), does its writes, writes outbox rows, commits. Routers never commit.
- **Pooling:** Neon pooled connection string for app roles (PgBouncer, transaction mode → disable asyncpg prepared statement cache: `statement_cache_size=0`); direct (unpooled) URL only for Alembic.
- **Naming convention** in `MetaData` so constraint names are deterministic (`pk_`, `fk_`, `uq_`, `ix_`, `ck_`).
- **IDs:** prefixed ULIDs generated in Python (`core/ids.py`), never in the DB.
- **Keyset pagination** on ULID/`created_at`; never `OFFSET`. Every list is capped at 100.
- **Query discipline:** no lazy loading (`lazy="raise"` default) so N+1 fails loudly in tests; every people-returning query uses `filters.not_blocked()`; every organizer query is filtered by `org_id`/`event_id` in the repository signature (it's a required argument, not optional).
- **Statement timeout:** `SET statement_timeout = '5s'` for API roles, `60s` for workers.
- **Migrations:** Alembic autogenerate then hand-review. Rules: backwards compatible with the running version (expand → migrate → contract across two deploys); `CREATE INDEX CONCURRENTLY` for indexes on existing tables; no data backfills inside schema migrations (use a job); every migration has a `downgrade` or an explicit "irreversible" note; `lock_timeout = '3s'` in migration env.
- **pgvector:** `ivfflat` per 02, created after seed; `SET ivfflat.probes = 10` per matching session; each vector row stores `embedding_model` (06 §1a).

### 7.2 Domain events (in-process)
Modules talk asynchronously through domain events instead of calling each other for side effects. Example: `events.CheckedIn` → `matching` enqueues `compute_for_user`, `realtime` bumps live stats, `analytics` logs. Events are dataclasses in the publisher's `events.py`; handlers register in the subscriber's module. Handlers never run inside the publisher's transaction: they are delivered via the outbox.

### 7.3 Transactional outbox (no lost side effects)
1. The service writes its rows **and** an `outbox_events` row in the same transaction.
2. The outbox relay (worker, polls every 500 ms with `FOR UPDATE SKIP LOCKED`, batch 100) enqueues ARQ jobs / publishes WS messages / sends pushes, then marks the row processed.
3. Retries with exponential backoff (max 10 attempts), then the row stays failed and alerts.
4. Every consumer is **idempotent** (keyed by outbox id or a natural key), because delivery is at-least-once.

Used for: wave sent/accepted, message created (push fallback), check-in, announcement fan-out, payment state changes, sponsor lead created. Pure UI notifications that may be lost (typing, live counters) publish straight to Redis.

### 7.4 Background jobs (ARQ)
- Queues: `default` (expiry, resurface, retention), `ai` (embeddings, explainers, icebreakers, follow-ups), `notify` (push/SMS fan-out). Stage 1 runs all three in one worker process; stage 2 splits `ai` out (09 §6).
- Every job: deterministic `_job_id` for dedupe (`f"compute_for_user:{event_id}:{user_id}"`), explicit timeout, max tries, and structured logs with `job_id` + `request_id` carried from the enqueuer.
- Jobs are thin: build context → call a service method. The same service method is testable without ARQ.
- Debounce (re-embed 30 s, 05 §1) via `_defer_by` + job id dedupe.
- Cron (scheduler role): `recompute_event` every 30 min while live, wave expiry, maybe-later resurface 09:00 local, morning-after, retention purge nightly, `chat_died` labelling, AI batch polling, outbox stuck-row sweep.

### 7.5 Redis key namespaces
`{env}:` prefix on every key. Namespaces: `rl:` rate limits, `idem:` idempotency (24 h), `ws:` pub/sub + tickets, `radar:` presence (07 §4), `cache:` read caches (TTL always set), `flags:`, `breaker:`, `budget:`, `arq:`. A key without a TTL is only allowed in `flags:` (lint check in `core/redis.py` key builder).

### 7.6 Caching
Cache only what's measured to be hot: match feed per user (invalidated on `matches.updated`), block sets per user (60 s, 07 §4), event room bootstrap (15 s), flags (10 s). Cache-aside, always with TTL, never the source of truth.

---

## 8. API layer standards

- **Versioning:** everything under `/v1`. Breaking change → new route version, old one kept until clients migrate.
- **Contracts:** request DTOs `extra="forbid"` (blocks mass assignment); explicit response models on every route (`response_model=`), so nothing leaks by accident. OpenAPI → orval TS client; CI fails on drift (09 §3).
- **Errors:** one envelope (00 §4). Services raise `DomainError(code, message, details, http_status)`; the global handler maps it. Unknown exceptions → `500 internal_error` with `request_id`, no stack trace or SQL ever returned. Validation errors → `422 validation_error` with field paths. Every error code is listed in `tests/contract/error_codes.py` and in 03.
- **Status codes:** 200/201/204 for success, 400 bad input, 401 unauthenticated, 403 authenticated but forbidden, 404 for "not found **or not allowed to know it exists**" (prevents IDOR probing), 409 conflict, 422 validation, 429 rate limited, 503 degraded dependency.
- **Idempotency:** `Idempotency-Key` header on money- and message-creating POSTs (00 §4). Stored in Redis 24 h with request hash; replay returns the stored response; same key + different body → `409 idempotency_key_reused`. Payment webhooks are deduped in Postgres (`webhook_events`) because they must survive a Redis flush.
- **Rate limits:** dependency per route with the limits in 03 §12; global per-IP backstop at Cloudflare.
- **Pagination:** cursor per 00 §4.
- **Request limits:** 1 MB JSON body cap (uploads go direct to R2 via presigned URL), 30 s request timeout, WS message cap 4 KB.
- **Streaming:** wingman responses use SSE (`text/event-stream`) from `POST /ai/assist`, with the same auth and rate limit.
- **Webhooks:** `POST /v1/webhooks/{provider}`: verify signature inside the adapter → insert `webhook_events` (PK dedupe) → enqueue processing → return 200 fast.

---

## 9. Security architecture

Builds on 08; this is how it's wired in code.

### 9.1 Authentication
- OTP: 6 digits via `secrets`, stored as **HMAC-SHA256 with a server pepper** (stronger than the plain SHA-256 in 08 §1 for a 6-digit space), 10 min TTL, 5 attempts, Turnstile check before send, SMS country allowlist, per-destination / per-prefix / per-IP caps (08 §6).
- Access JWT: 15 min, HS256 with `kid` rotation; verified in `core/auth.py` with `leeway=10s`, required claims, `aud`/`iss` set. Refresh: opaque 256-bit, hashed, rotating with family revocation (08 §1).
- WebSocket: single-use 30 s ticket (07 §1); JWT never in URLs.
- Organizer dashboard: same tokens; refresh token stored in an `HttpOnly; Secure; SameSite=Strict` cookie on the dashboard domain, access token in memory.

### 9.2 Authorization
- Authorization is **always a dependency or a policy function**, never an `if` inside a handler: `require_user`, `require_checkin(event_id)`, `require_visibility(min)`, `require_org_role(event_id, role)`, `require_staff`.
- **Object-level checks (BOLA/IDOR):** every route that takes an id loads the object through a policy that checks ownership/participation, and returns 404 on failure. Covered by a parametrized test that calls every route with another user's ids.
- **Tenant isolation:** organizer repositories require `org_id`; invariant `test_tenant_isolation`.
- **Organizer scope:** aggregates and own-event operational data only (08 §6). **Sponsor scope:** aggregates only.
- **Staff/admin:** `/internal/*` behind `require_staff` + IP allowlist + `audit_log` on every action.

### 9.3 Data protection
- `messages.body` encrypted with AES-GCM via a custom SQLAlchemy type (key id prefix for rotation).
- PII scrubbing in the log formatter (phone/email regexes) and in Langfuse export (06 §6). Auth and chat request bodies are never logged.
- DB roles: `app_rw` (DML only, no DDL), `migrator` (DDL), `readonly` (analytics/support).
- R2: private bucket, presigned PUT (8 MB, content-type pinned) and signed/CDN GET for approved variants only; EXIF stripped on variant generation.

### 9.4 Payments (first provider: Bachs)
- **First provider: [Bachs](https://bachs.io/)**, confirmed by Victor 2026-11-14 (DECISIONS-NEEDED #10). It covers what we need in one integration: hosted checkout (cards, mobile money, bank transfer, stablecoins), subscriptions and usage billing (fits organizer SaaS tiers), invoicing, dunning, VAT/GST, signed webhooks, and settlement to NGN/GHS/KES/ZAR bank accounts. API docs: `docs.bachs.io`. It has a Python SDK, which is imported only inside `adapters/payments/bachs.py`.
- `PaymentProvider` port: `create_checkout`, `verify_webhook`, `get_payment`, `refund`, `create_customer`, `create_subscription` / `change_subscription` / `cancel_subscription`, `report_usage`, `create_invoice`. Payout methods (`create_transfer`, `create_bulk_transfer`) are in the port for Office Hours (v2), but Bachs's site doesn't advertise bulk payouts to third parties, so confirm that against its API docs before v2; if it can't, a second adapter handles payouts behind the same port.
- Usage: organizer plans = Bachs subscriptions; sponsor revenue share and invoices = Bachs invoices; pilot can still bill manually (00 §3) with the adapter live in staging.
- Rules: we never touch card data (hosted checkout only); amounts in minor units; webhooks verified + deduped (`webhook_events`); state changes only from verified webhooks or server-side verification calls, never from client redirects; every money movement writes an append-only `ledger_entries` row; `fake` adapter for dev and tests.

### 9.5 Platform hardening
- Security headers middleware (HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'` on API), strict CORS allowlist (web app + dashboard origins only), `TrustedHost`.
- Only Cloudflare can reach the origin (Render custom domain + Cloudflare proxied; origin checks `CF-Connecting-IP` from trusted ranges for rate limiting).
- Outbound HTTP via one shared `httpx.AsyncClient` per adapter with timeouts on connect/read; no user-supplied URLs are ever fetched server-side (SSRF).
- Supply chain: `uv.lock` pinned, Dependabot/Renovate, `pip-audit` in CI, `bandit` subset via ruff `S` rules, `gitleaks` secret scan, Docker image runs as non-root on a slim base.
- AI: `<user_data>` tagging, structured outputs, safety screen, PII-leak validator (06 §2, §8).

---

## 10. Error handling & resilience

- **Exception hierarchy** (`core/errors.py`): `DomainError` → `NotFound`, `Forbidden`, `Conflict`, `RateLimited`, `ValidationFailed`, `DependencyUnavailable`. Modules subclass with their codes (`WaveLimitReached(RateLimited)`). Adapters translate vendor exceptions into `DependencyUnavailable` / `DependencyRejected`, so vendor exception types never leak into services.
- **No silent swallows:** `except Exception` only at process boundaries (global handler, job wrapper, outbox relay), always logged with stack trace and sent to Sentry. Ruff `BLE`/`TRY` rules on.
- **Timeouts everywhere:** HTTP adapters 3–5 s for sync paths (06 §9), DB statement timeout, Redis 500 ms, job timeouts.
- **Retries:** only on idempotent operations, exponential backoff with jitter (`tenacity`), capped. Never retry a non-idempotent POST to a vendor without an idempotency key.
- **Circuit breakers:** per AI model (06 §1) and per OTP/push provider; open breaker → fallback adapter.
- **Degradation ladder (09 §7):** AI down → cached matches, template explanations, chat without wingman. Redis down → REST still serves (rate limiter fails open for reads, fails **closed** for OTP send and waves), WS/radar off, client polls. Push down → inbox + SMS for critical categories.

---

## 11. Observability

- **Logs:** `structlog` JSON to stdout: `ts, level, msg, request_id, trace_id, user_id, org_id, event_id, route, status, latency_ms, role`. Context vars carry ids from request → service → enqueued job → outbox → WS publish.
- **Tracing:** OpenTelemetry (FastAPI, SQLAlchemy, httpx, Redis instrumentation) exported to Grafana Cloud Tempo; AI calls additionally traced in Langfuse linked by `request_id`.
- **Errors:** Sentry with release = git SHA, environment tag, PII scrubbing on, 100% errors / 10% transactions.
- **Metrics (RED + business):** request rate/errors/duration per route, WS connections, queue depth and job latency per queue, outbox lag, DB pool usage, AI tokens/cost/latency/fallback per task, OTP send/fail per provider, check-ins/min, waves sent/accepted. Exposed at `/internal/metrics` (Prometheus format, staff/IP-gated).
- **Health:** `GET /livez` (process up, no dependencies), `GET /readyz` (DB `SELECT 1`, Redis `PING`, migrations at head; used by Render health check). Workers write a heartbeat key; an alert fires if it's stale > 60 s.
- **Alerts and event-day dashboard:** as 09 §4 and 06 §6, plus outbox lag > 30 s and worker heartbeat missing.

---

## 12. Testing strategy (backend)

| Layer | What | Tooling | Runs |
|---|---|---|---|
| Unit | Scoring math, policies, validators, pure service logic with fake adapters | pytest, hypothesis (05 properties) | every PR |
| Integration | Routes → service → real Postgres + Redis; each test in a rolled-back transaction | pytest-asyncio, httpx `AsyncClient`, Postgres+pgvector and Redis service containers in CI | every PR |
| Invariants | 00 §4 + 08 §4/§6: silent decline, blocks absolute, no location leak, first contact structured, money never ranks (incl. sponsors), tenant isolation, organizer scope, sponsor aggregates only | `tests/invariants/` | every PR, blocking |
| Authorization sweep | Every route × (anonymous, other user, other org) → 401/404 | parametrized from the OpenAPI route table | every PR |
| Contract | OpenAPI snapshot, error-code catalogue, orval drift | pytest + CI diff | every PR |
| Architecture | Module boundaries, vendor-SDK import bans, sponsors/billing never imported by matching | `import-linter` | every PR |
| Migrations | `upgrade head` → `downgrade -1` → `upgrade head` on empty DB; autogenerate shows no drift | Alembic in CI | every PR |
| AI evals | Golden + red-team sets (06 §7) | `tests/evals`, `evals.yml` | on prompt/model/provider change, blocking on regression |
| Load | Check-in burst, chat, wingman, WS fan-out | k6 (`infra/k6`) | before each event |
| E2E | Owned by `apps/web` (Playwright) against staging | — | pre-release |

Rules: external vendors are faked at the **port**, never by mocking our own services; HTTP adapters themselves get a small test with `respx` against recorded responses; time-dependent logic uses the injectable clock (`core/clock.py`) for time-warp tests (resurface at 09:00, expiry); coverage is not a target, but every bug fix ships with a test that fails without it.

---

## 13. Tooling, local dev and CI/CD

- **Python tooling:** `uv` (deps + venv), `ruff` (lint + format; rule sets E, F, I, B, UP, S, BLE, TRY, ASYNC, PT, SIM, RUF), `mypy --strict` on `app/`, `import-linter`, `pre-commit` running the same checks.
- **Local:** `docker compose up` starts Postgres (pgvector image), Redis, api (reload), worker, scheduler; `make seed` loads the 200-attendee event; fake adapters by default so no vendor keys are needed; real adapters opt-in per service via env.
- **Docker:** multi-stage build (uv install in builder, slim runtime, non-root user, `PYTHONDONTWRITEBYTECODE`, healthcheck). One image for all roles.
- **CI (`ci.yml`, every PR):** lint → type check → import-linter → migrations check → unit + integration + invariants + contract → `pip-audit` + `gitleaks` → OpenAPI/orval drift. Required checks on `main`.
- **CD (`deploy.yml`):** merge to `main` → build image tagged with SHA → deploy staging (pre-deploy `alembic upgrade head`) → smoke tests → manual promote to prod. Rollback = redeploy previous image (migrations are backward compatible by rule).
- **Branching:** trunk-based, short-lived branches, squash merge, Conventional Commits, PR template with "security / migration / AI prompt change" checkboxes.
- **ADRs:** any change to a decision in 00 §3 or this doc gets an ADR in `docs/adr/`.

---

## 14. Build order (backend)

Aligned to the v0 plan (10 §v0). Each step ends green in CI and deployed to staging.

| Step | Week | Deliverable | Done when |
|---|---|---|---|
| B0 Foundations | 1 | Repo scaffold (§5), `core/` (config, db, uow, errors, logging, ids, clock, redis, middleware), health routes, Docker + compose, CI with all gates, Render blueprint, Sentry + OTel | `docker compose up` works; `/readyz` green on staging; a deliberate boundary violation fails CI |
| B1 Ports & fakes | 1 | All ports in `adapters/` with fake implementations; Anthropic + Voyage + Langfuse real adapters; `ai` module skeleton with routing, breaker, `ai_calls` | A test AI call through `ai.public` shows in Langfuse and `ai_calls` |
| B2 Outbox, jobs, flags | 1 | `outbox_events`, relay, ARQ worker + scheduler, job decorator, flags/kill switches | An event written in a transaction reaches a job exactly once under retry tests |
| B3 Identity | 2 | OTP (Termii + Twilio fallback + Turnstile + fraud caps), JWT + refresh rotation, `/me`, media presign/commit, push subscriptions | Refresh reuse revokes family (test); signup on a real phone < 90 s |
| B4 Organizers & events | 2 | Orgs/members, events CRUD + publish, rotating door QR, apply/approve, check-in, live stats over WS, announcements | Invariant `test_tenant_isolation` green; check-in from laptop door screen |
| B5 Profiles & goals | 3 | Event cards + visibility, goals + `goal_parser`, embeddings jobs, `safety_screen` on profile fields | Free text → parsed goal → embedded; injection in bio flagged |
| B6 Connections | 3 | Tap-to-exchange tokens, dual confirm, consent share, CRM notes, morning-after `followup_drafts` | Two phones exchange contacts; draft ready next morning |
| B7 Matching | 4 | Pipeline 05 stages 1–5, `match_scores`, feed, skip, feedback, `match_explainer` batch + live, recompute cron | Worked example 05 §10 reproduces; feed < 300 ms from cache |
| B8 Waves & safety | 4 | Waves, inbox/sent masking, respond, mutual, resurface/expiry, blocks, reports, auto-flags | `test_silent_decline`, `test_block_absolute`, `test_first_contact_structured` green |
| B9 Realtime, chat, wingman | 5 | WS tickets + gateway + pub/sub, conversations/messages (encrypted), read receipts, meet proposals, `icebreakers`, `chat_assist` SSE, quotas | Chat works through 2 API instances with AI keys removed; wingman evals pass |
| B10 Notifications, sponsors/ads (tile), billing | 5 | `notify()` pipeline (WS → web push → SMS/WhatsApp), inbox, prefs, quiet hours; sponsor + one sponsor tile placement with label + screening; `billing` port + Bachs adapter (checkout + webhook) + fake | `test_money_never_ranks` covers sponsors; `test_sponsor_aggregates_only` green |
| B11 Hardening | 6 | Authorization sweep, retention jobs, export/delete, audit log, admin moderation endpoints, dashboards + alerts, k6 load test, runbooks, restore drill | All CI gates green; load test passes on staging; go/no-go for pilot |

After the pilot: radar (v1.5), full sponsor inventory and ads delivery, exhibitor booths, ROI report, org subscriptions on Bachs, payouts, Office Hours, premium.

---

## 15. Open items feeding DECISIONS-NEEDED

| Item | Default until decided |
|---|---|
| Bachs bulk payouts to third parties (needed for Office Hours, v2) | Check docs.bachs.io before v2; second payout adapter behind the same port if not supported |
| 08 §1 says Twilio Verify for SMS, 00 §3 says Termii primary | Follow 00 §3: Termii primary, Twilio Verify fallback |
| Grafana Cloud vs Better Stack for logs/metrics (09 §2 mentions both) | Grafana Cloud (metrics + traces + logs in one place); Render logs as backup |
| `devices.expo_push_token` (02) vs Web Push in v0 | Add `push_subscriptions` now; `devices` used from v1.5 (Expo) |
