"""Transactional outbox + in-process domain event handlers (doc 11 §7.2, §7.3).

A service writes its rows and `emit(session, topic, payload)` in the same
transaction. The relay (worker) later delivers each row to every handler
subscribed to its topic. Delivery is at-least-once, so handlers are idempotent.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import DateTime, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core import clock
from app.core.db.base import Base, CreatedAt
from app.core.db.engine import get_session_factory
from app.core.ids import new_id

log = structlog.get_logger()
MAX_ATTEMPTS = 10

Handler = Callable[[dict[str, Any]], Awaitable[None]]
_handlers: dict[str, list[Handler]] = defaultdict(list)


class OutboxEvent(Base, CreatedAt):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("ix_outbox_pending", "available_at", postgresql_where="processed_at IS NULL"),
    )


def subscribe(topic: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        if fn not in _handlers[topic]:
            _handlers[topic].append(fn)
        return fn

    return deco


def emit(session: AsyncSession, topic: str, payload: dict[str, Any]) -> str:
    """Add an outbox row to the caller's transaction. Payload carries `_outbox_id`."""
    oid = new_id("obx")
    session.add(
        OutboxEvent(
            id=oid, topic=topic, payload={**payload, "_outbox_id": oid}, available_at=clock.now()
        )
    )
    return oid


async def relay_once(batch: int = 100) -> int:
    """Deliver up to `batch` pending rows. Returns how many were processed OK."""
    done = 0
    async with get_session_factory()() as session:
        rows = (
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.processed_at.is_(None),
                        OutboxEvent.available_at <= clock.now(),
                        OutboxEvent.attempts < MAX_ATTEMPTS,
                    )
                    .order_by(OutboxEvent.id)
                    .limit(batch)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            try:
                for handler in list(_handlers.get(row.topic, [])):
                    await handler(row.payload)
            except Exception as e:
                row.attempts += 1
                row.last_error = repr(e)[:500]
                row.available_at = clock.now() + timedelta(seconds=min(2**row.attempts, 600))
                log.exception(
                    "outbox_delivery_failed",
                    topic=row.topic,
                    outbox_id=row.id,
                    attempts=row.attempts,
                )
            else:
                row.processed_at = clock.now()
                done += 1
        await session.commit()
    return done


async def drain(max_rounds: int = 20) -> int:
    """Relay until empty (handlers may emit more events). Used by tests and the worker."""
    total = 0
    for _ in range(max_rounds):
        n = await relay_once()
        if n == 0:
            break
        total += n
    return total


async def lag_seconds() -> float:
    async with get_session_factory()() as session:
        oldest = (
            await session.execute(
                select(func.min(OutboxEvent.available_at)).where(
                    OutboxEvent.processed_at.is_(None), OutboxEvent.attempts < MAX_ATTEMPTS
                )
            )
        ).scalar()
    return 0.0 if oldest is None else max(0.0, (clock.now() - oldest).total_seconds())
