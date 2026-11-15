from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt


class Notification(Base, CreatedAt):
    """In-app inbox row. Chat messages are never copied here: they stay in the
    encrypted messages table and only produce a push."""

    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # ntf_
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("ix_notifications_user_id_id", "user_id", "id"),
        Index("ix_notifications_unread", "user_id", postgresql_where="read_at IS NULL"),
    )


class NotificationPref(Base):
    """Per-category push toggle. No row means enabled."""

    __tablename__ = "notification_prefs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __table_args__ = (PrimaryKeyConstraint("user_id", "category"),)
