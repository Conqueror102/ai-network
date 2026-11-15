from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt


class MatchScore(Base):
    """One row per unordered pair per event. `score_a` ranks user_b in user_a's feed
    and vice versa: the two differ only by the other side's warmth (05 §5)."""

    __tablename__ = "match_scores"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    user_a: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    user_b: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    score_a: Mapped[float] = mapped_column(Float, nullable=False)
    score_b: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    why_a: Mapped[str | None] = mapped_column(Text)  # explanation shown to user_a
    why_b: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        CheckConstraint("user_a < user_b", name="canonical_order"),
        Index("ix_match_scores_event_b", "event_id", "user_b"),
    )


class MatchFeedItem(Base):
    """The selected feed for a user (05 §7): top matches plus wildcards."""

    __tablename__ = "match_feed_items"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    peer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    wildcard: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    __table_args__ = (Index("ix_match_feed_items_event_peer", "event_id", "peer_id"),)


class MatchFeedState(Base):
    __tablename__ = "match_feed_state"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MatchFeedback(Base, CreatedAt):
    """Labelled examples for the learning loop, and the source of feed exclusions."""

    __tablename__ = "match_feedback"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # mfb_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )  # who acted
    peer_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    signal: Mapped[str] = mapped_column(String, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "signal IN ('feed_skip','wave_sent','wave_accepted','wave_not_now','chat_started',"
            "'chat_died','meet_confirmed')",
            name="signal_valid",
        ),
        Index("ix_match_feedback_event_user", "event_id", "user_id", "signal"),
        Index("ix_match_feedback_event_peer", "event_id", "peer_id", "signal"),
    )


class MatchingConfig(Base):
    """Overrides for the tunable constants in 05, changed without a deploy."""

    __tablename__ = "matching_config"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "default"
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
