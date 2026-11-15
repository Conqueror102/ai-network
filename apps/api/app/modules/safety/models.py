from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt


class Block(Base, CreatedAt):
    """Permanent, cross-event, and absolute (00 §4 invariant 5)."""

    __tablename__ = "blocks"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    __table_args__ = (CheckConstraint("user_id <> blocked_id", name="not_self"),)


class Report(Base, CreatedAt):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # rpt_
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    event_id: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, server_default="open", nullable=False)
    actioned_by: Mapped[str | None] = mapped_column(String)
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint(
            "reason IN ('harassment','spam','impersonation','inappropriate_content','other')",
            name="reason_valid",
        ),
        CheckConstraint("status IN ('open','actioned','dismissed')", name="status_valid"),
        Index("ix_reports_status_created_at", "status", "created_at"),
    )


class ModerationFlag(Base, CreatedAt):
    """Automatic flags (01 §14.3): decline streaks, repeated safety-screen failures."""

    __tablename__ = "moderation_flags"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # flg_
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_moderation_flags_open",
            "user_id",
            "event_id",
            "kind",
            unique=True,
            postgresql_where="resolved_at IS NULL",
        ),
    )
