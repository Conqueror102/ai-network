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


__all__ = ["blocked_ids", "has_open_flag", "is_blocked_pair", "not_blocked", "raise_flag"]
