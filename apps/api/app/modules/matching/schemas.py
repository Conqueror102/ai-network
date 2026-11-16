from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class MatchCard(BaseModel):
    """Raw scores never leave the server (05 §7.4)."""

    user_id: str
    display_name: str
    photo_url: str | None
    headline: str | None
    offer_text: str | None
    why: str
    matched_chips: list[str]
    wildcard: bool
    score_bucket: Literal["high", "medium"]


class AskedForCard(BaseModel):
    """Someone who fits what the viewer is looking for, shown apart from mutual
    matches because the interest may be one-sided. Contact is still a wave they can
    silently decline. Clients send that wave with source "directory"."""

    user_id: str
    display_name: str
    photo_url: str | None
    headline: str | None
    offer_text: str | None
    why: str
    matched_chips: list[str]


class FeedOut(BaseModel):
    items: list[MatchCard]
    asked_for: list[AskedForCard] = []
    computed_at: datetime | None
    warming_up: bool


class ConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, float]


class ConfigOut(BaseModel):
    values: dict[str, Any]
    overrides: dict[str, Any]
