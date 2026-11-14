from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OtpRequestIn(In):
    channel: Literal["phone", "email"]
    destination: str = Field(min_length=3, max_length=254)
    turnstile_token: str | None = Field(default=None, max_length=4096)


class OtpRequestOut(BaseModel):
    request_id: str
    resend_after_s: int = 60


class OtpVerifyIn(In):
    request_id: str = Field(max_length=64)
    code: str = Field(pattern=r"^\d{6}$")


class RefreshIn(In):
    refresh_token: str = Field(max_length=256)


class Link(In):
    label: str = Field(max_length=40)
    url: HttpUrl


class UserOut(BaseModel):
    """Own profile, including private fields. Never returned for another user."""

    id: str
    phone: str | None
    email: str | None
    real_name: str | None
    display_name: str | None
    photo_url: str | None
    photo_status: str
    headline: str | None
    bio: str | None
    role_title: str | None
    company: str | None
    industry: str | None
    skills: list[str]
    links: list[dict[str, str]]
    share_email: bool
    share_phone: bool
    premium: bool
    created_at: datetime


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str


class VerifyOut(TokensOut):
    user: UserOut
    is_new: bool


class MePatchIn(In):
    real_name: str | None = Field(default=None, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    headline: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=600)
    role_title: str | None = Field(default=None, max_length=80)
    company: str | None = Field(default=None, max_length=80)
    industry: str | None = Field(default=None, max_length=40)
    skills: list[str] | None = Field(default=None, max_length=20)
    links: list[Link] | None = Field(default=None, max_length=5)
    share_email: bool | None = None
    share_phone: bool | None = None


class PhotoPresignIn(In):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]


class PhotoPresignOut(BaseModel):
    upload_url: str
    key: str
    max_bytes: int


class PhotoCommitIn(In):
    key: str = Field(max_length=200)


class PushSubscriptionIn(In):
    endpoint: HttpUrl
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)
