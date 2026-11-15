from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, Timestamps


class Sponsor(Base, Timestamps):
    """A sponsor of one event. Holds no attendee data of any kind (08 §6)."""

    __tablename__ = "sponsors"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # spn_
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    tagline: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default="active", nullable=False)
    __table_args__ = (
        CheckConstraint("status IN ('active','held','archived')", name="status_valid"),
        CheckConstraint("char_length(name) <= 80", name="name_len"),
        CheckConstraint("char_length(tagline) <= 140", name="tagline_len"),
        Index("ix_sponsors_event_id", "event_id"),
    )
