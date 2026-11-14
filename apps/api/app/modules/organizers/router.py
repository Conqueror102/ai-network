from fastapi import APIRouter, Response

from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.modules.organizers import service
from app.modules.organizers.service import MemberIn, MemberOut, OrganizerIn, OrganizerOut

router = APIRouter(tags=["organizers"])


@router.post("/organizers", response_model=OrganizerOut, status_code=201)
async def create_organizer(
    body: OrganizerIn, user: CurrentUser, session: DbSession
) -> OrganizerOut:
    return await service.create(session, user.user_id, body)


@router.get("/organizers", response_model=list[OrganizerOut])
async def my_organizers(user: CurrentUser, session: DbSession) -> list[OrganizerOut]:
    return await service.list_mine(session, user.user_id)


@router.get("/organizers/{organizer_id}/members", response_model=list[MemberOut])
async def members(organizer_id: str, user: CurrentUser, session: DbSession) -> list[MemberOut]:
    await service.require_role(session, organizer_id, user.user_id, "owner")
    return await service.list_members(session, organizer_id)


@router.post("/organizers/{organizer_id}/members", response_model=MemberOut, status_code=201)
async def add_member(
    organizer_id: str, body: MemberIn, user: CurrentUser, session: DbSession
) -> MemberOut:
    await service.require_role(session, organizer_id, user.user_id, "owner")
    return await service.add_member(session, organizer_id, body)


@router.delete("/organizers/{organizer_id}/members/{member_id}", status_code=204)
async def remove_member(
    organizer_id: str, member_id: str, user: CurrentUser, session: DbSession
) -> Response:
    await service.require_role(session, organizer_id, user.user_id, "owner")
    await service.remove_member(session, organizer_id, member_id)
    return Response(status_code=204)
