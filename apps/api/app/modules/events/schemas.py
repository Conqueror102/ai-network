from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EventCreateIn(In):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    venue_name: str = Field(min_length=1, max_length=120)
    city_code: str = Field(min_length=2, max_length=20)
    address: str | None = Field(default=None, max_length=240)
    timezone: str = Field(default="Africa/Lagos", max_length=40)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    capacity: int | None = Field(default=None, gt=0, le=200_000)
    gating: Literal["open", "apply"] = "open"
    visibility: Literal["public", "unlisted"] = "public"
    meeting_points: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _order(self) -> "EventCreateIn":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class EventPatchIn(In):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    venue_name: str | None = Field(default=None, min_length=1, max_length=120)
    city_code: str | None = Field(default=None, min_length=2, max_length=20)
    address: str | None = Field(default=None, max_length=240)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    capacity: int | None = Field(default=None, gt=0, le=200_000)
    gating: Literal["open", "apply"] | None = None
    visibility: Literal["public", "unlisted"] | None = None
    meeting_points: list[str] | None = Field(default=None, max_length=20)
    static_door_qr_enabled: bool | None = None


class StatusIn(In):
    status: Literal["published", "live", "ended", "cancelled"]


class EventOut(BaseModel):
    id: str
    organizer_id: str
    name: str
    description: str | None
    cover_url: str | None
    venue_name: str
    city_code: str
    address: str | None  # only for registered/approved attendees and organizers
    timezone: str
    starts_at: datetime
    ends_at: datetime
    capacity: int | None
    gating: str
    visibility: str
    status: str
    meeting_points: list[str]
    my_application: str | None = None
    checked_in: bool = False


class ApplyOut(BaseModel):
    status: str


class ApplicationOut(BaseModel):
    id: str
    user_id: str
    display_name: str
    headline: str | None
    status: str
    created_at: datetime


class DecideIn(In):
    approve: bool


class DoorQrOut(BaseModel):
    qr_token: str
    expires_in_s: int
    static_qr_token: str | None


class CheckinIn(In):
    qr_token: str = Field(max_length=200)


class CheckinOut(BaseModel):
    checked_in: bool = True
    event_room_unlocked: bool = True


class LiveStatsOut(BaseModel):
    checked_in: int
    capacity: int | None
    checkins_last_hour: list[int]  # twelve 5-minute buckets, oldest first


class AnnouncementIn(In):
    body: str = Field(min_length=1, max_length=300)


class AnnouncementOut(BaseModel):
    id: str
    event_id: str
    body: str
    created_at: datetime
