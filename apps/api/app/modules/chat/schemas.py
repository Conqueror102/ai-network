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


class MeetIn(In):
    meeting_point: str | None = Field(default=None, max_length=120)
    at: datetime | None = None
    accept_message_id: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _one_of(self) -> "MeetIn":
        proposing = self.meeting_point is not None and self.at is not None
        if proposing == (self.accept_message_id is not None):
            raise ValueError("send either {meeting_point, at} or {accept_message_id}")
        return self
