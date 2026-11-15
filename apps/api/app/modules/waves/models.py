from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt


class Wave(Base, CreatedAt):
    """The only first-contact mechanism (01 §7). The card is frozen at send time."""

    __tablename__ = "waves"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # wav_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    from_user: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    to_user: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default="pending", nullable=False)
    # NULL while held back by the recipient's inbox cap (01 §7.4)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resurfaced: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conversation_id: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint("from_user <> to_user", name="not_self"),
        CheckConstraint("source IN ('match_feed','radar','directory')", name="source_valid"),
        CheckConstraint("char_length(note) <= 140", name="note_len"),
        CheckConstraint(
            "status IN ('pending','accepted','not_now','maybe_later','expired')",
            name="status_valid",
        ),
        UniqueConstraint("event_id", "from_user", "to_user"),
        Index(
            "ix_waves_inbox",
            "to_user",
            "event_id",
            "id",
            postgresql_where="status IN ('pending','maybe_later')",
        ),
        Index("ix_waves_event_status", "event_id", "status"),
        Index("ix_waves_from_user_event", "from_user", "event_id", "id"),
    )
