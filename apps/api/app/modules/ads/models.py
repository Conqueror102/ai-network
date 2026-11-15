from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, Timestamps


class AdPlacement(Base, Timestamps):
    """Sponsored inventory. v0 has one kind: a tile in the event room."""

    __tablename__ = "ad_placements"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # adp_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    sponsor_id: Mapped[str] = mapped_column(
        ForeignKey("sponsors.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, server_default="tile", nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(String)
    cta_url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default="active", nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("kind IN ('tile')", name="kind_valid"),
        CheckConstraint("status IN ('active','held','paused')", name="status_valid"),
        CheckConstraint("char_length(title) <= 60", name="title_len"),
        CheckConstraint("char_length(body) <= 140", name="body_len"),
        Index("ix_ad_placements_event_id", "event_id"),
    )


class AdImpressionDaily(Base):
    """Counters only. There is deliberately no user column: who saw or tapped an ad is
    never stored, so it can never be handed to a sponsor."""

    __tablename__ = "ad_impressions_daily"
    placement_id: Mapped[str] = mapped_column(
        ForeignKey("ad_placements.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    taps: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    __table_args__ = (PrimaryKeyConstraint("placement_id", "day"),)
