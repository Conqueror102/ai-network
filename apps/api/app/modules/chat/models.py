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
from app.core.db.types import EncryptedText


class Conversation(Base, CreatedAt):
    """Strictly 1:1, born from an accepted wave, tied to one event forever (01 §8.1)."""

    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # cnv_
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)
    user_a: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    user_b: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_from_wave: Mapped[str | None] = mapped_column(String)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # read cursors: the last message id each side has read
    read_a: Mapped[str | None] = mapped_column(String)
    read_b: Mapped[str | None] = mapped_column(String)
    died_logged: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    __table_args__ = (
        CheckConstraint("user_a < user_b", name="canonical_order"),
        UniqueConstraint("event_id", "user_a", "user_b"),
        Index("ix_conversations_user_a_last", "user_a", "last_message_at"),
        Index("ix_conversations_user_b_last", "user_b", "last_message_at"),
    )


class Message(Base, CreatedAt):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # msg_ (ULID: time ordered)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))  # NULL = wingman
    kind: Mapped[str] = mapped_column(String, server_default="text", nullable=False)
    # Encrypted at rest (08 §5). The 2,000 character limit is enforced in the schema layer
    # because the database only ever sees ciphertext.
    body: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "kind IN ('text','system','icebreakers','meet_proposal')", name="kind_valid"
        ),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
    )
