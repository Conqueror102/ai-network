# 02 — Domain Model (PostgreSQL 16 + pgvector)

Authoritative schema. Migrations via Alembic; this file is the target state for v1 + v1.5 (v2 tables marked). Conventions: ULID text PKs (prefixed), `TIMESTAMPTZ` UTC, `created_at DEFAULT now()` on every table (not repeated below), FKs `ON DELETE` as stated.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Identity ---------------------------------------------------------------
CREATE TABLE users (
  id             TEXT PRIMARY KEY,                    -- usr_
  phone          TEXT UNIQUE,                         -- E.164, nullable
  email          TEXT UNIQUE,                         -- lowercased, nullable
  CHECK (phone IS NOT NULL OR email IS NOT NULL),
  verified_at    TIMESTAMPTZ NOT NULL,
  real_name      TEXT,
  display_name   TEXT,
  photo_url      TEXT,                                -- 512px variant key
  photo_status   TEXT NOT NULL DEFAULT 'none',        -- none|pending|approved|rejected
  headline       TEXT CHECK (char_length(headline) <= 80),
  bio            TEXT CHECK (char_length(bio) <= 600),
  role_title     TEXT,
  company        TEXT,
  industry       TEXT,                                -- picker code
  skills         TEXT[] NOT NULL DEFAULT '{}',
  links          JSONB  NOT NULL DEFAULT '[]',        -- [{label,url}]
  home_area_code TEXT,                                -- picker code "NG-LA-LEKKI" (v2)
  share_email    BOOL NOT NULL DEFAULT false,         -- tap-to-exchange defaults
  share_phone    BOOL NOT NULL DEFAULT false,
  premium_until  TIMESTAMPTZ,                         -- v2
  deleted_at     TIMESTAMPTZ,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth_otps (
  id TEXT PRIMARY KEY, channel TEXT NOT NULL,          -- phone|email
  destination TEXT NOT NULL, code_hash TEXT NOT NULL,
  attempts INT NOT NULL DEFAULT 0, expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ
);
CREATE INDEX ON auth_otps (destination, expires_at);

CREATE TABLE refresh_tokens (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  family_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  device_info JSONB, expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ
);
CREATE INDEX ON refresh_tokens (user_id, family_id);

CREATE TABLE devices (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expo_push_token TEXT NOT NULL, platform TEXT NOT NULL,      -- ios|android
  last_seen_at TIMESTAMPTZ NOT NULL, UNIQUE (user_id, expo_push_token)
);

-- 2. Organizers & events ----------------------------------------------------
CREATE TABLE organizers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, logo_url TEXT,
  billing_email TEXT, created_by TEXT NOT NULL REFERENCES users(id)
);

CREATE TABLE organizer_members (
  organizer_id TEXT NOT NULL REFERENCES organizers(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner','staff')),
  PRIMARY KEY (organizer_id, user_id)
);

CREATE TABLE events (
  id TEXT PRIMARY KEY, organizer_id TEXT NOT NULL REFERENCES organizers(id),
  name TEXT NOT NULL, description TEXT, cover_url TEXT,
  venue_name TEXT NOT NULL, city_code TEXT NOT NULL, address TEXT,
  starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ NOT NULL,
  CHECK (ends_at > starts_at),
  capacity INT, gating TEXT NOT NULL DEFAULT 'open' CHECK (gating IN ('open','apply')),
  visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','unlisted')),
  door_qr_seed TEXT NOT NULL,                          -- TOTP seed for rotating door QR
  static_door_qr_enabled BOOL NOT NULL DEFAULT false,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','live','ended','cancelled')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON events (city_code, starts_at) WHERE visibility = 'public' AND status IN ('published','live');

CREATE TABLE zones (                                    -- sessions/rooms; analytics only
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'session',   -- session|room
  starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ, qr_token TEXT NOT NULL UNIQUE
);

CREATE TABLE event_applications (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  decided_by TEXT REFERENCES users(id), decided_at TIMESTAMPTZ,
  UNIQUE (event_id, user_id)
);

CREATE TABLE checkins (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  zone_id TEXT REFERENCES zones(id) ON DELETE SET NULL,       -- NULL = door check-in
  scanned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX one_door_checkin_per_day ON checkins
  (event_id, user_id, (scanned_at::date)) WHERE zone_id IS NULL;
CREATE INDEX ON checkins (event_id, zone_id, scanned_at);

-- 3. Event profiles & goals ---------------------------------------------------
CREATE TABLE event_profiles (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL, display_photo_url TEXT, headline TEXT,
  offer_text TEXT CHECK (char_length(offer_text) <= 300),
  visibility TEXT NOT NULL DEFAULT 'directory'
    CHECK (visibility IN ('hidden','directory','radar')),
  profile_embedding vector(1024),                       -- offer_text + headline + bio
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (event_id, user_id)
);
CREATE INDEX ON event_profiles (event_id) WHERE visibility <> 'hidden';
-- ANN index (build after seeding; lists ≈ sqrt(rows), start 100):
CREATE INDEX ep_embed_idx ON event_profiles
  USING ivfflat (profile_embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE goals (
  id TEXT PRIMARY KEY,
  event_profile_id TEXT NOT NULL REFERENCES event_profiles(id) ON DELETE CASCADE,
  intent TEXT NOT NULL CHECK (intent IN
    ('hire','get_hired','raise','invest','sell','buy','learn','cofounder','partner','meet')),
  target JSONB NOT NULL DEFAULT '{}',                   -- {roles:[],industries:[],stage:[]}
  offer TEXT CHECK (char_length(offer) <= 300),
  raw_input TEXT,                                       -- what the user typed/spoke
  priority INT NOT NULL CHECK (priority BETWEEN 1 AND 3),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  ask_embedding   vector(1024),                         -- embed(intent+target+raw ask)
  offer_embedding vector(1024),                         -- embed(offer)
  UNIQUE (event_profile_id, priority)
);
CREATE INDEX goal_ask_idx ON goals USING ivfflat (ask_embedding vector_cosine_ops) WITH (lists=100);

-- 4. Waves, conversations, connections ---------------------------------------
CREATE TABLE waves (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  from_user TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  to_user   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  CHECK (from_user <> to_user),
  source TEXT NOT NULL CHECK (source IN ('match_feed','radar','directory')),
  card JSONB NOT NULL,                                  -- frozen intro card at send time
  note TEXT CHECK (char_length(note) <= 140),           -- safety-screened one-liner
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','accepted','not_now','maybe_later','expired')),
  resurfaced BOOL NOT NULL DEFAULT false,
  resolved_at TIMESTAMPTZ,
  UNIQUE (event_id, from_user, to_user)
);
CREATE INDEX ON waves (to_user, status) WHERE status IN ('pending','maybe_later');
CREATE INDEX ON waves (event_id, status);

CREATE TABLE conversations (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id),
  user_a TEXT NOT NULL REFERENCES users(id), user_b TEXT NOT NULL REFERENCES users(id),
  CHECK (user_a < user_b),                              -- canonical ordering
  created_from_wave TEXT REFERENCES waves(id),
  last_message_at TIMESTAMPTZ,
  UNIQUE (event_id, user_a, user_b)
);
CREATE INDEX ON conversations (user_a, last_message_at DESC);
CREATE INDEX ON conversations (user_b, last_message_at DESC);

CREATE TABLE messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender_id TEXT REFERENCES users(id),                  -- NULL = system/wingman block
  kind TEXT NOT NULL DEFAULT 'text' CHECK (kind IN ('text','system','icebreakers','meet_proposal')),
  body TEXT NOT NULL CHECK (char_length(body) <= 2000),
  payload JSONB,                                        -- structured part for non-text kinds
  ai_assisted BOOL NOT NULL DEFAULT false,
  delivered_at TIMESTAMPTZ, read_at TIMESTAMPTZ
);
CREATE INDEX ON messages (conversation_id, id);         -- ULID = time-ordered

CREATE TABLE connections (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  peer_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_id TEXT NOT NULL REFERENCES events(id),
  met_confirmed_at TIMESTAMPTZ,                         -- set by tap-to-exchange
  shared JSONB NOT NULL DEFAULT '{}',                   -- what peer shared with me {email,phone,links}
  notes TEXT,                                           -- my private notes about peer
  UNIQUE (user_id, peer_id, event_id)
);

CREATE TABLE blocks (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  blocked_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, blocked_id)
);
-- Every people-query MUST apply:
--   NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.user_id=:me AND b.blocked_id=x.user_id)
--                                        OR (b.user_id=x.user_id AND b.blocked_id=:me))

CREATE TABLE reports (
  id TEXT PRIMARY KEY, reporter_id TEXT NOT NULL REFERENCES users(id),
  subject_id TEXT NOT NULL REFERENCES users(id),
  reason TEXT NOT NULL CHECK (reason IN ('harassment','spam','impersonation','inappropriate_content','other')),
  detail TEXT, context JSONB,                           -- e.g. last 20 messages snapshot
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','actioned','dismissed')),
  actioned_by TEXT, actioned_at TIMESTAMPTZ
);

-- 5. Matching ----------------------------------------------------------------
CREATE TABLE match_scores (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_a TEXT NOT NULL, user_b TEXT NOT NULL, CHECK (user_a < user_b),
  score REAL NOT NULL,
  components JSONB NOT NULL,        -- see 05 §6: fits, intent bonus, boosts, matched pairs
  explanation TEXT,                 -- cached "why you two"
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, user_a, user_b)
);
CREATE INDEX ON match_scores (event_id, user_a, score DESC);
CREATE INDEX ON match_scores (event_id, user_b, score DESC);

CREATE TABLE match_feedback (       -- labeled examples for the learning loop
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL, user_id TEXT NOT NULL, peer_id TEXT NOT NULL,
  signal TEXT NOT NULL CHECK (signal IN
    ('feed_skip','wave_sent','wave_accepted','wave_not_now','chat_started',
     'chat_died','meet_confirmed')),
  components JSONB NOT NULL         -- frozen score components at signal time
);

-- 6. Announcements, analytics, AI audit ---------------------------------------
CREATE TABLE announcements (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  author_id TEXT NOT NULL REFERENCES users(id), body TEXT NOT NULL CHECK (char_length(body) <= 300)
);

CREATE TABLE analytics_events (
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, user_id TEXT, event_id TEXT,
  props JSONB NOT NULL DEFAULT '{}', at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON analytics_events (name, at);
CREATE INDEX ON analytics_events (event_id, name);

CREATE TABLE ai_calls (              -- audit + cost tracking for every LLM call
  id TEXT PRIMARY KEY, task TEXT NOT NULL,             -- prompt registry key (06 §3)
  user_id TEXT, event_id TEXT, model TEXT NOT NULL,
  input_tokens INT, output_tokens INT, cache_read_tokens INT,
  latency_ms INT, ok BOOL NOT NULL, error TEXT
);
CREATE INDEX ON ai_calls (task, created_at);

-- 7. v2: Office Hours & billing ------------------------------------------------
CREATE TABLE event_vips (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  approved_by TEXT NOT NULL, strikes INT NOT NULL DEFAULT 0,
  PRIMARY KEY (event_id, user_id)
);

CREATE TABLE office_hour_slots (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  host_user_id TEXT NOT NULL REFERENCES users(id),
  starts_at TIMESTAMPTZ NOT NULL, duration_min INT NOT NULL DEFAULT 15,
  price_minor INT NOT NULL, currency TEXT NOT NULL, charity BOOL NOT NULL DEFAULT false,
  meeting_point TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','booked','completed','cancelled'))
);

CREATE TABLE bookings (
  id TEXT PRIMARY KEY, slot_id TEXT NOT NULL REFERENCES office_hour_slots(id),
  attendee_id TEXT NOT NULL REFERENCES users(id),
  payment_ref TEXT NOT NULL,                            -- Paystack/Stripe reference
  status TEXT NOT NULL DEFAULT 'booked'
    CHECK (status IN ('booked','completed','no_show','refunded','disputed'))
);

-- Radar tokens live ONLY in Redis (see 07 §4); no SQL table by design:
--   radar:token:{token}        -> {user_id, event_id}     TTL 300s
--   radar:active:{event_id}    -> SET of user_id          member TTL via sorted-set timestamps
--   radar:sightings:{event}:{user} -> ZSET peer_user_id -> last_bucket_ts  TTL 120s
```

## Retention schedule (enforced by nightly job)

| Data | Retention |
|---|---|
| `auth_otps` | 24 h after expiry |
| Radar Redis keys | TTL ≤ 5 min; all keys for an event purged at `ends_at + 1h` |
| `checkins` zone rows | Aggregated into organizer stats at event end + 30 d, then deleted |
| `waves` with status `not_now`/`expired` | Row kept (dedupe constraint needs it); `card`/`note` nulled after 30 d |
| `messages` | 24 months, then deleted (policy shown in-app) |
| Soft-deleted users | PII hard-deleted after 30 d; messages become "Deleted user" |
| `ai_calls` | 90 d |
| `analytics_events` | 24 months |
