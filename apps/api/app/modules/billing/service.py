"""Organizer billing behind the PaymentProvider port (doc 11 §9.4).

The webhook is the only thing that marks money as received. A redirect back from the
checkout page proves nothing, so the client just polls the invoice.
"""

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import factory
from app.adapters.payments.port import PaymentError, WebhookEvent
from app.core import clock, outbox
from app.core.config import get_settings
from app.core.db.pagination import decode_cursor, paginate
from app.core.errors import NotFound
from app.core.ids import new_id
from app.modules.billing import errors
from app.modules.billing.models import Invoice, LedgerEntry, Payment, WebhookEventRow
from app.modules.billing.schemas import InvoiceIn, InvoiceOut
from app.modules.organizers import public as organizers

log = structlog.get_logger()


def invoice_out(i: Invoice) -> InvoiceOut:
    return InvoiceOut(
        id=i.id,
        organizer_id=i.organizer_id,
        event_id=i.event_id,
        description=i.description,
        amount_minor=i.amount_minor,
        currency=i.currency,
        status=i.status,
        due_at=i.due_at,
        paid_at=i.paid_at,
        created_at=i.created_at,
    )


async def create_invoice(session: AsyncSession, staff_id: str, data: InvoiceIn) -> Invoice:
    await organizers.billing_contact(session, data.organizer_id)  # 404 for unknown org
    invoice = Invoice(id=new_id("inv"), created_by=staff_id, **data.model_dump())
    session.add(invoice)
    await session.commit()
    return invoice


async def list_invoices(
    session: AsyncSession, organizer_id: str, cursor: str | None, limit: int
) -> tuple[list[Invoice], str | None]:
    q = select(Invoice).where(Invoice.organizer_id == organizer_id)
    after = decode_cursor(cursor)
    if after:
        q = q.where(Invoice.id < str(after))
    rows = list((await session.execute(q.order_by(Invoice.id.desc()).limit(limit + 1))).scalars())
    return paginate(rows, limit, lambda i: i.id)


async def _own_invoice(
    session: AsyncSession, organizer_id: str, invoice_id: str, *, lock: bool = False
) -> Invoice:
    q = select(Invoice).where(Invoice.id == invoice_id, Invoice.organizer_id == organizer_id)
    invoice = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if invoice is None:  # another organizer's invoice id looks like a missing one
        raise NotFound
    return invoice


async def start_checkout(session: AsyncSession, organizer_id: str, invoice_id: str) -> Payment:
    invoice = await _own_invoice(session, organizer_id, invoice_id, lock=True)
    if invoice.status != "open":
        raise errors.InvoiceNotPayable
    _name, email = await organizers.billing_contact(session, organizer_id)
    if not email:
        raise errors.BillingEmailRequired
    provider = factory.payments()
    payment_id = new_id("pay")
    try:
        checkout = await provider.create_checkout(
            reference=payment_id,
            amount_minor=invoice.amount_minor,
            currency=invoice.currency,
            customer_email=email,
            description=invoice.description,
            success_url=f"{get_settings().web_base_url}/billing/invoices/{invoice.id}",
            metadata={"invoice_id": invoice.id, "organizer_id": organizer_id},
        )
    except PaymentError as e:
        log.warning("checkout_failed", provider=provider.name, error=str(e))
        raise errors.PaymentProviderDown from e
    payment = Payment(
        id=payment_id,
        invoice_id=invoice.id,
        provider=provider.name,
        checkout_ref=checkout.provider_ref,
        checkout_url=checkout.url,
        amount_minor=invoice.amount_minor,
        currency=invoice.currency,
    )
    session.add(payment)
    await session.commit()
    return payment


def _ledger(invoice: Invoice, payment_id: str | None, kind: str, amount_minor: int) -> LedgerEntry:
    return LedgerEntry(
        id=new_id("led"),
        organizer_id=invoice.organizer_id,
        invoice_id=invoice.id,
        payment_id=payment_id,
        kind=kind,
        amount_minor=amount_minor,
        currency=invoice.currency,
    )


async def handle_webhook(session: AsyncSession, provider: str, event: WebhookEvent) -> str:
    """Apply a verified webhook exactly once. Returns "duplicate", "ignored" or "applied".

    The dedupe row and the state change commit together, so a crash in between makes
    the provider's retry do the work instead of losing it."""
    fresh = (
        await session.execute(
            insert(WebhookEventRow)
            .values(
                provider=provider,
                provider_event_id=event.event_id,
                type=event.type,
                payload=event.raw,
                processed_at=clock.now(),
            )
            .on_conflict_do_nothing()
            .returning(WebhookEventRow.provider_event_id)
        )
    ).scalar_one_or_none()
    if fresh is None:
        return "duplicate"
    outcome = "ignored"
    if event.reference and event.type.startswith("payment."):
        payment = (
            await session.execute(
                select(Payment)
                .where(Payment.id == event.reference, Payment.provider == provider)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if payment is not None:
            invoice = (
                await session.execute(
                    select(Invoice).where(Invoice.id == payment.invoice_id).with_for_update()
                )
            ).scalar_one()
            outcome = _apply(session, invoice, payment, event)
    await session.commit()
    return outcome


def _apply(session: AsyncSession, invoice: Invoice, payment: Payment, event: WebhookEvent) -> str:
    payment.charge_ref = event.provider_ref or payment.charge_ref
    if event.type == "payment.succeeded" and payment.status == "pending":
        if (event.amount_minor, event.currency) != (payment.amount_minor, payment.currency):
            # Paid a different amount or currency than we asked for: never mark as paid.
            payment.status = "mismatch"
            log.error("payment_amount_mismatch", payment_id=payment.id, invoice_id=invoice.id)
            return "applied"
        payment.status = "succeeded"
        session.add(_ledger(invoice, payment.id, "charge", payment.amount_minor))
        if invoice.status == "open":
            invoice.status, invoice.paid_at = "paid", clock.now()
            outbox.emit(
                session,
                "billing.invoice_paid",
                {"invoice_id": invoice.id, "organizer_id": invoice.organizer_id},
            )
        return "applied"
    if event.type == "payment.failed" and payment.status == "pending":
        payment.status = "failed"
        return "applied"
    if event.type == "payment.refunded" and payment.status == "succeeded":
        payment.status = "refunded"
        session.add(_ledger(invoice, payment.id, "refund", -payment.amount_minor))
        invoice.status = "refunded"
        return "applied"
    return "ignored"


async def mark_paid_manually(session: AsyncSession, invoice_id: str) -> Invoice:
    """Pilot invoices can be settled by bank transfer outside the provider (00 §3)."""
    invoice = (
        await session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFound
    if invoice.status != "open":
        raise errors.InvoiceNotPayable
    invoice.status, invoice.paid_at, invoice.paid_manually = "paid", clock.now(), True
    session.add(_ledger(invoice, None, "manual_payment", invoice.amount_minor))
    outbox.emit(
        session,
        "billing.invoice_paid",
        {"invoice_id": invoice.id, "organizer_id": invoice.organizer_id},
    )
    await session.commit()
    return invoice


async def refund(session: AsyncSession, invoice_id: str) -> Invoice:
    """Ask the provider for a full refund. The invoice flips to refunded when the
    provider's webhook confirms it, not here."""
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFound
    payment = (
        await session.execute(
            select(Payment).where(Payment.invoice_id == invoice_id, Payment.status == "succeeded")
        )
    ).scalar_one_or_none()
    if payment is None or not payment.charge_ref:
        raise errors.NothingToRefund
    try:
        await factory.payments().refund(payment.charge_ref, idempotency_key=f"refund_{payment.id}")
    except PaymentError as e:
        log.warning("refund_failed", payment_id=payment.id, error=str(e))
        raise errors.PaymentProviderDown from e
    return invoice
