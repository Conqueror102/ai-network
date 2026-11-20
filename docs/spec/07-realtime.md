# 07 — Realtime & Notifications

## 1. WebSocket protocol

- Endpoint: `wss://api.<domain>/v1/ws?ticket=<ws_ticket>`. The client first calls `POST /v1/ws/ticket` (authenticated) to get a **single-use ticket valid 30 s** (stored in Redis, deleted on use), so the long-lived access JWT never appears in URLs or proxy logs. Connection is bound to the ticket's user; dropped when that user's access token would expire → client fetches a new ticket and reconnects.
- One connection per app instance. Server: FastAPI WS endpoint; fan-out via Redis pub/sub so any API instance can deliver to any socket.
- Envelope (server→client):
```json
{"id": "evt_ulid", "type": "message.new", "ts": "2026-07-14T10:00:00Z", "payload": {...}}
```
- Client→server messages: only `{"type": "ping"}` (keepalive 25 s) and `{"type": "ack", "id": ...}` (optional). All mutations go over REST — WS is delivery-only. This keeps the protocol trivial and REST the single source of truth.

### Event types

| type | payload | audience |
|---|---|---|
| `message.new` | Message | conversation peer |
| `message.read` | {conversation_id, last_message_id} | peer |
| `meet.nearby` | {conversation_id, meet_message_id, distance_m, direction, rough, age_s}: never coordinates | the other person in a meet-up, only while both share |
| `meet.updated` | the meet_proposal Message (status, `spot_me`, `arrived`) | both |
| `wave.received` | {wave_id} (client fetches card via REST) | recipient |
| `wave.accepted` | {wave_id, conversation_id} | sender |
| `wave.mutual` | {conversation_id, peer_card} | both |
| `conversation.created` | {conversation_id} | both |
| `matches.updated` | {event_id} | user |
| `connection.confirmed` | {connection_id, peer_card} | both |
| `announcement.new` | Announcement | all checked-in at event |
| `event.stats` | {checked_in, per_hour[]} | organizer dashboard topic |

### Subscriptions & delivery semantics
- Server auto-subscribes the socket to: `user:{id}` always; `event:{id}:attendee` while checked into a live event; organizers additionally to `event:{id}:stats` from the dashboard.
- Delivery is **at-most-once over WS, with REST as source of truth**: clients must reconcile on reconnect/foreground by refetching (`/conversations`, `/waves/inbox`, `/matches`). Envelope `id` (ULID) enables client-side dedupe. No server-side replay buffer in v1 — reconcile-on-reconnect is simpler and sufficient.
- Redis channels: `ws:user:{id}`, `ws:event:{id}:attendee`, `ws:event:{id}:stats`. Message = full envelope JSON.

## 2. Push notification catalogue (Expo)

All pushes deep-link (`ainet://...`). Collapse keys prevent stacking spam.

| Trigger | Title/body pattern | Deep link | Throttle |
|---|---|---|---|
| Wave received | "Someone at {event} wants to meet you" (no name — curiosity + privacy) | waves inbox | collapse per event |
| Wave accepted | "{name} accepted your intro 🎉" | conversation | — |
| Mutual wave | "You and {name} noticed each other" | conversation | — |
| New message | "{name}: {preview 60 chars}" | conversation | collapse per conversation |
| Maybe-later resurface | "Still want to connect with {name} from {event}?" | wave card | once ever |
| Meet reminder | "Meeting {name} at {point} in 10 min" | conversation | — |
| Application decided | "You're in! {event}" / "Update on your application" | event | — |
| Announcement | "{event}: {body 80}" | event room | server limit 1/10 min |
| Morning-after | "Your {event} wrap-up is ready" | summary screen | once |
| Photo rejected | "We couldn't approve your photo" | profile | — |

Quiet hours: no non-urgent pushes 22:00–08:00 recipient-local (meet reminders exempt). Notification preferences: per-category toggles under settings; server enforces.

## 3. Delivery pipeline

`notify(user_id, category, payload)` service: (1) WS attempt to `ws:user:{id}`; (2) if no active socket OR category is push-always (wave, message when backgrounded) → Expo push via batched sender worker (chunks of 100, receipts checked; `DeviceNotRegistered` → device row deleted). All notifications also written to `notifications` inbox table [v1.5 in-app notification center].

## 4. Radar presence (Redis, authoritative)

```
radar:token:{token}          STRING  {user_id, event_id}         TTL 300
radar:active:{event_id}      ZSET    user_id -> last_active_ts    (trim > 30 min)
radar:seen:{event}:{user}    ZSET    peer_id -> ts of last right_here  TTL 120
```
Sightings request: resolve tokens (pipelined GETs) → filter mutual-discoverable + not-blocked (cached per-user sets, 60 s) → bucket by RSSI (server constant, per 01 §9.4) → update `radar:seen` → respond `{user_id: bucket}`. p95 target < 150 ms.
