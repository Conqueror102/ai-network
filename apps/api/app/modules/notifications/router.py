from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.modules.notifications import schemas, service

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=Page[schemas.NotificationOut])
async def inbox(
    user: CurrentUser,
    session: DbSession,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.NotificationOut]:
    rows, nxt = await service.list_inbox(session, user.user_id, cursor, clamp_limit(limit))
    return Page(
        items=[
            schemas.NotificationOut(
                id=n.id,
                category=n.category,
                title=n.title,
                body=n.body,
                data=n.data,
                read_at=n.read_at,
                created_at=n.created_at,
            )
            for n in rows
        ],
        next_cursor=nxt,
    )


@router.get("/notifications/unread-count", response_model=schemas.UnreadOut)
async def unread(user: CurrentUser, session: DbSession) -> schemas.UnreadOut:
    return schemas.UnreadOut(unread=await service.unread_count(session, user.user_id))


@router.post("/notifications/read", status_code=204)
async def read(body: schemas.ReadIn, user: CurrentUser, session: DbSession) -> Response:
    await service.mark_read(session, user.user_id, body.ids, body.all)
    return Response(status_code=204)


@router.get("/me/notification-prefs", response_model=schemas.PrefsOut)
async def get_prefs(user: CurrentUser, session: DbSession) -> schemas.PrefsOut:
    return schemas.PrefsOut(push=await service.get_prefs(session, user.user_id))


@router.put("/me/notification-prefs", response_model=schemas.PrefsOut)
async def put_prefs(
    body: schemas.PrefsIn, user: CurrentUser, session: DbSession
) -> schemas.PrefsOut:
    return schemas.PrefsOut(
        push=await service.set_prefs(
            session, user.user_id, {str(k): v for k, v in body.push.items()}
        )
    )
