"""Data subject rights (08 §3, NDPA 2023 / GDPR): export. Erasure is `DELETE /me`."""

from typing import Any

from fastapi import APIRouter

from app.core import clock, ratelimit
from app.core.audit import Audit
from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.modules.chat import public as chat
from app.modules.connections import public as connections
from app.modules.identity import public as identity
from app.modules.notifications import public as notifications
from app.modules.profiles import public as profiles
from app.modules.safety import public as safety
from app.modules.waves import public as waves

router = APIRouter(tags=["privacy"])


@router.get("/me/export")
async def export_me(user: CurrentUser, session: DbSession, audit: Audit) -> dict[str, Any]:
    """Everything the user gave us, as JSON. Other people's data (their messages,
    the contact details they shared, reports about this user, who declined a wave)
    is never included: an export must not become a way around the product's rules."""
    await ratelimit.hit("export", user.user_id, limit=3, window_s=86400)
    me = user.user_id
    data = {
        "generated_at": clock.now().isoformat(),
        "account": await identity.export_user(session, me),
        "event_profiles": await profiles.export_user(session, me),
        "connections": await connections.export_user(session, me),
        "waves": await waves.export_user(session, me),
        "conversations": await chat.export_user(session, me),
        "notifications": await notifications.export_user(session, me),
        "safety": await safety.export_user(session, me),
    }
    audit.log("privacy.export", "user", me, role="user")
    await session.commit()
    return data
