"""Staff-only reads over the audit trail. Hidden behind 404 like every `/internal/*`."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.auth import StaffUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit, decode_cursor, paginate

router = APIRouter(tags=["admin"])


class AuditOut(BaseModel):
    id: str
    actor_id: str
    actor_role: str
    action: str
    target_type: str | None
    target_id: str | None
    org_id: str | None
    event_id: str | None
    ip: str | None
    meta: dict[str, Any]
    created_at: datetime


@router.get("/internal/audit", response_model=Page[AuditOut])
async def audit_trail(
    _: StaffUser,
    session: DbSession,
    actor_id: Annotated[str | None, Query(max_length=40)] = None,
    org_id: Annotated[str | None, Query(max_length=40)] = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[AuditOut]:
    stmt = select(AuditLog)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if org_id:
        stmt = stmt.where(AuditLog.org_id == org_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    after = decode_cursor(cursor)
    if after:
        stmt = stmt.where(AuditLog.id < str(after))
    n = clamp_limit(limit)
    rows = list((await session.scalars(stmt.order_by(AuditLog.id.desc()).limit(n + 1))).all())
    rows, nxt = paginate(rows, n, lambda r: r.id)
    return Page(
        items=[
            AuditOut(
                id=r.id,
                actor_id=r.actor_id,
                actor_role=r.actor_role,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                org_id=r.org_id,
                event_id=r.event_id,
                ip=str(r.ip) if r.ip else None,
                meta=r.meta,
                created_at=r.created_at,
            )
            for r in rows
        ],
        next_cursor=nxt,
    )
