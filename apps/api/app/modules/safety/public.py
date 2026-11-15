"""Safety's public surface. Every people-returning query in every module must apply
`not_blocked(...)` or `blocked_ids(...)` (00 §4 invariant 5)."""

from typing import Any

from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import Block, ModerationFlag


def not_blocked(me: str, other_user_column: Any) -> ColumnElement[bool]:
    """SQL predicate: no block exists between `me` and the row's user, in either direction."""
    return ~exists().where(
        or_(
            and_(Block.user_id == me, Block.blocked_id == other_user_column),
            and_(Block.user_id == other_user_column, Block.blocked_id == me),
        )
    )


def i_have_not_blocked(me: str, other_user_column: Any) -> ColumnElement[bool]:
    """One-directional: true unless `me` blocked the row's user. For views where hiding
    rows in the other direction would reveal that the viewer was blocked."""
    return ~exists().where(and_(Block.user_id == me, Block.blocked_id == other_user_column))


def block_between(col_a: Any, col_b: Any) -> ColumnElement[bool]:
    """Correlated predicate for `exists().where(...)`: a block either way between two
    user columns of the outer row."""
    return or_(
        and_(Block.user_id == col_a, Block.blocked_id == col_b),
        and_(Block.user_id == col_b, Block.blocked_id == col_a),
    )


async def blocked_ids(session: AsyncSession, me: str) -> set[str]:
    """Everyone `me` blocked or was blocked by."""
    rows = (
        await session.execute(
            select(Block.user_id, Block.blocked_id).where(
                or_(Block.user_id == me, Block.blocked_id == me)
            )
        )
    ).all()
    return {b if a == me else a for a, b in rows}


async def is_blocked_pair(session: AsyncSession, a: str, b: str) -> bool:
    return (
        await session.execute(
            select(
                exists().where(
                    or_(
                        and_(Block.user_id == a, Block.blocked_id == b),
                        and_(Block.user_id == b, Block.blocked_id == a),
                    )
                )
            )
        )
    ).scalar_one()


async def has_open_flag(
    session: AsyncSession, user_id: str, event_id: str | None, kind: str
) -> bool:
    q = select(ModerationFlag.id).where(
        ModerationFlag.user_id == user_id,
        ModerationFlag.kind == kind,
        ModerationFlag.resolved_at.is_(None),
    )
    if event_id is not None:
        q = q.where(ModerationFlag.event_id == event_id)
    return (await session.execute(q.limit(1))).scalar_one_or_none() is not None


async def raise_flag(session: AsyncSession, user_id: str, event_id: str | None, kind: str) -> None:
    from sqlalchemy.dialects.postgresql import insert

    from app.core.ids import new_id

    await session.execute(
        insert(ModerationFlag)
        .values(id=new_id("flg"), user_id=user_id, event_id=event_id, kind=kind)
        .on_conflict_do_nothing()
    )


async def attach_report_context(
    session: AsyncSession, report_id: str, reporter_id: str, context: dict[str, Any]
) -> None:
    """Chat attaches the last messages of a reported conversation (01 §14.2)."""
    from app.modules.safety.models import Report

    report = await session.get(Report, report_id)
    if report is not None and report.reporter_id == reporter_id and report.context is None:
        report.context = context


WAVE_PAUSE = "wave_pause"
EVENT_SUSPENDED = "event_suspended"


async def export_user(session: AsyncSession, user_id: str) -> dict[str, Any]:
    """Blocks and reports the user made. Reports made about them are not included:
    that would reveal who reported them."""
    from app.modules.safety.models import Report

    blocks = (await session.scalars(select(Block).where(Block.user_id == user_id))).all()
    reports = (await session.scalars(select(Report).where(Report.reporter_id == user_id))).all()
    return {
        "blocked": [{"user_id": b.blocked_id, "at": b.created_at.isoformat()} for b in blocks],
        "reports_made": [
            {
                "subject_id": r.subject_id,
                "event_id": r.event_id,
                "reason": r.reason,
                "detail": r.detail,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in reports
        ],
    }


__all__ = [
    "EVENT_SUSPENDED",
    "WAVE_PAUSE",
    "attach_report_context",
    "block_between",
    "blocked_ids",
    "export_user",
    "has_open_flag",
    "i_have_not_blocked",
    "is_blocked_pair",
    "not_blocked",
    "raise_flag",
]
