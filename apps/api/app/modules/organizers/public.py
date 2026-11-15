from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.organizers.models import Organizer
from app.modules.organizers.service import Role, require_role, role_of


async def billing_contact(session: AsyncSession, organizer_id: str) -> tuple[str, str | None]:
    """(name, billing email) of an organizer."""
    org = await session.get(Organizer, organizer_id)
    if org is None:
        raise NotFound
    return org.name, org.billing_email


__all__ = ["Role", "billing_contact", "require_role", "role_of"]
