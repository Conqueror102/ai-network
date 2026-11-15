"""Connections' public surface."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connections.models import Connection
from app.modules.connections.service import ensure_pair


async def met_count(session: AsyncSession, event_id: str) -> int:
    """Confirmed in-person meetings in an event (pairs, not rows). Aggregate only."""
    rows = (
        await session.execute(
            select(func.count()).where(
                Connection.event_id == event_id,
                Connection.met_confirmed_at.is_not(None),
                Connection.user_id < Connection.peer_id,
            )
        )
    ).scalar_one()
    return int(rows)


async def connected_peer_ids(session: AsyncSession, event_id: str, user_id: str) -> set[str]:
    return set(
        (
            await session.execute(
                select(Connection.peer_id).where(
                    Connection.event_id == event_id, Connection.user_id == user_id
                )
            )
        ).scalars()
    )


async def export_user(session: AsyncSession, user_id: str) -> list[dict[str, object]]:
    """The user's own address book: who they connected with and their private notes.
    Contact details other people shared stay out: they are those people's data."""
    rows = (await session.scalars(select(Connection).where(Connection.user_id == user_id))).all()
    return [
        {
            "peer_id": c.peer_id,
            "event_id": c.event_id,
            "met_confirmed_at": c.met_confirmed_at.isoformat() if c.met_confirmed_at else None,
            "notes": c.notes,
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


__all__ = ["connected_peer_ids", "ensure_pair", "export_user", "met_count"]
