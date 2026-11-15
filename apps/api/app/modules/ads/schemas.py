from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PlacementIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    sponsor_id: str = Field(max_length=40)
    title: str = Field(min_length=1, max_length=60)
    body: str | None = Field(default=None, max_length=140)
    cta_url: HttpUrl | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class PlacementOut(BaseModel):
    id: str
    event_id: str
    sponsor_id: str
    kind: str
    title: str
    body: str | None
    cta_url: str | None
    status: str


class TileOut(BaseModel):
    """What an attendee sees. `label` is a server-side constant the client must render;
    organizers and sponsors cannot change or remove it (doc 11 §5)."""

    placement_id: str
    label: Literal["Sponsored"] = "Sponsored"
    sponsor_name: str
    title: str
    body: str | None
    cta_url: str | None


class SponsoredOut(BaseModel):
    tile: TileOut | None


class DayStats(BaseModel):
    day: date
    impressions: int
    taps: int


class ReportOut(BaseModel):
    """Aggregates only: no attendee identities, no per-person rows."""

    sponsor_id: str
    impressions: int
    taps: int
    daily: list[DayStats]
