"""Money tables (00 §4): integer minor units plus a currency, never floats.
`ledger_entries` is append-only, enforced by a database trigger."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, CreatedAt, Timestamps


class Invoice(Base, Timestamps):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # inv_
    organizer_id: Mapped[str] = mapped_column(ForeignKey("organizers.id"), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String, server_default="open", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_manually: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint("currency = upper(currency)", name="currency_upper"),
        CheckConstraint("status IN ('open','paid','void','refunded')", name="status_valid"),
        Index("ix_invoices_organizer_id_id", "organizer_id", "id"),
    )


class Payment(Base, Timestamps):
    """One checkout attempt for an invoice."""

    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # pay_ (also our reference)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    checkout_ref: Mapped[str] = mapped_column(String, nullable=False)
    charge_ref: Mapped[str | None] = mapped_column(String)
    checkout_url: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String, server_default="pending", nullable=False)
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','succeeded','failed','refunded','mismatch')",
            name="status_valid",
        ),
    )


class WebhookEventRow(Base):
    """Dedupe for inbound webhooks. In Postgres because it must survive a Redis flush."""

    __tablename__ = "webhook_events"
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (PrimaryKeyConstraint("provider", "provider_event_id"),)


class LedgerEntry(Base, CreatedAt):
    """Append-only money movements. Positive = money in, negative = money out."""

    __tablename__ = "ledger_entries"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # led_
    organizer_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    invoice_id: Mapped[str] = mapped_column(String, nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('charge','refund','manual_payment')", name="kind_valid"),
    )
