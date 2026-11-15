from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.profiles.public import EventCardOut


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TokenIn(In):
    event_id: str = Field(max_length=40)


class TokenOut(BaseModel):
    qr_payload: str
    ttl_s: int


class ScanIn(In):
    qr_payload: str = Field(min_length=8, max_length=120)
    event_id: str = Field(max_length=40)


class SharedContact(BaseModel):
    email: str | None = None
    phone: str | None = None
    links: list[dict[str, str]] = Field(default_factory=list)


class ConnectionOut(BaseModel):
    id: str
    event_id: str
    peer: EventCardOut
    met_confirmed_at: datetime | None
    shared: SharedContact
    notes: str | None
    followup_drafts: list[str]
    created_at: datetime


class PendingExchangeOut(BaseModel):
    confirm_id: str
    event_id: str
    peer_card: EventCardOut
    i_confirmed: bool
    expires_in_s: int


class ConfirmOut(BaseModel):
    status: Literal["waiting", "confirmed"]
    connection: ConnectionOut | None = None


class NotesIn(In):
    notes: str | None = Field(max_length=2000)
