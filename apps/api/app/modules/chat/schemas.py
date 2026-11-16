from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.profiles.public import EventCardOut

MAX_BODY = 2000


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MessageIn(In):
    body: str = Field(min_length=1, max_length=MAX_BODY)
    ai_assisted: bool = False


class MessageOut(BaseModel):
    """`ai_assisted` is analytics only and is never part of this shape (01 §8.5)."""

    id: str
    conversation_id: str
    sender_id: str | None
    kind: Literal["text", "system", "icebreakers", "meet_proposal"]
    body: str
    payload: dict[str, Any] | None
    delivered_at: datetime | None
    read_at: datetime | None
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    event_id: str
    peer: EventCardOut
    last_message: MessageOut | None
    last_message_at: datetime | None
    unread_count: int
    created_at: datetime


class ReadIn(In):
    last_message_id: str = Field(max_length=40)


SPOT_ME_MAX = 80


class MeetIn(In):
    """Propose with a numbered spot (`spot_id`) or its name (`meeting_point`), or accept.
    `spot_me` is an optional "how to spot me" line for this one meet-up."""

    spot_id: str | None = Field(default=None, max_length=40)
    meeting_point: str | None = Field(default=None, max_length=120)
    at: datetime | None = None
    accept_message_id: str | None = Field(default=None, max_length=40)
    spot_me: str | None = Field(default=None, min_length=1, max_length=SPOT_ME_MAX)

    @model_validator(mode="after")
    def _one_of(self) -> "MeetIn":
        place = (self.spot_id is not None) + (self.meeting_point is not None)
        proposing = place == 1 and self.at is not None
        accepting = self.accept_message_id is not None
        if place > 1 or proposing == accepting or (accepting and (place or self.at)):
            raise ValueError("send either {spot_id or meeting_point, at} or {accept_message_id}")
        return self


class MeetStatusIn(In):
    """`spot_me`: set or change my "how to spot me" line. `arrived`: I am at the spot."""

    spot_me: str | None = Field(default=None, min_length=1, max_length=SPOT_ME_MAX)
    arrived: Literal[True] | None = None

    @model_validator(mode="after")
    def _something(self) -> "MeetStatusIn":
        if self.spot_me is None and self.arrived is None:
            raise ValueError("send spot_me, arrived, or both")
        return self


class MeetSpotOut(BaseModel):
    """`busy` is a coarse level for the chosen time, never a count or a list of people."""

    id: str
    number: int
    code: str
    label: str
    hint: str | None
    busy: Literal["quiet", "some", "busy"]
    suggested: bool
