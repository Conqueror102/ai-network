from typing import Any

from app.core import outbox
from app.core.db.uow import UnitOfWork
from app.modules.waves import service


@outbox.subscribe("identity.user_purged")
async def on_user_purged(payload: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        await service.forget_sender(session, payload["user_id"])
