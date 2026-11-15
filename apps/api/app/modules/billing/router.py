from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request

from app.adapters import factory
from app.adapters.payments.port import WebhookInvalid
from app.core import idempotency, ratelimit
from app.core.audit import Audit
from app.core.auth import CurrentUser, StaffUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.core.errors import NotFound, ValidationFailed
from app.modules.billing import schemas, service
from app.modules.organizers import public as organizers

router = APIRouter(tags=["billing"])


@router.get("/organizers/{organizer_id}/invoices", response_model=Page[schemas.InvoiceOut])
async def invoices(
    organizer_id: str,
    user: CurrentUser,
    session: DbSession,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.InvoiceOut]:
    await organizers.require_role(session, organizer_id, user.user_id, "owner")
    rows, nxt = await service.list_invoices(session, organizer_id, cursor, clamp_limit(limit))
    return Page(items=[service.invoice_out(i) for i in rows], next_cursor=nxt)


@router.post(
    "/organizers/{organizer_id}/invoices/{invoice_id}/checkout",
    response_model=schemas.CheckoutOut,
)
async def checkout(
    organizer_id: str,
    invoice_id: str,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> Any:
    await organizers.require_role(session, organizer_id, user.user_id, "owner")
    fingerprint = {"invoice": invoice_id}
    replay = await idempotency.lookup(user.user_id, idempotency_key, fingerprint)
    if replay is not None:
        return replay
    await ratelimit.hit("checkout", user.user_id, limit=10, window_s=600)
    payment = await service.start_checkout(session, organizer_id, invoice_id)
    out = schemas.CheckoutOut(payment_id=payment.id, checkout_url=payment.checkout_url)
    await idempotency.store(user.user_id, idempotency_key, fingerprint, out.model_dump())
    return out


@router.post("/webhooks/{provider}", include_in_schema=False)
async def webhook(provider: str, request: Request, session: DbSession) -> dict[str, str]:
    """Unauthenticated by design: the signature over the raw body is the credential."""
    adapter = factory.payments()
    if provider != adapter.name:
        raise NotFound
    try:
        event = adapter.verify_webhook(body=await request.body(), headers=dict(request.headers))
    except WebhookInvalid as e:
        raise ValidationFailed("Invalid signature", code="webhook_invalid") from e
    return {"result": await service.handle_webhook(session, provider, event)}


# --- staff ---------------------------------------------------------------------------


@router.post("/internal/billing/invoices", response_model=schemas.InvoiceOut, status_code=201)
async def create_invoice(
    body: schemas.InvoiceIn, staff: StaffUser, session: DbSession, audit: Audit
) -> schemas.InvoiceOut:
    audit.log(
        "billing.invoice_create",
        "organizer",
        body.organizer_id,
        org_id=body.organizer_id,
        meta={"amount_minor": body.amount_minor, "currency": body.currency},
    )
    return service.invoice_out(await service.create_invoice(session, staff.user_id, body))


@router.post("/internal/billing/invoices/{invoice_id}/mark-paid", response_model=schemas.InvoiceOut)
async def mark_paid(
    invoice_id: str, _: StaffUser, session: DbSession, audit: Audit
) -> schemas.InvoiceOut:
    audit.log("billing.mark_paid", "invoice", invoice_id)
    return service.invoice_out(await service.mark_paid_manually(session, invoice_id))


@router.post("/internal/billing/invoices/{invoice_id}/refund", response_model=schemas.InvoiceOut)
async def refund(
    invoice_id: str, _: StaffUser, session: DbSession, audit: Audit
) -> schemas.InvoiceOut:
    audit.log("billing.refund", "invoice", invoice_id)
    return service.invoice_out(await service.refund(session, invoice_id))
