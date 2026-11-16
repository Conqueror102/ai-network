"""Waves: structured first contact with silent declines (01 §7, 00 §4).

Nothing in this module may tell a sender that they were declined, snoozed, held by an
inbox cap, expired or blocked. `sent_view` is the single place that renders a wave for
its sender, and it only knows "pending" and "accepted".
"""

from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, outbox, ratelimit
from app.core.db.pagination import decode_cursor, paginate
from app.core.errors import NotFound
from app.core.ids import new_id
from app.core.redis import get_redis, key
from app.modules.ai import public as ai
from app.modules.chat import public as chat
from app.modules.connections import public as connections
from app.modules.events import public as events
from app.modules.identity import public as identity
from app.modules.matching import public as matching
from app.modules.profiles import public as profiles
from app.modules.safety import public as safety
from app.modules.waves import errors
from app.modules.waves.models import Wave
from app.modules.waves.schemas import InboxWaveOut, SentWaveOut, WaveIn

log = structlog.get_logger()
WAVES_PER_HOUR = 5
INBOX_CAP = 50
DECLINE_STREAK = 10
SCREEN_FAILS = 3
OPEN = ("pending", "maybe_later")


async def _screen_note(session: AsyncSession, note: str, user_id: str, event_id: str) -> None:
    """Fail closed: a note that cannot be screened is not sent (06 §4.6)."""
    await ratelimit.hit("wave_note", user_id, limit=20, window_s=3600)
    rejected = ai.validators.contains_contact_details(note)
    if not rejected:
        try:
            verdict = await ai.screen(note, kind="wave_note", user_id=user_id, event_id=event_id)
        except ai.AiUnavailable as e:
            raise errors.NoteUnavailable from e
        rejected = not verdict.allow
    if rejected:
        r = get_redis()
        k = key("quota", "screenfail", event_id, user_id)
        fails = await r.incr(k)
        await r.expire(k, 24 * 3600)
        if fails >= SCREEN_FAILS:  # 01 §14.3: repeated screen failures pause sending
            await safety.raise_flag(session, user_id, event_id, safety.WAVE_PAUSE)
            await session.commit()
        raise errors.NoteRejected


async def _card(
    session: AsyncSession, event: events.EventInfo, sender: str, recipient: str, data: WaveIn
) -> dict[str, Any]:
    """The frozen intro card: who, why, and the optional note. Never proximity, never
    contact details."""
    sender_card = (await profiles.get_event_cards(session, event.id, [sender]))[sender]
    why = f"You're both at {event.name}."
    chips: list[str] = []
    if data.source == "match_feed":
        chips, text = await matching.match_context(session, event.id, recipient, sender)
        why = text or why
    return {
        "from": sender_card.model_dump(),
        "why": why,
        "matched_chips": chips,
        "note": data.note or None,
        "event_name": event.name,
    }


async def _inbox_count(session: AsyncSession, event_id: str, user_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Wave)
                .where(
                    Wave.event_id == event_id,
                    Wave.to_user == user_id,
                    Wave.status == "pending",
                    Wave.delivered_at.is_not(None),
                )
            )
        ).scalar_one()
    )


async def _accept(session: AsyncSession, wave: Wave) -> str:
    wave.status, wave.resolved_at = "accepted", clock.now()
    cid = await chat.open_conversation(
        session, wave.event_id, wave.from_user, wave.to_user, wave_id=wave.id
    )
    wave.conversation_id = cid
    await connections.ensure_pair(session, wave.event_id, wave.from_user, wave.to_user)
    await matching.record_signal(
        session, wave.event_id, wave.to_user, wave.from_user, "wave_accepted"
    )
    return cid


async def _reachable(session: AsyncSession, event_id: str, me: str, peer: str) -> bool:
    """Someone who switched off "open to meeting anyone" can only be waved at by a
    person the engine matched them with, or by someone they waved at first."""
    if await profiles.open_ids(session, event_id, [peer]):
        return True
    if await matching.in_feed(session, event_id, me, peer):
        return True
    waved_at_me = (
        await session.execute(
            select(Wave.id).where(
                Wave.event_id == event_id, Wave.from_user == peer, Wave.to_user == me
            )
        )
    ).first()
    return waved_at_me is not None


async def send(
    session: AsyncSession, event: events.EventInfo, me: str, premium: bool, data: WaveIn
) -> Wave:
    if data.to_user == me:
        raise errors.RecipientUnavailable
    if await profiles.visibility_of(session, event.id, me) is None:
        raise errors.ProfileRequired
    if await safety.has_open_flag(session, me, event.id, safety.WAVE_PAUSE):
        raise errors.WavesPaused
    if not await profiles.showable_ids(session, event.id, me, [data.to_user]):
        raise errors.RecipientUnavailable
    if not await _reachable(session, event.id, me, data.to_user):
        raise errors.RecipientUnavailable  # same answer as "not here": nothing to probe
    existing = (
        await session.execute(
            select(Wave.id).where(
                Wave.event_id == event.id, Wave.from_user == me, Wave.to_user == data.to_user
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise errors.WaveAlreadyExists
    if data.note:
        await _screen_note(session, data.note, me, event.id)
    if not premium:  # a pacing limit, not a ranking signal
        await ratelimit.hit(
            "waves",
            f"{event.id}:{me}",
            limit=WAVES_PER_HOUR,
            window_s=3600,
            code="wave_limit_reached",
        )

    reverse = (
        await session.execute(
            select(Wave)
            .where(
                Wave.event_id == event.id,
                Wave.from_user == data.to_user,
                Wave.to_user == me,
                Wave.status.in_((*OPEN, "not_now")),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    wave = Wave(
        id=new_id("wav"),
        event_id=event.id,
        from_user=me,
        to_user=data.to_user,
        source=data.source,
        card=await _card(session, event, me, data.to_user, data),
        note=data.note or None,
    )
    session.add(wave)
    try:
        await session.flush()
    except IntegrityError as e:  # two taps racing
        await session.rollback()
        raise errors.WaveAlreadyExists from e
    await matching.record_signal(session, event.id, me, data.to_user, "wave_sent")

    if reverse is not None:
        # They reached out to me first: sending back is a yes from both sides (01 §7.5).
        wave.delivered_at = clock.now()
        cid = await _accept(session, reverse)
        wave.status, wave.resolved_at, wave.conversation_id = "accepted", clock.now(), cid
        outbox.emit(
            session,
            "waves.mutual",
            {"event_id": event.id, "conversation_id": cid, "user_ids": [me, data.to_user]},
        )
    elif await _inbox_count(session, event.id, data.to_user) < INBOX_CAP:
        wave.delivered_at = clock.now()
        outbox.emit(
            session,
            "waves.received",
            {"wave_id": wave.id, "event_id": event.id, "to_user": data.to_user},
        )
    # else: held until the recipient frees a slot. The sender cannot tell.
    await session.commit()
    return wave


async def _deliver_next(session: AsyncSession, event_id: str, user_id: str) -> None:
    held = (
        await session.execute(
            select(Wave)
            .where(
                Wave.event_id == event_id,
                Wave.to_user == user_id,
                Wave.status == "pending",
                Wave.delivered_at.is_(None),
            )
            .order_by(Wave.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if held is not None and await _inbox_count(session, event_id, user_id) < INBOX_CAP:
        held.delivered_at = clock.now()
        outbox.emit(
            session,
            "waves.received",
            {"wave_id": held.id, "event_id": event_id, "to_user": user_id},
        )


async def respond(session: AsyncSession, me: str, wave_id: str, action: str) -> str | None:
    wave = (
        await session.execute(select(Wave).where(Wave.id == wave_id).with_for_update())
    ).scalar_one_or_none()
    if wave is None or wave.to_user != me or wave.delivered_at is None:
        raise NotFound
    if await safety.is_blocked_pair(session, me, wave.from_user):
        raise NotFound
    answerable = wave.status == "pending" or (wave.status == "maybe_later" and wave.resurfaced)
    if not answerable:
        raise errors.WaveNotPending
    cid: str | None = None
    if action == "accept":
        cid = await _accept(session, wave)
        outbox.emit(
            session,
            "waves.accepted",
            {
                "wave_id": wave.id,
                "event_id": wave.event_id,
                "conversation_id": cid,
                "from_user": wave.from_user,
                "to_user": me,
            },
        )
    elif action == "maybe_later" and not wave.resurfaced:
        wave.status, wave.resolved_at = "maybe_later", clock.now()
    else:
        # "not now", or a second snooze. Silent: no event, no push, no receipt.
        wave.status, wave.resolved_at = "not_now", clock.now()
        await matching.record_signal(session, wave.event_id, me, wave.from_user, "wave_not_now")
        declines = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Wave)
                    .where(
                        Wave.event_id == wave.event_id,
                        Wave.from_user == wave.from_user,
                        Wave.status == "not_now",
                    )
                )
            ).scalar_one()
        )
        if declines > DECLINE_STREAK:  # 01 §14.3
            await safety.raise_flag(session, wave.from_user, wave.event_id, safety.WAVE_PAUSE)
    await session.flush()
    await _deliver_next(session, wave.event_id, me)
    await session.commit()
    return cid


# --- views -----------------------------------------------------------------------------


async def sent_view(session: AsyncSession, waves: list[Wave]) -> list[SentWaveOut]:
    by_event: dict[str, list[str]] = {}
    for w in waves:
        by_event.setdefault(w.event_id, []).append(w.to_user)
    cards = {
        eid: await profiles.get_event_cards(session, eid, ids) for eid, ids in by_event.items()
    }
    return [
        SentWaveOut(
            id=w.id,
            event_id=w.event_id,
            to=cards[w.event_id][w.to_user],
            source=w.source,
            note=w.note,
            status="accepted" if w.status == "accepted" else "pending",
            conversation_id=w.conversation_id if w.status == "accepted" else None,
            created_at=w.created_at,
        )
        for w in waves
    ]


async def list_sent(
    session: AsyncSession, event_id: str, me: str, cursor: str | None, limit: int
) -> tuple[list[SentWaveOut], str | None]:
    q = select(Wave).where(Wave.event_id == event_id, Wave.from_user == me, _not_i_blocked(me))
    after = decode_cursor(cursor)
    if after:
        q = q.where(Wave.id < str(after))
    rows = list((await session.execute(q.order_by(Wave.id.desc()).limit(limit + 1))).scalars())
    rows, nxt = paginate(rows, limit, lambda w: w.id)
    return await sent_view(session, rows), nxt


def _not_i_blocked(me: str) -> Any:
    """Hide waves to people I blocked. Waves to people who blocked ME stay visible and
    "pending": removing them would reveal the block."""
    return safety.i_have_not_blocked(me, Wave.to_user)


async def list_inbox(
    session: AsyncSession, event_id: str, me: str, cursor: str | None, limit: int
) -> tuple[list[InboxWaveOut], str | None]:
    q = select(Wave).where(
        Wave.event_id == event_id,
        Wave.to_user == me,
        Wave.delivered_at.is_not(None),
        or_(Wave.status == "pending", and_(Wave.status == "maybe_later", Wave.resurfaced)),
        safety.not_blocked(me, Wave.from_user),
    )
    after = decode_cursor(cursor)
    if after:
        q = q.where(Wave.id < str(after))
    rows = list((await session.execute(q.order_by(Wave.id.desc()).limit(limit + 1))).scalars())
    rows, nxt = paginate(rows, limit, lambda w: w.id)
    senders = await identity.get_cards(session, [w.from_user for w in rows])
    return [
        InboxWaveOut(
            id=w.id,
            event_id=w.event_id,
            card=w.card,
            source=w.source,
            resurfaced=w.resurfaced,
            created_at=w.created_at,
        )
        for w in rows
        if senders[w.from_user].active
    ], nxt


# --- jobs' work ------------------------------------------------------------------------


async def expire(session: AsyncSession, event_ids: list[str]) -> int:
    if not event_ids:
        return 0
    result = await session.execute(
        update(Wave)
        .where(Wave.event_id.in_(event_ids), Wave.status.in_(OPEN))
        .values(status="expired", resolved_at=clock.now())
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


async def resurface(session: AsyncSession, event_id: str, before: Any) -> int:
    """Bring snoozed waves back once (01 §7.3). `before`: snoozed earlier than this."""
    rows = list(
        (
            await session.execute(
                select(Wave)
                .where(
                    Wave.event_id == event_id,
                    Wave.status == "maybe_later",
                    Wave.resurfaced.is_(False),
                    Wave.resolved_at < before,
                    ~exists().where(safety.block_between(Wave.from_user, Wave.to_user)),
                )
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for w in rows:
        w.resurfaced = True
        outbox.emit(
            session,
            "waves.resurfaced",
            {
                "wave_id": w.id,
                "event_id": event_id,
                "to_user": w.to_user,
                "from_user": w.from_user,
            },
        )
    return len(rows)


async def counts(session: AsyncSession, event_id: str) -> dict[str, int]:
    """Aggregates for organizer reports. Declines are deliberately not broken out."""
    rows = dict(
        (
            await session.execute(
                select(Wave.status, func.count())
                .where(Wave.event_id == event_id)
                .group_by(Wave.status)
            )
        ).all()
    )
    return {"sent": sum(rows.values()), "accepted": rows.get("accepted", 0)}


async def scrub_resolved(session: AsyncSession, before: datetime) -> int:
    res = await session.execute(
        update(Wave)
        .where(
            Wave.status.in_(("not_now", "expired")),
            Wave.resolved_at < before,
            Wave.card != {},
        )
        .values(card={}, note=None)
    )
    return res.rowcount or 0  # type: ignore[attr-defined]


async def forget_sender(session: AsyncSession, user_id: str) -> None:
    """A purged account's frozen cards and notes go, whatever the wave's status."""
    await session.execute(update(Wave).where(Wave.from_user == user_id).values(card={}, note=None))


async def export_user(session: AsyncSession, user_id: str) -> dict[str, Any]:
    """What this user sent, and only the waves they answered or still see. Declines by
    other people are not theirs to learn, so sent waves show no outcome beyond
    pending or accepted (same masking as the Sent tab)."""
    sent = (await session.scalars(select(Wave).where(Wave.from_user == user_id))).all()
    received = (
        await session.scalars(
            select(Wave).where(Wave.to_user == user_id, Wave.delivered_at.is_not(None))
        )
    ).all()
    return {
        "sent": [
            {
                "id": w.id,
                "event_id": w.event_id,
                "to_user": w.to_user,
                "note": w.note,
                "status": "accepted" if w.status == "accepted" else "pending",
                "created_at": w.created_at.isoformat(),
            }
            for w in sent
        ],
        "received": [
            {
                "id": w.id,
                "event_id": w.event_id,
                "from_user": w.from_user,
                "note": w.note,
                "status": w.status,
                "created_at": w.created_at.isoformat(),
            }
            for w in received
        ],
    }
