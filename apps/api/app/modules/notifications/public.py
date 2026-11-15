"""Public surface of the notifications module."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification, NotificationPref


async def export_user(session: AsyncSession, user_id: str) -> dict[str, object]:
    inbox = (
        await session.scalars(
            select(Notification).where(Notification.user_id == user_id).order_by(Notification.id)
        )
    ).all()
    prefs = (
        await session.scalars(select(NotificationPref).where(NotificationPref.user_id == user_id))
    ).all()
    return {
        "inbox": [
            {
                "category": n.category,
                "title": n.title,
                "body": n.body,
                "created_at": n.created_at.isoformat(),
                "read_at": n.read_at.isoformat() if n.read_at else None,
            }
            for n in inbox
        ],
        "prefs": {p.category: p.push_enabled for p in prefs},
    }


__all__ = ["export_user"]
