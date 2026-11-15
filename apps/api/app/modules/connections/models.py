from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, Timestamps
from app.core.db.types import EncryptedText


class Connection(Base, Timestamps):
    """One side's CRM row about a peer. Two rows per pair, one per owner (02 §4)."""

    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # con_
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    peer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)
    met_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # JSON of what the peer consented to share with me. Encrypted: it is contact PII.
    shared: Mapped[str | None] = mapped_column(EncryptedText)
    notes: Mapped[str | None] = mapped_column(EncryptedText)  # my private notes
    followup_drafts: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]", nullable=False)
    followup_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("user_id", "peer_id", "event_id"),
        CheckConstraint("user_id <> peer_id", name="not_self"),
        Index("ix_connections_user_id_id", "user_id", "id"),
        Index(
            "ix_connections_event_pending_followup",
            "event_id",
            postgresql_where="followup_generated_at IS NULL",
        ),
    )
