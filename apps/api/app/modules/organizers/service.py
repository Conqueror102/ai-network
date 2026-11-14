"""Organizer accounts and membership. Every organizer-scoped read goes through
`require_role`, which is the tenant boundary (08 §6)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.core.ids import new_id
from app.modules.organizers.models import Organizer, OrganizerMember

Role = Literal["owner", "staff"]
_RANK = {"staff": 1, "owner": 2}


class OrganizerIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    billing_email: EmailStr | None = None


class OrganizerOut(BaseModel):
    id: str
    name: str
    logo_url: str | None
    role: str


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(max_length=40)
    role: Role = "staff"


class MemberOut(BaseModel):
    user_id: str
    role: str


async def role_of(session: AsyncSession, organizer_id: str, user_id: str) -> str | None:
    return (
        await session.execute(
            select(OrganizerMember.role).where(
                OrganizerMember.organizer_id == organizer_id, OrganizerMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def require_role(
    session: AsyncSession, organizer_id: str, user_id: str, minimum: Role = "staff"
) -> str:
    """404 (not 403) so non-members cannot learn which organizers exist."""
    role = await role_of(session, organizer_id, user_id)
    if role is None or _RANK[role] < _RANK[minimum]:
        raise NotFound
    return role


async def create(session: AsyncSession, user_id: str, data: OrganizerIn) -> OrganizerOut:
    org = Organizer(
        id=new_id("org"), name=data.name, billing_email=data.billing_email, created_by=user_id
    )
    session.add(org)
    await session.flush()
    session.add(OrganizerMember(organizer_id=org.id, user_id=user_id, role="owner"))
    await session.commit()
    return OrganizerOut(id=org.id, name=org.name, logo_url=None, role="owner")


async def list_mine(session: AsyncSession, user_id: str) -> list[OrganizerOut]:
    rows = (
        await session.execute(
            select(Organizer, OrganizerMember.role)
            .join(OrganizerMember, OrganizerMember.organizer_id == Organizer.id)
            .where(OrganizerMember.user_id == user_id)
            .order_by(Organizer.id)
            .limit(100)
        )
    ).all()
    return [OrganizerOut(id=o.id, name=o.name, logo_url=o.logo_url, role=r) for o, r in rows]


async def list_members(session: AsyncSession, organizer_id: str) -> list[MemberOut]:
    rows = (
        await session.execute(
            select(OrganizerMember)
            .where(OrganizerMember.organizer_id == organizer_id)
            .order_by(OrganizerMember.created_at)
            .limit(100)
        )
    ).scalars()
    return [MemberOut(user_id=m.user_id, role=m.role) for m in rows]


async def add_member(session: AsyncSession, organizer_id: str, data: MemberIn) -> MemberOut:
    from app.modules.identity import public as identity

    card = await identity.get_card(session, data.user_id)  # 404 when unknown
    if not card.active:
        raise NotFound
    existing = await session.get(OrganizerMember, (organizer_id, data.user_id))
    if existing is not None:
        existing.role = data.role
    else:
        session.add(
            OrganizerMember(organizer_id=organizer_id, user_id=data.user_id, role=data.role)
        )
    await session.flush()
    await _ensure_owner(session, organizer_id)
    await session.commit()
    return MemberOut(user_id=data.user_id, role=data.role)


async def remove_member(session: AsyncSession, organizer_id: str, user_id: str) -> None:
    member = await session.get(OrganizerMember, (organizer_id, user_id))
    if member is None:
        raise NotFound
    await session.delete(member)
    await session.flush()
    await _ensure_owner(session, organizer_id)
    await session.commit()


async def _ensure_owner(session: AsyncSession, organizer_id: str) -> None:
    owners = (
        await session.execute(
            select(func.count())
            .select_from(OrganizerMember)
            .where(OrganizerMember.organizer_id == organizer_id, OrganizerMember.role == "owner")
        )
    ).scalar_one()
    if owners == 0:
        raise Conflict("An organizer needs at least one owner", code="last_owner")
