from datetime import timedelta

import structlog
from sqlalchemy import delete, select

from app.adapters import factory
from app.core import clock, flags, jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.ai import public as ai
from app.modules.identity.models import AuthOtp, PushSubscription, RefreshToken, User
from app.modules.identity.service import SCREENED_FIELDS

log = structlog.get_logger()
OTP_KEEP = timedelta(hours=24)
TOKEN_KEEP = timedelta(days=30)
HARD_DELETE_AFTER = timedelta(days=30)
PURGE_BATCH = 200


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


async def purge_expired_credentials() -> tuple[int, int]:
    """OTPs go 24 hours after expiry, refresh tokens 30 days after expiry (02 retention)."""
    now = clock.now()
    async with UnitOfWork() as session:
        otps = await session.execute(delete(AuthOtp).where(AuthOtp.expires_at < now - OTP_KEEP))
        toks = await session.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < now - TOKEN_KEEP)
        )
    return otps.rowcount or 0, toks.rowcount or 0  # type: ignore[attr-defined]


async def purge_deleted_users() -> int:
    """Hard-delete the PII of accounts deleted 30 days ago (08 §3, NDPA erasure).

    The row stays as a tombstone so conversations still render "Deleted user"; every
    personal field, credential and push subscription goes. Other modules drop their
    own rows on `identity.user_purged`.
    """
    cutoff = clock.now() - HARD_DELETE_AFTER
    photo_keys: list[str] = []
    async with UnitOfWork() as session:
        users = (
            await session.scalars(
                select(User)
                .where(User.deleted_at < cutoff, User.purged_at.is_(None))
                .limit(PURGE_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for u in users:
            if u.photo_key:
                photo_keys.append(u.photo_key)
            u.phone = u.email = u.real_name = u.display_name = None
            u.photo_key, u.photo_status = None, "none"
            u.headline = u.bio = u.role_title = u.company = u.industry = None
            u.home_area_code = None
            u.skills, u.links = [], []
            u.share_email = u.share_phone = False
            u.premium_until = None
            u.purged_at = clock.now()
            await session.execute(delete(PushSubscription).where(PushSubscription.user_id == u.id))
            await session.execute(delete(RefreshToken).where(RefreshToken.user_id == u.id))
            outbox.emit(session, "identity.user_purged", {"user_id": u.id})
    for key in photo_keys:  # after commit: a failed object delete must not undo the purge
        try:
            await factory.storage().delete(key)
        except Exception:  # noqa: BLE001 - storage errors must not undo the purge
            log.warning("photo_delete_failed", key=key)
    return len(users)


@jobs.cron("identity.retention", hour={2}, minute={10})
async def retention() -> None:
    otps, toks = await purge_expired_credentials()
    users = await purge_deleted_users()
    log.info("identity_retention", otps=otps, refresh_tokens=toks, users_purged=users)
