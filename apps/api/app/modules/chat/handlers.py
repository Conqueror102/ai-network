from typing import Any

from sqlalchemy import select

from app.core import jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.chat.models import Conversation, Message
from app.modules.safety import public as safety


@outbox.subscribe("chat.conversation_created")
async def seed_icebreakers(payload: dict[str, Any]) -> None:
    cid = payload["conversation_id"]
    await jobs.enqueue("chat.icebreakers", cid, job_id=f"ice:{cid}")


@outbox.subscribe("safety.report_created")
async def attach_messages(payload: dict[str, Any]) -> None:
    """A report filed from a chat carries its last 20 messages (01 §14.2). Only if the
    reporter is in that conversation and the subject is the other person."""
    cid = payload.get("conversation_id")
    if not cid:
        return
    async with UnitOfWork() as session:
        conv = await session.get(Conversation, cid)
        pair = {payload["reporter_id"], payload["subject_id"]}
        if conv is None or {conv.user_a, conv.user_b} != pair:
            return
        rows = list(
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == cid)
                    .order_by(Message.id.desc())
                    .limit(20)
                )
            ).scalars()
        )
        await safety.attach_report_context(
            session,
            payload["report_id"],
            payload["reporter_id"],
            {
                "conversation_id": cid,
                "messages": [
                    {
                        "id": m.id,
                        "sender_id": m.sender_id,
                        "kind": m.kind,
                        "body": m.body,
                        "at": m.created_at.isoformat(),
                    }
                    for m in rows[::-1]
                ],
            },
        )
