from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["wave", "wave_accepted", "message", "meet", "event", "wrapup", "safety"]
CATEGORIES: tuple[str, ...] = (
    "wave",
    "wave_accepted",
    "message",
    "meet",
    "event",
    "wrapup",
    "safety",
)


class NotificationOut(BaseModel):
    id: str
    category: str
    title: str
    body: str
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(default_factory=list, max_length=100)
    all: bool = False


class PrefsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    push: dict[Category, bool]


class PrefsOut(BaseModel):
    push: dict[str, bool]


class UnreadOut(BaseModel):
    unread: int
