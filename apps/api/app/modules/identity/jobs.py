from app.core import flags, jobs
from app.core.db.uow import UnitOfWork
from app.modules.ai import public as ai
from app.modules.identity.models import User
from app.modules.identity.service import SCREENED_FIELDS


@jobs.job("identity.moderate_photo")
async def moderate_photo(user_id: str, key: str) -> None:
    """v0: approve unless auto-approval is switched off (then staff review the queue).

    Image moderation by a vision model and variant generation are follow-ups; the
    status machine (pending -> approved | rejected) is already what clients rely on.
    """
    async with UnitOfWork() as session:
        user = await session.get(User, user_id)
        if user is None or user.photo_key != key or user.photo_status != "pending":
            return
        if await flags.is_enabled("photo.auto_approve", True):
            user.photo_status = "approved"


@jobs.job("identity.rescreen_profile", max_tries=5)
async def rescreen_profile(user_id: str) -> None:
    """Profile text accepted while AI was down gets screened once AI is back."""
    async with UnitOfWork() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        text = " \n ".join(str(getattr(user, f)) for f in SCREENED_FIELDS if getattr(user, f))
        if not text:
            return
        verdict = await ai.screen(text, kind="profile", user_id=user_id)  # raises => retry
        if not verdict.allow:
            user.headline, user.bio = None, None
