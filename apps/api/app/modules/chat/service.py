"""1:1 chat born from an accepted wave (01 §8). Bodies are encrypted at rest."""

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import DateTime, and_, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, jobs, outbox
from app.core.db.pagination import decode_cursor, encode_cursor, paginate
from app.core.ids import new_id
from app.modules.chat import errors
from app.modules.chat.models import Conversation, Message
from app.modules.chat.schemas import (
    ConversationOut,
    MeetIn,
    MeetSpotOut,
    MeetStatusIn,
    MessageIn,
    MessageOut,
)
from app.modules.events import public as events
from app.modules.identity import public as identity
from app.modules.matching import public as matching
from app.modules.profiles import public as profiles
from app.modules.realtime import public as realtime
from app.modules.safety import public as safety

MEET_REMINDER_BEFORE = timedelta(minutes=10)


def peer_of(conv: Conversation, me: str) -> str:
    return conv.user_b if conv.user_a == me else conv.user_a


def message_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        conversation_id=m.conversation_id,
        sender_id=m.sender_id,
        kind=m.kind,  # type: ignore[arg-type]
        body=m.body,
        payload=m.payload,
        delivered_at=m.delivered_at,
        read_at=m.read_at,
        created_at=m.created_at,
    )


async def get_for(
    session: AsyncSession, conversation_id: str, me: str, *, lock: bool = False
) -> Conversation:
    """The conversation, if `me` is in it and the pair is not blocked. One 404 for
    everything else, so ids cannot be probed (IDOR) and a block is not revealed."""
    q = select(Conversation).where(Conversation.id == conversation_id)
    conv = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if conv is None or me not in (conv.user_a, conv.user_b):
        raise errors.ConversationNotFound
    if await safety.is_blocked_pair(session, conv.user_a, conv.user_b):
        raise errors.ConversationNotFound
    return conv


async def list_conversations(
    session: AsyncSession, me: str, cursor: str | None, limit: int
) -> tuple[list[ConversationOut], str | None]:
    peer = func.coalesce(
        func.nullif(Conversation.user_a, me), Conversation.user_b
    )  # the other participant
    sort = func.coalesce(Conversation.last_message_at, Conversation.created_at)
    q = select(Conversation).where(
        or_(Conversation.user_a == me, Conversation.user_b == me), safety.not_blocked(me, peer)
    )
    after = decode_cursor(cursor)
    if after:
        ts, cid = datetime.fromisoformat(after[0]), str(after[1])
        q = q.where(or_(sort < ts, and_(sort == ts, Conversation.id < cid)))
    rows = list(
        (
            await session.execute(q.order_by(sort.desc(), Conversation.id.desc()).limit(limit + 1))
        ).scalars()
    )
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        tail = rows[-1]
        nxt = encode_cursor([(tail.last_message_at or tail.created_at).isoformat(), tail.id])
    if not rows:
        return [], None
    ids = [c.id for c in rows]
    # last message per conversation, and unread counts, in two grouped queries (no N+1)
    last_ids = (
        select(func.max(Message.id))
        .where(Message.conversation_id.in_(ids))
        .group_by(Message.conversation_id)
    )
    last = {
        m.conversation_id: m
        for m in (await session.execute(select(Message).where(Message.id.in_(last_ids)))).scalars()
    }
    unread = dict(
        (
            await session.execute(
                select(Message.conversation_id, func.count())
                .where(
                    Message.conversation_id.in_(ids),
                    Message.sender_id.is_not(None),
                    Message.sender_id != me,
                    Message.read_at.is_(None),
                )
                .group_by(Message.conversation_id)
            )
        ).all()
    )
    by_event: dict[str, list[str]] = {}
    for c in rows:
        by_event.setdefault(c.event_id, []).append(peer_of(c, me))
    cards = {e: await profiles.get_event_cards(session, e, p) for e, p in by_event.items()}
    return [
        ConversationOut(
            id=c.id,
            event_id=c.event_id,
            peer=cards[c.event_id][peer_of(c, me)],
            last_message=message_out(last[c.id]) if c.id in last else None,
            last_message_at=c.last_message_at,
            unread_count=unread.get(c.id, 0),
            created_at=c.created_at,
        )
        for c in rows
    ], nxt


async def list_messages(
    session: AsyncSession, conversation_id: str, me: str, cursor: str | None, limit: int
) -> tuple[list[MessageOut], str | None]:
    conv = await get_for(session, conversation_id, me)
    q = select(Message).where(Message.conversation_id == conv.id)
    after = decode_cursor(cursor)
    if after:
        q = q.where(Message.id < str(after))
    rows = list((await session.execute(q.order_by(Message.id.desc()).limit(limit + 1))).scalars())
    rows, nxt = paginate(rows, limit, lambda m: m.id)
    # fetching is delivery: single tick for everything the peer sent that I now hold
    pending = [m for m in rows if m.sender_id not in (None, me) and m.delivered_at is None]
    if pending:
        now = clock.now()
        for m in pending:
            m.delivered_at = now
        await session.commit()
    return [message_out(m) for m in rows], nxt


async def _add(
    session: AsyncSession,
    conv: Conversation,
    *,
    sender_id: str | None,
    kind: str,
    body: str,
    payload: dict[str, Any] | None = None,
    ai_assisted: bool = False,
) -> Message:
    now = clock.now()
    msg = Message(
        id=new_id("msg"),
        conversation_id=conv.id,
        sender_id=sender_id,
        kind=kind,
        body=body,
        payload=payload,
        ai_assisted=ai_assisted,
        created_at=now,
    )
    session.add(msg)
    conv.last_message_at = now
    return msg


async def _fan_out(conv: Conversation, msg: Message, *, to: list[str]) -> None:
    out = message_out(msg).model_dump(mode="json")
    for user_id in to:
        await realtime.publish_user(user_id, "message.new", out)


async def send_message(
    session: AsyncSession, conversation_id: str, me: str, data: MessageIn
) -> MessageOut:
    conv = await get_for(session, conversation_id, me, lock=True)
    peer = peer_of(conv, me)
    if not (await identity.get_card(session, peer)).active:
        raise errors.ConversationNotFound
    first = (
        await session.execute(
            select(Message.id)
            .where(Message.conversation_id == conv.id, Message.kind == "text")
            .limit(1)
        )
    ).first() is None
    msg = await _add(
        session, conv, sender_id=me, kind="text", body=data.body, ai_assisted=data.ai_assisted
    )
    if await realtime.is_online(peer):
        msg.delivered_at = msg.created_at
    if first:
        await matching.record_signal(session, conv.event_id, me, peer, "chat_started")
    # The outbox row carries ids only: message text never sits in plaintext outside
    # the encrypted column.
    outbox.emit(
        session,
        "chat.message_created",
        {
            "conversation_id": conv.id,
            "message_id": msg.id,
            "event_id": conv.event_id,
            "from_user": me,
            "to_user": peer,
        },
    )
    await session.commit()
    await _fan_out(conv, msg, to=[peer])
    return message_out(msg)


async def mark_read(session: AsyncSession, conversation_id: str, me: str, last_id: str) -> None:
    conv = await get_for(session, conversation_id, me, lock=True)
    exists_ = (
        await session.execute(
            select(Message.id).where(Message.id == last_id, Message.conversation_id == conv.id)
        )
    ).scalar_one_or_none()
    if exists_ is None:
        raise errors.ConversationNotFound
    mine_is_a = conv.user_a == me
    current = conv.read_a if mine_is_a else conv.read_b
    if current is not None and current >= last_id:
        return
    if mine_is_a:
        conv.read_a = last_id
    else:
        conv.read_b = last_id
    now = clock.now()
    await session.execute(
        update(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.id <= last_id,
            Message.sender_id != me,
            Message.read_at.is_(None),
        )
        .values(read_at=now, delivered_at=func.coalesce(Message.delivered_at, now))
    )
    await session.commit()
    await realtime.publish_user(
        peer_of(conv, me),
        "message.read",
        {"conversation_id": conv.id, "last_message_id": last_id},
    )


# --- meet planner (01 §8.6) --------------------------------------------------------------


MEET_SLOT_WINDOW = timedelta(minutes=30)  # meetings this close in time share a spot
ARRIVE_OPENS_BEFORE = timedelta(minutes=30)
ARRIVE_CLOSES_AFTER = timedelta(hours=1)


def place_of(payload: dict[str, Any]) -> str:
    """ "M3 · Coffee stand" for a numbered spot, the plain name for older proposals."""
    code = payload.get("spot_code")
    return f"{code} · {payload['meeting_point']}" if code else str(payload["meeting_point"])


def _busy_level(n: int) -> Literal["quiet", "some", "busy"]:
    return "quiet" if n == 0 else "some" if n <= 2 else "busy"


async def meet_spots(
    session: AsyncSession, event_id: str, at: datetime | None
) -> list[MeetSpotOut]:
    """The event's numbered spots with how busy each is around `at`, and one suggestion:
    the quietest. Only a coarse level leaves the server, so nobody can tell who is
    meeting where (no location leak)."""
    spots = await events.active_spots(session, event_id)
    if not spots:
        return []
    when = at or clock.now()
    meet_at = cast(Message.payload["at"].astext, DateTime(timezone=True))
    spot_id = Message.payload["spot_id"].astext
    counts = Counter(
        (
            await session.execute(
                select(spot_id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.event_id == event_id,
                    Message.kind == "meet_proposal",
                    Message.payload["status"].astext.in_(("proposed", "accepted")),
                    spot_id.in_([s.id for s in spots]),
                    meet_at.between(when - MEET_SLOT_WINDOW, when + MEET_SLOT_WINDOW),
                )
                .limit(2000)
            )
        ).scalars()
    )
    best = min(spots, key=lambda s: (counts.get(s.id, 0), s.number))
    return [
        MeetSpotOut(
            id=s.id,
            number=s.number,
            code=s.code,
            label=s.label,
            hint=s.hint,
            busy=_busy_level(counts.get(s.id, 0)),
            suggested=s.id == best.id,
        )
        for s in spots
    ]


async def propose_meet(
    session: AsyncSession, conversation_id: str, me: str, data: MeetIn
) -> MessageOut:
    conv = await get_for(session, conversation_id, me, lock=True)
    event = await events.get_info(session, conv.event_id)
    now = clock.now()
    at = data.at
    spot = next(
        (
            s
            for s in await events.active_spots(session, conv.event_id)
            if s.id == data.spot_id or s.label == data.meeting_point
        ),
        None,
    )
    if (
        spot is None
        or at is None
        or at.tzinfo is None
        or at <= now
        or at > max(event.ends_at, now) + timedelta(hours=2)
        or at.minute % 15
        or at.second
    ):
        raise errors.MeetInvalid
    payload: dict[str, Any] = {
        "meeting_point": spot.label,
        "spot_id": spot.id,
        "spot_code": spot.code,
        "spot_hint": spot.hint,
        "at": at.isoformat(),
        "status": "proposed",
    }
    if data.spot_me:
        payload["spot_me"] = {me: data.spot_me}
    msg = await _add(
        session,
        conv,
        sender_id=me,
        kind="meet_proposal",
        body=f"Meet at {spot.place}?",
        payload=payload,
    )
    outbox.emit(
        session,
        "chat.message_created",
        {
            "conversation_id": conv.id,
            "message_id": msg.id,
            "event_id": conv.event_id,
            "from_user": me,
            "to_user": peer_of(conv, me),
        },
    )
    await session.commit()
    await _fan_out(conv, msg, to=[peer_of(conv, me)])
    return message_out(msg)


async def _proposal(session: AsyncSession, conv: Conversation, message_id: str) -> Message:
    proposal = await session.get(Message, message_id)
    if proposal is None or proposal.conversation_id != conv.id or proposal.kind != "meet_proposal":
        raise errors.ConversationNotFound
    return proposal


async def accept_meet(
    session: AsyncSession, conversation_id: str, me: str, message_id: str, spot_me: str | None
) -> MessageOut:
    conv = await get_for(session, conversation_id, me, lock=True)
    proposal = await _proposal(session, conv, message_id)
    if proposal.sender_id == me:  # only the other person can accept
        raise errors.ConversationNotFound
    payload = dict(proposal.payload or {})
    at = datetime.fromisoformat(payload["at"])
    if payload.get("status") != "proposed" or at <= clock.now():
        raise errors.MeetNotOpen
    payload = {**payload, "status": "accepted", "accepted_by": me}
    if spot_me:
        payload["spot_me"] = {**payload.get("spot_me", {}), me: spot_me}
    proposal.payload = payload
    peer = peer_of(conv, me)
    place = place_of(payload)
    msg = await _add(
        session,
        conv,
        sender_id=None,
        kind="system",
        body=f"Meeting confirmed: {place}",
        payload={
            "meet_message_id": proposal.id,
            "meeting_point": payload["meeting_point"],
            "spot_code": payload.get("spot_code"),
            "at": payload["at"],
        },
    )
    await matching.record_signal(session, conv.event_id, me, peer, "meet_confirmed")
    outbox.emit(
        session,
        "chat.meet_confirmed",
        {
            "conversation_id": conv.id,
            "event_id": conv.event_id,
            "user_ids": [conv.user_a, conv.user_b],
            "meeting_point": place,
            "at": payload["at"],
        },
    )
    await session.commit()
    delay = (at - MEET_REMINDER_BEFORE - clock.now()).total_seconds()
    await jobs.enqueue(
        "chat.meet_reminder", proposal.id, job_id=f"meet:{proposal.id}", defer_s=max(0.0, delay)
    )
    await _fan_out(conv, msg, to=[conv.user_a, conv.user_b])
    await _meet_updated(conv, proposal)
    return message_out(msg)


async def _meet_updated(conv: Conversation, proposal: Message) -> None:
    """Both phones redraw the meet-up card (status, "how to spot me", who has arrived)."""
    out = message_out(proposal).model_dump(mode="json")
    for user_id in (conv.user_a, conv.user_b):
        await realtime.publish_user(user_id, "meet.updated", out)


async def meet_status(
    session: AsyncSession, conversation_id: str, me: str, message_id: str, data: MeetStatusIn
) -> MessageOut:
    """Two things a person can say about their own meet-up: "this is how to spot me" and
    "I'm here". Both are chosen by the person, for this one meeting, and reach only the
    other person in the chat; nothing here tracks or infers a location."""
    conv = await get_for(session, conversation_id, me, lock=True)
    proposal = await _proposal(session, conv, message_id)
    payload = dict(proposal.payload or {})
    at = datetime.fromisoformat(payload["at"])
    now = clock.now()
    status = payload.get("status")
    if status not in ("proposed", "accepted") or now > at + ARRIVE_CLOSES_AFTER:
        raise errors.MeetNotOpen
    newly_arrived = False
    if data.spot_me:
        payload["spot_me"] = {**payload.get("spot_me", {}), me: data.spot_me}
    if data.arrived:
        if status != "accepted" or now < at - ARRIVE_OPENS_BEFORE:
            raise errors.MeetNotNow
        arrived = dict(payload.get("arrived", {}))
        if me not in arrived:  # a second tap changes nothing and pings nobody
            arrived[me] = now.isoformat()
            payload["arrived"] = arrived
            newly_arrived = True
    if payload == proposal.payload:
        return message_out(proposal)
    proposal.payload = payload
    if newly_arrived:
        outbox.emit(
            session,
            "chat.meet_arrived",
            {
                "conversation_id": conv.id,
                "event_id": conv.event_id,
                "from_user": me,
                "to_user": peer_of(conv, me),
                "meeting_point": place_of(payload),
                "has_spot_me": me in payload.get("spot_me", {}),
            },
        )
    await session.commit()
    await _meet_updated(conv, proposal)
    return message_out(proposal)


# --- used by other modules ---------------------------------------------------------------


async def recent_messages(
    session: AsyncSession, conversation_id: str, me: str, limit: int = 10
) -> tuple[Conversation, list[Message]]:
    conv = await get_for(session, conversation_id, me)
    rows = list(
        (
            await session.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id, Message.kind.in_(("text", "meet_proposal"))
                )
                .order_by(Message.id.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return conv, rows[::-1]
