from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt


class Organizer(Base, CreatedAt):
    __tablename__ = "organizers"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # org_
    name: Mapped[str] = mapped_column(String, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String)
    billing_email: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class OrganizerMember(Base, CreatedAt):
    __tablename__ = "organizer_members"
    organizer_id: Mapped[str] = mapped_column(
        ForeignKey("organizers.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint("role IN ('owner','staff')", name="role_valid"),)
