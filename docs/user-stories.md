# User Stories — AiNetwork

Grouped by epic. Priority: **P0** = v1 blocker, **P1** = v1.5, **P2** = v2.

## Epic 1 — Identity & Profile

| ID | Story | Priority |
|---|---|---|
| US-101 | As an attendee, I can sign up with phone/email OTP so my identity is verified once. | P0 |
| US-102 | As an attendee, I can build a profile (photo, role, company, skills, links, bio) so others know who I am. | P0 |
| US-103 | As an attendee, I can set per-event goals in plain language ("I want to meet fintech CTOs who raised Series A") and the AI converts them into structured targets I can edit. | P0 |
| US-104 | As an attendee, I can use a display persona per event (different name/photo) while remaining verified underneath, so I control my public identity. | P1 |
| US-105 | As an attendee, I can set my coarse home area (city/district picker, never GPS) visible only to accepted connections. | P2 |

**US-103 acceptance criteria:**
- Free text or voice note in → structured goal object out (intent, target filters, offer, priority).
- User sees the parsed goal and can edit every field before saving.
- Goals are per-event and expire at event end (user can carry them forward).

## Epic 2 — Events & Check-in

| ID | Story | Priority |
|---|---|---|
| US-201 | As an organizer, I can create an event (name, venue, dates, zones, capacity) and get a QR check-in kit. | P0 |
| US-202 | As an organizer, I can set gating: open entry, or apply-first (scan without approval is politely denied). | P0 |
| US-203 | As an attendee, I can browse/search events and see ones near my city, and apply/register. | P0 |
| US-204 | As an attendee, I scan the door QR and am checked in — this unlocks the event room for me. | P0 |
| US-205 | As an organizer, I see live attendance counts and can push announcements to all checked-in attendees. | P0 |
| US-206 | As an attendee, I can optionally scan session/room QRs so the organizer gets session-attendance analytics (never used for radar or my visible location). | P1 |
| US-207 | As an organizer, I can see session-level check-ins to know which talks filled up. | P1 |

## Epic 3 — Matching & Intros

| ID | Story | Priority |
|---|---|---|
| US-301 | As an attendee, I see a ranked match feed (top ~10) of checked-in attendees, each with a "why you two" explanation grounded in our actual goals. | P0 |
| US-302 | As an attendee, I can browse the full attendee directory (checked-in, visibility-on people only; I must be visible to browse). | P0 |
| US-303 | As an attendee, I tap "introduce me" and review an AI-drafted intro card before it's sent — nothing goes out without my approval. | P0 |
| US-304 | As a recipient, I get a warm intro card (who, why us, no location info) and can Accept, Not now (silent), or Maybe later. | P0 |
| US-305 | As a sender, I never learn whether a non-response was a decline — pending and declined look identical, and waves expire silently at event end. | P0 |
| US-306 | As a recipient who tapped Maybe later, I get the card resurfaced exactly once the next morning. | P0 |
| US-307 | As an attendee, matches get a boost when we attended the same session, and the shared session appears as an icebreaker. | P1 |
| US-308 | As an attendee, my feed always includes 1–2 "wildcard" interesting matches outside my stated goals. | P1 |

**US-301 acceptance criteria:**
- Score = geometric mean of two-way goal fit (one-sided matches rank low).
- "Why you two" cites real matched signals only (which ask met which offer); never invented.
- Feed excludes blocked users bidirectionally and respects visibility settings.

## Epic 4 — Chat & AI Wingman

| ID | Story | Priority |
|---|---|---|
| US-401 | As two matched attendees, we get a chat pre-seeded with context and 2–3 icebreakers so neither of us faces a blank screen. | P0 |
| US-402 | As an attendee, I can ask the wingman to draft/rewrite my message in a tone (formal, casual, warm, funny). | P0 |
| US-403 | As an attendee, I get reply suggestions when I'm stuck ("she mentioned fundraising — you could offer that VC intro"). | P0 |
| US-404 | As matched attendees, the app suggests a concrete meet: time + named meeting point ("Coffee point B, 15:30"). | P0 |
| US-405 | As attendees who meet in person, we tap-to-exchange contacts; this logs a confirmed meeting into both our CRMs and organizer analytics. | P0 |
| US-406 | As an attendee, I can record what I want to say as a voice note plus a target tone, and the AI shapes the message. | P2 |
| US-407 | As an attendee, non-native English speakers get the wingman's help sounding natural in a professional register. | P1 |

## Epic 5 — Radar ("Say hi")

| ID | Story | Priority |
|---|---|---|
| US-501 | As an attendee, I can turn on discovery per event (requires a face photo) and appear in the event-wide discoverable list — no map, no direction, no distances. This base layer needs no special hardware and always works. | P1 |
| US-502 | As an attendee, I can go ghost with one tap; while ghost I also cannot browse (reciprocity). | P1 |
| US-503 | As an attendee, I spot someone interesting, find them in the list by photo, and send a "say hi" — a structured intro card, never free text. | P1 |
| US-504 | As a recipient, the card says "also at [event]" — my proximity is revealed only *after* I accept. | P1 |
| US-508 | As an attendee, when I open the radar screen my phone quietly announces itself and listens over Bluetooth, so the list sorts nearest-first in coarse buckets — "right here" (a few steps) vs "in the area" — never exact distance or direction. | P1 |
| US-509 | As an attendee, my radar broadcast uses short-lived anonymous tokens and only runs while my radar screen is open (or moments after), so nobody can track me passively or across time. | P1 |
| US-505 | As an attendee, waves are rate-limited (~5/hour, one per person per event) and expire silently. | P1 |
| US-506 | As two attendees who waved at each other before either responded, we get an instant "you noticed each other" match. | P1 |
| US-507 | As an attendee, blocking someone removes us from each other's radar forever, across all future events. | P1 |

**US-508 acceptance criteria:**
- Signal strength maps to buckets server-side; raw strength/distance never reaches the client UI.
- "Right here" works when both people have the radar screen open (foreground Bluetooth) — designed as an active "I'm open to hellos" mode, not passive tracking.
- Someone the caller can physically see is reliably in the "right here" bucket; beyond that, precision is deliberately fuzzy.

## Epic 6 — Post-event & CRM

| ID | Story | Priority |
|---|---|---|
| US-601 | As an attendee, my chats and contacts are automatically grouped by the event where we met — zero manual filing. | P0 |
| US-602 | As an attendee, a contact card shows our full history ("met at DevCon Lagos Jul 2026; crossed paths at 2 other events"). | P1 |
| US-603 | As an attendee, the morning after an event I get a summary: people met, drafted follow-ups ready to approve. | P1 |
| US-604 | As an attendee, I get follow-up reminders ("DevCon ended 3 days ago — 2 people you haven't followed up with"). | P2 |
| US-605 | As an attendee, when connections and I are in the same city post-event, the app suggests a coffee meetup and drafts the group message. | P2 |
| US-606 | As an attendee registered for an upcoming event, I can see people from my city who are also going ("12 attendees coming from Lagos") and connect before the event — city-level info only, same double-opt-in intro cards as everywhere else. | P2 |
| US-607 | As an attendee, I can turn on travel mode ("I'm in Nairobi this week") so my accepted connections — and only them — in that city are notified and can suggest meeting up. | P2 |

## Epic 7 — Organizer & Monetization

| ID | Story | Priority |
|---|---|---|
| US-701 | As an organizer, I get a post-event report: check-ins, intros sent/accepted, confirmed meetings — numbers I can put in next year's sponsor deck. | P1 |
| US-702 | As an exhibitor, my booth QR lets attendees tap-to-exchange with my team, and I can export my lead list. | P1 |
| US-703 | As an organizer, I can sell sponsored meeting points and sponsor tiles inside the event app. | P2 |
| US-704 | As an organizer, I can charge for tickets in-app (Stripe/Paystack) with the platform taking a fee. | P2 |
| US-705 | As an organizer, I can pay per event on a tier based on attendee count. | P0 (manual invoicing OK for v1) |

## Epic 8 — Trust & Safety (cross-cutting, all P0)

| ID | Story |
|---|---|
| US-801 | As an attendee, I can block anyone; blocks are bidirectional, permanent, and cross-event. |
| US-802 | As an attendee, I can report a user/message; reports reach a moderation queue with context. |
| US-803 | As an attendee, first contact is always a structured card — there is no channel to send free text to someone who hasn't accepted me. |
| US-804 | As a user, my messages have a documented retention policy and I can export/delete my data. |
| US-805 | As an attendee, nothing about my precise location is ever stored — only event/session check-in timestamps and short-lived anonymous radar tokens, all expiring at event end. |

## Epic 9 — Office Hours (v2, all P2)

| ID | Story |
|---|---|
| US-901 | As an organizer-approved VIP (speaker, investor, notable guest), I can offer 15-min meeting slots with a price — or route proceeds to a charity I pick. |
| US-902 | As an attendee, I can browse the event's Office Hours section, book a slot, and pay in-app (Paystack/Stripe). |
| US-903 | As both parties, the meeting is confirmed by tap-to-exchange at the meeting point; an unconfirmed slot triggers the no-show/refund flow. |
| US-904 | As a platform, Office Hours listings never appear inside the match feed and never influence match ranking — it is a visibly separate section. |
| US-905 | As a platform, we take a 15–20% fee per completed booking; the VIP receives the rest (or their charity does). |

## Epic 10 — Attendee Premium (v2, all P2)

| ID | Story |
|---|---|
| US-1001 | As a premium attendee, I get advanced directory search and filters ("every fintech CTO at this event," filter by role/industry/stage/goals). Basic browsing stays free for everyone. |
| US-1002 | As a premium attendee, my wave limit is lifted (free tier keeps ~5/hour). |
| US-1003 | As a premium attendee, I can ask the wingman for a meeting brief before I meet someone: profile summary, their goals, shared context, suggested talking points. |
| US-1004 | As a premium attendee, I can see who viewed my profile. |
| US-1005 | As a platform, premium never buys ranking: no paid boosts in anyone's match feed, no queue-jumping on waves — premium is tools for yourself, never access to others. |

