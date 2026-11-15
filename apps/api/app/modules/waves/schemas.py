from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.profiles.public import EventCardOut


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WaveIn(In):
    to_user: str = Field(max_length=40)
    source: Literal["match_feed", "radar", "directory"]
    note: str | None = Field(default=None, max_length=140)


class SentWaveOut(BaseModel):
    """What the sender may know. `status` is only ever "pending" or "accepted":
    a decline, a snooze, an expiry and a held wave all read as "pending" (00 §4)."""

    id: str
    event_id: str
    to: EventCardOut
    source: str
    note: str | None
    status: Literal["pending", "accepted"]
    conversation_id: str | None
    created_at: datetime


class InboxWaveOut(BaseModel):
    id: str
    event_id: str
    card: dict[str, Any]
    source: str
    resurfaced: bool
    created_at: datetime


class RespondIn(In):
    action: Literal["accept", "not_now", "maybe_later"]


class RespondOut(BaseModel):
    conversation_id: str
