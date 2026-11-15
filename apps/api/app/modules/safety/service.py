from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, outbox
from app.core.db.pagination import decode_cursor, paginate
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.modules.identity import public as identity
from app.modules.safety.models import Block, ModerationFlag, Report
from app.modules.safety.public import EVENT_SUSPENDED, raise_flag
from app.modules.safety.schemas import ReportIn


async def block(session: AsyncSession, me: str, user_id: str) -> None:
    """Permanent, cross-event, silent (01 §14.1). Every people query filters on this row
    from the next request on; nothing is sent to the blocked person."""
    if user_id == me:
        raise ValidationFailed("You cannot block yourself", code="block_self")
    await identity.get_card(session, user_id)  # 404 for unknown ids
    inserted = await session.execute(
        insert(Block).values(user_id=me, blocked_id=user_id).on_conflict_do_nothing()
    )
    if inserted.rowcount:  # type: ignore[attr-defined]
        outbox.emit(session, "safety.blocked", {"user_id": me, "blocked_id": user_id})
    await session.commit()


async def report(session: AsyncSession, me: str, data: ReportIn) -> None:
    if data.subject_id == me:
        raise ValidationFailed("You cannot report yourself", code="report_self")
    await identity.get_card(session, data.subject_id)
    rid = new_id("rpt")
    session.add(
        Report(
            id=rid,
            reporter_id=me,
            subject_id=data.subject_id,
            event_id=data.event_id,
            reason=data.reason,
            detail=data.detail,
        )
    )
    outbox.emit(
        session,
        "safety.report_created",
        {
            "report_id": rid,
            "reporter_id": me,
            "subject_id": data.subject_id,
            "conversation_id": data.conversation_id,
        },
    )
    await session.commit()


# --- moderation queue (staff) ------------------------------------------------------------


async def list_reports(
    session: AsyncSession, status: str, cursor: str | None, limit: int
) -> tuple[list[Report], str | None]:
    q = select(Report).where(Report.status == status)
    after = decode_cursor(cursor)
    if after:
        q = q.where(Report.id > str(after))
    rows = list((await session.execute(q.order_by(Report.id).limit(limit + 1))).scalars())
    return paginate(rows, limit, lambda r: r.id)


async def act_on_report(
    session: AsyncSession, staff_id: str, report_id: str, action: str
) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise NotFound
    if report.status != "open":
        raise Conflict("Report already handled", code="report_closed")
    if action == "ban":
        await identity.set_suspended(session, report.subject_id, True)
    elif action == "suspend_event":
        if report.event_id is None:
            raise ValidationFailed("This report has no event", code="report_no_event")
        await raise_flag(session, report.subject_id, report.event_id, EVENT_SUSPENDED)
    report.status = "dismissed" if action == "dismiss" else "actioned"
    report.action = action
    report.actioned_by = staff_id
    report.actioned_at = clock.now()
    outbox.emit(
        session,
        "safety.report_actioned",
        {
            "report_id": report.id,
            "subject_id": report.subject_id,
            "action": action,
            "staff_id": staff_id,
            "event_id": report.event_id,
        },
    )
    await session.commit()
    return report


async def list_flags(session: AsyncSession) -> list[ModerationFlag]:
    return list(
        (
            await session.execute(
                select(ModerationFlag)
                .where(ModerationFlag.resolved_at.is_(None))
                .order_by(ModerationFlag.created_at)
                .limit(200)
            )
        ).scalars()
    )


async def resolve_flag(session: AsyncSession, flag_id: str) -> None:
    flag = await session.get(ModerationFlag, flag_id)
    if flag is None:
        raise NotFound
    flag.resolved_at = clock.now()
    await session.commit()
