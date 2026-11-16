"""Identity's public surface for other modules: DTOs only, never ORM objects."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import revoke_user
from app.core.errors import NotFound
from app.modules.identity.models import PushSubscription, User
from app.modules.identity.service import is_premium
from app.modules.media import public as media


@dataclass(frozen=True)
class UserCard:
    """Public-safe view of a user. No contact details."""

    id: str
    display_name: str
    photo_url: str | None
    headline: str | None
    bio: str | None
    role_title: str | None
    company: str | None
    industry: str | None
    skills: list[str]
    premium: bool
    active: bool


@dataclass(frozen=True)
class Contact:
    """Contact details the user has consented to share on tap-to-exchange."""

    email: str | None
    phone: str | None
    links: list[dict[str, str]]


@dataclass(frozen=True)
class PushSub:
    id: str
    endpoint: str
    p256dh: str
    auth: str


def _card(u: User) -> UserCard:
    active = u.deleted_at is None and u.suspended_at is None
    return UserCard(
        id=u.id,
        display_name=(u.display_name or "Attendee") if active else "Deleted user",
        photo_url=media.public_url(u.photo_key)
        if active and u.photo_key and u.photo_status == "approved"
        else None,
        headline=u.headline if active else None,
        bio=u.bio if active else None,
        role_title=u.role_title if active else None,
        company=u.company if active else None,
        industry=u.industry if active else None,
        skills=u.skills if active else [],
        premium=is_premium(u),
        active=active,
    )


async def get_cards(session: AsyncSession, user_ids: list[str]) -> dict[str, UserCard]:
    if not user_ids:
        return {}
    rows = (await session.execute(select(User).where(User.id.in_(set(user_ids))))).scalars()
    return {u.id: _card(u) for u in rows}


async def get_card(session: AsyncSession, user_id: str) -> UserCard:
    cards = await get_cards(session, [user_id])
    if user_id not in cards:
        raise NotFound
    return cards[user_id]


async def has_approved_photo(session: AsyncSession, user_id: str) -> bool:
    u = await session.get(User, user_id)
    return bool(u and u.photo_key and u.photo_status == "approved")


async def shared_contact(session: AsyncSession, user_id: str) -> Contact:
    """Only what the user opted to share (users.share_email / share_phone)."""
    u = await session.get(User, user_id)
    if u is None or u.deleted_at is not None:
        return Contact(None, None, [])
    return Contact(u.email if u.share_email else None, u.phone if u.share_phone else None, u.links)


async def private_contact(session: AsyncSession, user_id: str) -> tuple[str | None, str | None]:
    """(email, phone) for system notifications to the user themself. Never shown to others."""
    u = await session.get(User, user_id)
    if u is None or u.deleted_at is not None:
        return None, None
    return u.email, u.phone


async def push_subscriptions(session: AsyncSession, user_id: str) -> list[PushSub]:
    rows = (
        await session.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))
    ).scalars()
    return [PushSub(s.id, s.endpoint, s.p256dh, s.auth) for s in rows]


async def delete_push_subscription(session: AsyncSession, sub_id: str) -> None:
    sub = await session.get(PushSubscription, sub_id)
    if sub is not None:
        await session.delete(sub)


async def set_suspended(session: AsyncSession, user_id: str, suspended: bool) -> None:
    from app.core import clock

    u = await session.get(User, user_id)
    if u is None:
        raise NotFound
    u.suspended_at = clock.now() if suspended else None
    if suspended:
        await revoke_user(user_id)


def user_ids_matching(
    *,
    role: str | None = None,
    industry: str | None = None,
    company: str | None = None,
    text: str | None = None,
) -> Select[Any]:
    """Subquery of active user ids whose public profile fields contain the given text.
    For directory filters. Only fields that are already on the public card are searched;
    phone, email and real name never are."""

    def like(value: str) -> str:
        return f"%{value.replace('%', '').replace('_', '')}%"

    q = select(User.id).where(User.deleted_at.is_(None), User.suspended_at.is_(None))
    if role:
        q = q.where(or_(User.role_title.ilike(like(role)), User.headline.ilike(like(role))))
    if industry:
        q = q.where(User.industry.ilike(like(industry)))
    if company:
        q = q.where(User.company.ilike(like(company)))
    if text:
        q = q.where(
            or_(
                User.role_title.ilike(like(text)),
                User.company.ilike(like(text)),
                User.industry.ilike(like(text)),
                User.headline.ilike(like(text)),
            )
        )
    return q


async def export_user(session: AsyncSession, user_id: str) -> dict[str, object]:
    """The account record as the user gave it to us. Raises 404 for deleted accounts."""
    u = await session.get(User, user_id)
    if u is None or u.deleted_at is not None:
        raise NotFound
    return {
        "id": u.id,
        "phone": u.phone,
        "email": u.email,
        "real_name": u.real_name,
        "display_name": u.display_name,
        "headline": u.headline,
        "bio": u.bio,
        "role_title": u.role_title,
        "company": u.company,
        "industry": u.industry,
        "skills": u.skills,
        "links": u.links,
        "home_area_code": u.home_area_code,
        "share_email": u.share_email,
        "share_phone": u.share_phone,
        "photo_url": media.public_url(u.photo_key) if u.photo_key else None,
        "created_at": u.created_at.isoformat(),
    }


__all__ = [
    "Contact",
    "PushSub",
    "UserCard",
    "delete_push_subscription",
    "export_user",
    "get_card",
    "get_cards",
    "has_approved_photo",
    "private_contact",
    "push_subscriptions",
    "set_suspended",
    "shared_contact",
    "user_ids_matching",
]
