from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InvoiceIn(In):
    organizer_id: str = Field(max_length=40)
    event_id: str | None = Field(default=None, max_length=40)
    description: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(gt=0, le=10**12)  # integer minor units, never a float
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    due_at: datetime | None = None


class InvoiceOut(BaseModel):
    id: str
    organizer_id: str
    event_id: str | None
    description: str
    amount_minor: int
    currency: str
    status: str
    due_at: datetime | None
    paid_at: datetime | None
    created_at: datetime


class CheckoutOut(BaseModel):
    payment_id: str
    checkout_url: str
