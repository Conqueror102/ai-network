from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.core.errors import ValidationFailed
from app.modules.wingman import schemas, service

router = APIRouter(tags=["wingman"])


@router.post("/ai/assist", response_model=schemas.AssistOut)
async def assist(
    body: schemas.AssistIn, user: CurrentUser, session: DbSession
) -> schemas.AssistOut:
    options = await service.assist(session, user.user_id, user.premium, body)
    return schemas.AssistOut(options=options)


@router.post("/ai/assist/stream")
async def assist_stream(
    body: schemas.AssistIn, user: CurrentUser, session: DbSession
) -> StreamingResponse:
    if body.action == "suggest_replies":
        raise ValidationFailed("Streaming is for draft and rewrite", code="stream_unsupported")
    events = await service.assist_stream(session, user.user_id, user.premium, body)
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
