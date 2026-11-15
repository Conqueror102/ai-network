from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt, Timestamps

DIMS = 1024


class EventProfile(Base, Timestamps):
    """A user's identity within one event (00 §5)."""

    __tablename__ = "event_profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # epf_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    headline: Mapped[str | None] = mapped_column(String)
    offer_text: Mapped[str | None] = mapped_column(String)
    visibility: Mapped[str] = mapped_column(String, server_default="directory", nullable=False)
    profile_embedding: Mapped[list[float] | None] = mapped_column(Vector(DIMS))
    embedding_model: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        UniqueConstraint("event_id", "user_id"),
        CheckConstraint("visibility IN ('hidden','directory','radar')", name="visibility_valid"),
        CheckConstraint("char_length(offer_text) <= 300", name="offer_len"),
        CheckConstraint("char_length(headline) <= 80", name="headline_len"),
        Index(
            "ix_event_profiles_event_visible", "event_id", postgresql_where="visibility <> 'hidden'"
        ),
    )


class Goal(Base, CreatedAt):
    __tablename__ = "goals"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # gol_
    event_profile_id: Mapped[str] = mapped_column(
        ForeignKey("event_profiles.id", ondelete="CASCADE"), nullable=False
    )
    intent: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    offer: Mapped[str | None] = mapped_column(String)
    raw_input: Mapped[str | None] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, server_default="active", nullable=False)
    ask_embedding: Mapped[list[float] | None] = mapped_column(Vector(DIMS))
    offer_embedding: Mapped[list[float] | None] = mapped_column(Vector(DIMS))
    embedding_model: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        CheckConstraint(
            "intent IN ('hire','get_hired','raise','invest','sell','buy','learn',"
            "'cofounder','partner','meet')",
            name="intent_valid",
        ),
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority_range"),
        CheckConstraint("status IN ('active','archived')", name="status_valid"),
        CheckConstraint("char_length(offer) <= 300", name="offer_len"),
        CheckConstraint("char_length(raw_input) <= 500", name="raw_len"),
        # one active goal per priority slot; archived goals keep their history
        Index(
            "uq_goals_active_priority",
            "event_profile_id",
            "priority",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )
