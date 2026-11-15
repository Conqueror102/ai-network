from typing import Any

from sqlalchemy import update

from app.core import outbox
from app.core.db.uow import UnitOfWork
from app.modules.connections.models import Connection


@outbox.subscribe("identity.user_deleted")
async def forget_shared_contact(payload: dict[str, Any]) -> None:
    """A deleted user's contact details leave every address book at once (08 §6);
    the rows themselves go with the hard delete (FK cascade)."""
    async with UnitOfWork() as session:
        await session.execute(
            update(Connection)
            .where(Connection.peer_id == payload["user_id"])
            .values(shared=None, followup_drafts=[])
        )
