from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from app.core import ratelimit
from app.core.auth import CurrentUser, StaffUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.modules.safety import schemas, service
from app.modules.safety.models import Report

router = APIRouter(tags=["safety"])


@router.post("/blocks", status_code=204)
async def block(body: schemas.BlockIn, user: CurrentUser, session: DbSession) -> Response:
    await service.block(session, user.user_id, body.user_id)
    return Response(status_code=204)


@router.post("/reports", status_code=204)
async def report(body: schemas.ReportIn, user: CurrentUser, session: DbSession) -> Response:
    await ratelimit.hit("reports", user.user_id, limit=10, window_s=3600)
    await service.report(session, user.user_id, body)
    return Response(status_code=204)


def _out(r: Report) -> schemas.ReportOut:
    return schemas.ReportOut(
        id=r.id,
        reporter_id=r.reporter_id,
        subject_id=r.subject_id,
        event_id=r.event_id,
        reason=r.reason,
        detail=r.detail,
        context=r.context,
        status=r.status,
        action=r.action,
        created_at=r.created_at,
    )


@router.get("/internal/moderation/reports", response_model=Page[schemas.ReportOut])
async def reports(
    _: StaffUser,
    session: DbSession,
    status: Literal["open", "actioned", "dismissed"] = "open",
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.ReportOut]:
    rows, nxt = await service.list_reports(session, status, cursor, clamp_limit(limit))
    return Page(items=[_out(r) for r in rows], next_cursor=nxt)


@router.post("/internal/moderation/reports/{report_id}/action", response_model=schemas.ReportOut)
async def act(
    report_id: str, body: schemas.ActionIn, staff: StaffUser, session: DbSession
) -> schemas.ReportOut:
    return _out(await service.act_on_report(session, staff.user_id, report_id, body.action))


@router.get("/internal/moderation/flags", response_model=list[schemas.FlagOut])
async def flags(_: StaffUser, session: DbSession) -> list[schemas.FlagOut]:
    return [
        schemas.FlagOut(
            id=f.id, user_id=f.user_id, event_id=f.event_id, kind=f.kind, created_at=f.created_at
        )
        for f in await service.list_flags(session)
    ]


@router.post("/internal/moderation/flags/{flag_id}/resolve", status_code=204)
async def resolve_flag(flag_id: str, _: StaffUser, session: DbSession) -> Response:
    await service.resolve_flag(session, flag_id)
    return Response(status_code=204)
