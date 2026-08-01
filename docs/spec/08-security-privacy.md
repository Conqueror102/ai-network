# 08 — Security & Privacy

## 1. Authentication design

- OTP: 6 digits, `secrets.randbelow`, stored as SHA-256 hash; 10-min expiry; 5 attempts; resend cooldown 60 s; destination rate limits (03 §12). SMS via Twilio Verify (NG routes tested!), email via Resend.
- JWT access: HS256, 15 min, claims `{sub, exp, iat, jti, premium}`. Secret in env; `kid` header supports rotation (two active secrets during rotation window).
- Refresh: opaque 256-bit random, SHA-256 stored, 30-day expiry, **rotating with family detection** — each use issues a new token in the same `family_id` and revokes the used one; presenting a revoked token revokes the entire family (stolen-token containment) and forces re-login.
- Logout: revokes presented refresh token. "Logout everywhere": revokes all families for user.

## 2. Authorization matrix

| Action | Rule |
|---|---|
| Read event room / directory / feed | checked-in at event ∧ own visibility ≥ directory |
| Radar list / sightings | + own visibility = radar |
| Send wave | checked-in ∧ rate limits ∧ no block ∧ unique pair |
| Read conversation | participant only |
| Organizer endpoints | `organizer_members` row for event's org (announcements/exports: any role; billing/member mgmt: `owner`) |
| Admin/moderation | separate internal role (`users.is_staff` bool + IP allowlist on `/internal/*`) |

Enforced via FastAPI dependencies (`require_checkin(event_id)`, `require_org_role(...)`) — never inline in handlers.

## 3. Threat model & mitigations

| Threat | Mitigation |
|---|---|
| **Stalking via radar** | No distance/direction/RSSI to clients; rotating anonymous BLE tokens (5 min); physical-presence requirement; reciprocity; ghost mode; blocks absolute; bucket data TTL 120 s |
| **Scraping the directory** | Auth + check-in required; per-user rate limits; pagination caps; no bulk contact fields (contact details only via mutual tap-to-exchange); export endpoints consent-gated |
| **Harassment via waves/chat** | Structured-card first contact (no free text pre-accept); note safety screen; wave rate limits + unique pair; auto-pause on decline streak; block/report |
| **Fake profiles / impersonation** | OTP-verified channel; photo moderation; report → impersonation queue; [v1.5] organizer can require registration email match |
| **Prompt injection via profiles/messages into AI** | `<user_data>` tagging + structured outputs + injection category in safety screen (06 §2) |
| **QR replay (remote check-in)** | Rotating door QR (60 s TOTP, ±90 s window); static fallback is explicit organizer opt-in |
| **Token theft** | Short access TTL; rotating refresh with family revocation; tokens never logged; TLS everywhere |
| **Payment fraud (v2)** | Provider-side checkout (no PAN touches us); webhook signature verification; idempotent webhook handling; payout delay T+2 d |
| **Insider/data exposure** | Least-privilege DB roles (app user has no DDL); PII columns documented; staff actions audit-logged (`reports.actioned_by`, admin log table) |
| **DoS on event day** | Per-IP + per-user rate limits; check-in endpoint O(1); Cloudflare in front |

## 4. Privacy invariants (repeat of 00 §4 — test-enforced)

Each invariant has a dedicated test in `tests/invariants/`:
1. `test_no_location_leak`: fuzz all people-returning endpoints; assert no `rssi|distance|lat|lng|zone` fields pre-acceptance.
2. `test_silent_decline`: sender's wave view identical byte-for-byte before/after `not_now`.
3. `test_block_absolute`: after block, both users absent from every list/feed/radar/chat surface of the other.
4. `test_first_contact_structured`: no API path delivers sender free text pre-accept except the screened 140-char note.
5. `test_money_never_ranks`: premium flag and office-hours host status leave `match_scores` and feed order unchanged.

## 5. Data protection

- Encryption: TLS 1.2+ in transit; provider disk encryption at rest; `messages.body` additionally app-layer encrypted (AES-GCM, key in env/KMS) so DB dumps don't expose chats.
- PII inventory: `users.phone/email/real_name`, `connections.shared`, message bodies. Everything else is pseudonymous behind ULIDs.
- NDPR/GDPR rights: export (`GET /me/export`, async, 72 h SLA) and erasure (`DELETE /me`, 30-day hard delete) — see retention table in 02.
- Logs: structured JSON; PII scrubbed at the logging formatter (phone/email regex redaction); request bodies never logged on auth/chat routes.
- Backups: daily automated (Neon PITR); restore drill before pilot event (10 §4).
- Secrets: platform env vars; no secrets in repo; rotation runbook in 09 §7.
