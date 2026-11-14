from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt, Timestamps


class User(Base, Timestamps):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # usr_
    phone: Mapped[str | None] = mapped_column(String, unique=True)  # E.164
    email: Mapped[str | None] = mapped_column(String, unique=True)  # lowercased
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    real_name: Mapped[str | None] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String)
    photo_key: Mapped[str | None] = mapped_column(String)
    photo_status: Mapped[str] = mapped_column(String, server_default="none", nullable=False)
    headline: Mapped[str | None] = mapped_column(String)
    bio: Mapped[str | None] = mapped_column(Text)
    role_title: Mapped[str | None] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    industry: Mapped[str | None] = mapped_column(String)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}", nullable=False)
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]", nullable=False)
    home_area_code: Mapped[str | None] = mapped_column(String)
    share_email: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    share_phone: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_staff: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "phone IS NOT NULL OR email IS NOT NULL OR deleted_at IS NOT NULL",
            name="contact_present",
        ),
        CheckConstraint("char_length(headline) <= 80", name="headline_len"),
        CheckConstraint("char_length(bio) <= 600", name="bio_len"),
        CheckConstraint(
            "photo_status IN ('none','pending','approved','rejected')", name="photo_status_valid"
        ),
    )


class AuthOtp(Base, CreatedAt):
    __tablename__ = "auth_otps"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # otp_
    channel: Mapped[str] = mapped_column(String, nullable=False)
    destination: Mapped[str] = mapped_column(String, nullable=False)
    code_hash: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("channel IN ('phone','email')", name="channel_valid"),
        Index("ix_auth_otps_destination_expires_at", "destination", "expires_at"),
    )


class RefreshToken(Base, CreatedAt):
    __tablename__ = "refresh_tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # tok_
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    family_id: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    device_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_refresh_tokens_user_id_family_id", "user_id", "family_id"),)


class PushSubscription(Base, CreatedAt):
    """Web Push subscription (v0 PWA). Expo device tokens arrive with v1.5."""

    __tablename__ = "push_subscriptions"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # psh_
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
