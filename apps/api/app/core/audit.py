"""Audit trail for sensitive actions (doc 11 §3, 08 §7).

Every staff action under `/internal/*`, every organizer action that touches other
people's data, and every data export writes one row. The row joins the caller's
transaction, so an action and its audit entry commit or roll back together.
Rows are append-only: a trigger refuses UPDATE and DELETE.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core import ratelimit
from app.core.auth import CurrentUser, Principal
from app.core.db.base import Base, CreatedAt
from app.core.db.engine import DbSession
from app.core.ids import new_id


class AuditLog(Base, CreatedAt):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # aud_
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_role: Mapped[str] = mapped_column(String, nullable=False)  # staff | organizer | user
    action: Mapped[str] = mapped_column(String, nullable=False)  # "billing.refund"
    target_type: Mapped[str | None] = mapped_column(String)
    target_id: Mapped[str | None] = mapped_column(String)
    org_id: Mapped[str | None] = mapped_column(String)
    event_id: Mapped[str | None] = mapped_column(String)
    ip: Mapped[str | None] = mapped_column(INET)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    __table_args__ = (
        Index("ix_audit_log_org_id_created_at", "org_id", "created_at"),
        Index("ix_audit_log_actor_id_created_at", "actor_id", "created_at"),
    )


def record(
    session: AsyncSession,
    *,
    actor_id: str,
    actor_role: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    org_id: str | None = None,
    event_id: str | None = None,
    ip: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Stage an audit row in the caller's transaction. Never put message text,
    contact details or secrets in `meta`: ids and decisions only."""
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            org_id=org_id,
            event_id=event_id,
            ip=ip,
            meta=meta or {},
        )
    )


@dataclass
class Auditor:
    session: AsyncSession
    principal: Principal
    ip: str | None

    def log(
        self,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        *,
        role: str | None = None,
        org_id: str | None = None,
        event_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        record(
            self.session,
            actor_id=self.principal.user_id,
            actor_role=role or ("staff" if self.principal.staff else "user"),
            action=action,
            target_type=target_type,
            target_id=target_id,
            org_id=org_id,
            event_id=event_id,
            ip=self.ip,
            meta=meta,
        )


async def auditor(request: Request, principal: CurrentUser, session: DbSession) -> Auditor:
    ip = ratelimit.client_ip(request)
    return Auditor(session, principal, ip if _is_ip(ip) else None)


def _is_ip(value: str | None) -> bool:
    import ipaddress

    if not value:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


Audit = Annotated[Auditor, Depends(auditor)]
