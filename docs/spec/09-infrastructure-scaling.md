# 09 — Infrastructure, Operations & Scaling

## 1. Environments

| Env | Purpose | Data |
|---|---|---|
| `dev` | local: docker-compose (postgres+pgvector, redis, api, worker); Expo dev client against local API | seeded fake event (script below) |
| `staging` | mirrors prod topology, small tier; every merge to `main` auto-deploys | anonymized/seeded only |
| `prod` | pilot + real events | real |

Seed script `apps/api/scripts/seed_event.py`: creates 1 event, 200 fake attendees with realistic goals (generated once by Claude, checked into repo as fixtures), embeddings precomputed — the matching engine is developable offline.

## 2. Topology (prod, stage 1)

```
Cloudflare (DNS, TLS, WAF, rate-limit backstop)
  → Render (Frankfurt): api (uvicorn, 2× instances, scale to 4 on event days)
  → Render: worker (arq, 1 instance; split into default + ai pools at stage 2)
  → Render: cron (arq scheduler)
Neon Postgres (pgvector, PITR)          Upstash Redis
Cloudflare R2 + CDN (photos)            Vercel (dashboard)  EAS (mobile builds)
Sentry (all three apps)                 Better Stack / Render logs
Langfuse (AI traces, prompts, evals)
```

Config: 12-factor env vars. Full list maintained in `apps/api/.env.example` (DATABASE_URL, REDIS_URL, JWT_SECRET, JWT_SECRET_NEXT, ANTHROPIC_API_KEY, VOYAGE_API_KEY, R2_*, EXPO_ACCESS_TOKEN, TWILIO_*, RESEND_*, SENTRY_DSN, MSG_ENC_KEY, PAYSTACK_*/STRIPE_* [v2]).

## 3. CI/CD (GitHub Actions)

1. PR: ruff + mypy + pytest (api); biome + tsc + vitest (ts packages); OpenAPI client freshness check (`orval` output committed — CI fails if drift).
2. Merge to `main`: build Docker image → deploy staging → run smoke tests (auth, checkin, wave happy path against staging) → manual promote to prod (one click).
3. Migrations: `alembic upgrade head` runs as pre-deploy step; all migrations must be backwards-compatible with the previous app version (two-phase for destructive changes).
4. Mobile: EAS Build on tag; EAS Update (OTA) from `main` for JS-only changes — the event-day hotfix path.

## 4. Observability

- **Logs:** structured JSON (request_id, user_id, route, latency). PII-scrubbed (08 §5).
- **Sentry:** API + mobile + dashboard, release-tagged.
- **Metrics** (Prometheus-style counters exposed at `/internal/metrics`, scraped or pushed to Grafana Cloud): request rate/latency per route, WS connections, queue depth per job, AI latency + token spend per task, checkin rate, wave send/accept counters.
- **Event-day mission control:** one Grafana dashboard: check-ins/min, error rate, p95 latency, WS connections, queue depth, AI spend, OTP delivery failures. Alerts (to WhatsApp/Telegram): error rate > 2%, p95 > 1.5 s, queue depth > 500, AI spend > $150/event, OTP failure > 10%.

## 5. Capacity math (design targets)

Pilot assumptions: 1,000 attendees, 700 concurrent app users at peak (keynote break).

| Load | Estimate | Design headroom |
|---|---|---|
| Check-in burst | 1,000 over 45 min ≈ 0.4 rps avg, 5 rps burst | trivial; endpoint is 2 queries + enqueue |
| Chat | 700 users × 1 msg/2 min ≈ 6 msg/s | WS fan-out via Redis: fine to ~2k msg/s per node |
| Radar sightings | 200 active radar users × 1 req/10 s = 20 rps | Redis pipeline ≈ 1 ms each |
| Matching batch | 1,000 users × K=60 pairs ≈ 30k pair-scores/run | vector ops in-process ≈ seconds; explanations are the cost → batch |
| WS connections | ≤ 1,000 | single instance handles 10k+; we run 2 |
| Push burst (announcement) | 1,000 pushes | Expo batch API, worker chunks of 100 ≈ seconds |

Postgres at this scale is a rounding error. **The only real scaling costs are AI tokens and push bursts — both queued.**

## 6. Scaling stages (build the current one, know the next one)

**Stage 1 — pilot to ~5 events/month, ≤ 3k attendees each (current design).** Monolith ×2, one worker, one DB. Nothing more.

**Stage 2 — ~50 events/month, big events to 10k attendees.**
- API autoscale 4–8; split worker pools: `default` vs `ai` (AI latency can't starve wave expiry).
- Postgres: add read replica (directory/feed reads); pgbouncer; move `analytics_events` writes to buffered batch inserts.
- pgvector: raise ivfflat lists; per-event partial indexes if ANN latency > 50 ms.
- WS: dedicated WS deployment (same image, `ROLE=ws`), Redis pub/sub unchanged.
- Multi-event isolation: per-event Redis key prefixes already in place; per-event rate budget for AI.

**Stage 3 — platform scale (hundreds of concurrent events, 100k+ MAU).**
- Partition hot tables by `event_id` (checkins, waves, messages by conversation hash).
- Extract chat into its own service *only if* WS+message write load demands it (boundary is already clean: modules/chat).
- Analytics → ClickHouse or warehouse; ML feedback pipeline productionized.
- Multi-region: keep single write region; move read replicas + CDN close to event geographies. (Events are geographically local — pin an event's traffic to its nearest region at the LB when this matters.)

Explicit non-goals until data forces them: Kubernetes, microservices, GraphQL, multi-write-region.

## 7. Runbooks (write before pilot; live in `docs/runbooks/`)

- Event-day: pre-flight checklist (scale API to 4, warm caches, test OTP delivery on local carriers, door-screen check), on-call rotation, degradation ladder: AI down → cached matches + chat without wingman; Redis down → REST-only mode (no WS/radar, app functional); push down → in-app only.
- Incident: severity levels, who flips the static-QR fallback, comms template to organizer.
- Secret rotation: JWT (dual-secret window), API keys, R2 keys.
- Restore drill: Neon PITR to staging, verify counts, before first real event.
