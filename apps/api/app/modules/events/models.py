from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt, Timestamps


class Event(Base, Timestamps):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # evt_
    organizer_id: Mapped[str] = mapped_column(
        ForeignKey("organizers.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(String)
    venue_name: Mapped[str] = mapped_column(String, nullable=False)
    city_code: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str | None] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String, server_default="Africa/Lagos", nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int | None] = mapped_column(Integer)
    gating: Mapped[str] = mapped_column(String, server_default="open", nullable=False)
    visibility: Mapped[str] = mapped_column(String, server_default="public", nullable=False)
    door_qr_seed: Mapped[str] = mapped_column(String, nullable=False)
    static_door_qr_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    meeting_points: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}", nullable=False
    )
    status: Mapped[str] = mapped_column(String, server_default="draft", nullable=False)
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="capacity_positive"),
        CheckConstraint("gating IN ('open','apply')", name="gating_valid"),
        CheckConstraint("visibility IN ('public','unlisted')", name="visibility_valid"),
        CheckConstraint(
            "status IN ('draft','published','live','ended','cancelled')", name="status_valid"
        ),
        Index(
            "ix_events_discovery",
            "city_code",
            "starts_at",
            postgresql_where="visibility = 'public' AND status IN ('published','live')",
        ),
    )


class EventApplication(Base, CreatedAt):
    __tablename__ = "event_applications"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # app_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, server_default="pending", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("event_id", "user_id"),
        CheckConstraint("status IN ('pending','approved','rejected')", name="status_valid"),
        Index("ix_event_applications_event_status", "event_id", "status"),
    )


class Checkin(Base):
    """Door check-in. One per user per event per (UTC) day.

    02 used a unique index on `scanned_at::date`; that cast is not immutable for
    timestamptz, so the day is stored explicitly instead.
    """

    __tablename__ = "checkins"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # chk_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", "day"),
        Index("ix_checkins_event_scanned_at", "event_id", "scanned_at"),
    )


class Announcement(Base, CreatedAt):
    __tablename__ = "announcements"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # ann_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("char_length(body) <= 300", name="body_len"),)
