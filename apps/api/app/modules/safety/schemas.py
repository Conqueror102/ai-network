from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Reason = Literal["harassment", "spam", "impersonation", "inappropriate_content", "other"]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BlockIn(In):
    user_id: str = Field(max_length=40)


class ReportIn(In):
    subject_id: str = Field(max_length=40)
    reason: Reason
    detail: str | None = Field(default=None, max_length=1000)
    conversation_id: str | None = Field(default=None, max_length=40)
    event_id: str | None = Field(default=None, max_length=40)


class ReportOut(BaseModel):
    id: str
    reporter_id: str
    subject_id: str
    event_id: str | None
    reason: str
    detail: str | None
    context: dict[str, Any] | None
    status: str
    action: str | None
    created_at: datetime


class ActionIn(In):
    action: Literal["warn", "suspend_event", "ban", "dismiss"]


class FlagOut(BaseModel):
    id: str
    user_id: str
    event_id: str | None
    kind: str
    created_at: datetime
