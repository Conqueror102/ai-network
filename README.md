# AiNetwork (working title)

AI-powered event networking: an AI "wingman" that handles discovery, matching, first contact, and icebreaking at events — so humans only do the real conversation. Rejection-proof by design, organizer-distributed, privacy-first.

## Documents

**Build from `docs/spec/` — it is the prescriptive, build-ready specification. On any conflict, spec wins over the planning docs.**

| Spec | Contents |
|---|---|
| [spec/00-overview.md](docs/spec/00-overview.md) | Conventions, fixed stack decisions (with rejected alternatives), invariants, glossary |
| [spec/01-product-spec.md](docs/spec/01-product-spec.md) | Exact behavior of every feature: rules, edge cases, analytics |
| [spec/02-domain-model.md](docs/spec/02-domain-model.md) | Full PostgreSQL schema + retention schedule |
| [spec/03-api-spec.md](docs/spec/03-api-spec.md) | Every endpoint, error codes, rate limits |
| [spec/04-flows.md](docs/spec/04-flows.md) | Sequence flows for every journey incl. failure branches |
| [spec/05-matching-engine.md](docs/spec/05-matching-engine.md) | Scoring formulas, constants, jobs, feedback loop, worked example |
| [spec/06-ai-layer.md](docs/spec/06-ai-layer.md) | Every AI task: prompts contract, models, fallbacks, injection defense, cost model |
| [spec/07-realtime.md](docs/spec/07-realtime.md) | WebSocket protocol, push catalogue, radar Redis design |
| [spec/08-security-privacy.md](docs/spec/08-security-privacy.md) | Auth design, threat model, test-enforced privacy invariants |
| [spec/09-infrastructure-scaling.md](docs/spec/09-infrastructure-scaling.md) | Deploy topology, CI/CD, observability, capacity math, 3 scaling stages |
| [spec/10-build-plan.md](docs/spec/10-build-plan.md) | Milestones M0–M8 with definitions of done, test strategy |
| [spec/DECISIONS-NEEDED.md](docs/spec/DECISIONS-NEEDED.md) | The only open items — everything else is decided |

Planning/rationale docs (context, superseded by spec on conflict):

| Doc | What's in it |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Vision, personas, principles, feature scope (v1 / v1.5 / v2), monetization, metrics, risks |
| [docs/user-stories.md](docs/user-stories.md) | User stories by epic with priorities and acceptance criteria |
| [docs/architecture.md](docs/architecture.md) | System architecture summary, key flows, AI layer, security invariants |
| [docs/tech-stack.md](docs/tech-stack.md) | Stack choices with rationale, repo layout, tooling, cost sketch |

## The one-paragraph pitch

At a conference, you set goals ("meet fintech CTOs raising Series A"). The app matches you two-way with other checked-in attendees, drafts a warm intro you approve with one tap, and delivers it as a card the other person can silently accept or decline — nobody ever gets rejected to their face. Accepted intros open an AI-seeded chat, then a concrete meet ("Coffee point B, 15:30"). Organizers get QR check-in, live attendance, and hard numbers proving their event created real connections.

## Core design rules (never break these)

1. Double opt-in for all first contact; declines are silent.
2. AI drafts, humans approve — nothing sends autonomously.
3. No precise location ever: proximity only as coarse buckets ("right here" / "at the event") via Bluetooth range — no distances, no maps of people, no remote tracking possible.
4. First contact is a structured card, never free text.
5. The organizer is the customer; check-in is the distribution channel.

## Stack (summary)

Expo/React Native (mobile) · Next.js (organizer dashboard) · FastAPI (backend) · PostgreSQL + pgvector · Redis · Claude API (`claude-opus-4-8`) + Voyage embeddings · Expo Push · Paystack/Stripe.
