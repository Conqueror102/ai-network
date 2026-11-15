"""Sponsored tile delivery (doc 11 §5). Ads read nothing about the viewer and nothing
in matching, waves or the feed reads ads: money never ranks (00 §4)."""

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, flags
from app.core.errors import NotFound
from app.core.ids import new_id
from app.core.redis import get_redis, key
from app.modules.ads.models import AdImpressionDaily, AdPlacement
from app.modules.ads.schemas import DayStats, PlacementIn, PlacementOut, ReportOut, TileOut
from app.modules.sponsors import public as sponsors

DAILY_CAP = 12  # impressions per attendee per placement per day


def out(p: AdPlacement) -> PlacementOut:
    return PlacementOut(
        id=p.id,
        event_id=p.event_id,
        sponsor_id=p.sponsor_id,
        kind=p.kind,
        title=p.title,
        body=p.body,
        cta_url=p.cta_url,
        status=p.status,
    )


async def create(
    session: AsyncSession, event_id: str, user_id: str, data: PlacementIn
) -> AdPlacement:
    await sponsors.get_info(session, event_id, data.sponsor_id)  # 404 across events
    status = await sponsors.screen_text(f"{data.title}. {data.body or ''}", user_id, event_id)
    placement = AdPlacement(
        id=new_id("adp"),
        event_id=event_id,
        sponsor_id=data.sponsor_id,
        title=data.title,
        body=data.body,
        cta_url=str(data.cta_url) if data.cta_url else None,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        status=status,
    )
    session.add(placement)
    await session.commit()
    return placement


async def list_for_event(session: AsyncSession, event_id: str) -> list[AdPlacement]:
    return list(
        (
            await session.execute(
                select(AdPlacement).where(AdPlacement.event_id == event_id).order_by(AdPlacement.id)
            )
        ).scalars()
    )


async def set_status(session: AsyncSession, event_id: str, placement_id: str, status: str) -> None:
    placement = await session.get(AdPlacement, placement_id)
    if placement is None or placement.event_id != event_id:
        raise NotFound
    if placement.status == "held" and status == "active":
        raise NotFound  # only staff review releases held content
    placement.status = status
    await session.commit()


async def _bump(session: AsyncSession, placement_id: str, column: str) -> None:
    today = clock.now().date()
    stmt = insert(AdImpressionDaily).values(placement_id=placement_id, day=today, **{column: 1})
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["placement_id", "day"],
            set_={column: getattr(AdImpressionDaily, column) + 1},
        )
    )


async def tile_for(session: AsyncSession, event_id: str, viewer_id: str) -> TileOut | None:
    """At most one sponsored tile. Rotation is by least-shown today, never by anything
    about the viewer."""
    if not await flags.is_enabled(f"sponsor.surfaces.{event_id}", True):
        return None
    now = clock.now()
    rows = list(
        (
            await session.execute(
                select(AdPlacement)
                .outerjoin(
                    AdImpressionDaily,
                    (AdImpressionDaily.placement_id == AdPlacement.id)
                    & (AdImpressionDaily.day == now.date()),
                )
                .where(
                    AdPlacement.event_id == event_id,
                    AdPlacement.status == "active",
                    or_(AdPlacement.starts_at.is_(None), AdPlacement.starts_at <= now),
                    or_(AdPlacement.ends_at.is_(None), AdPlacement.ends_at > now),
                )
                .order_by(func.coalesce(AdImpressionDaily.impressions, 0), AdPlacement.id)
                .limit(5)
            )
        ).scalars()
    )
    r = get_redis()
    for placement in rows:
        sponsor = await sponsors.get_info(session, event_id, placement.sponsor_id)
        if not sponsor.active:
            continue
        cap = key("quota", "ad", placement.id, viewer_id, now.strftime("%Y%m%d"))
        seen = await r.incr(cap)
        await r.expire(cap, 36 * 3600)
        if seen > DAILY_CAP:  # frequency cap; the counter key expires, nothing is stored
            continue
        await _bump(session, placement.id, "impressions")
        await session.commit()
        return TileOut(
            placement_id=placement.id,
            sponsor_name=sponsor.name,
            title=placement.title,
            body=placement.body,
            cta_url=placement.cta_url,
        )
    return None


async def tap(session: AsyncSession, event_id: str, placement_id: str) -> None:
    placement = await session.get(AdPlacement, placement_id)
    if placement is None or placement.event_id != event_id or placement.status != "active":
        raise NotFound
    await _bump(session, placement_id, "taps")
    await session.commit()


async def report(session: AsyncSession, event_id: str, sponsor_id: str) -> ReportOut:
    await sponsors.get_info(session, event_id, sponsor_id)
    rows = (
        await session.execute(
            select(
                AdImpressionDaily.day,
                func.sum(AdImpressionDaily.impressions),
                func.sum(AdImpressionDaily.taps),
            )
            .join(AdPlacement, AdPlacement.id == AdImpressionDaily.placement_id)
            .where(AdPlacement.event_id == event_id, AdPlacement.sponsor_id == sponsor_id)
            .group_by(AdImpressionDaily.day)
            .order_by(AdImpressionDaily.day)
        )
    ).all()
    daily = [DayStats(day=d, impressions=int(i), taps=int(t)) for d, i, t in rows]
    return ReportOut(
        sponsor_id=sponsor_id,
        impressions=sum(d.impressions for d in daily),
        taps=sum(d.taps for d in daily),
        daily=daily,
    )


async def release_held(session: AsyncSession, placement_id: str) -> None:
    await session.execute(
        update(AdPlacement)
        .where(AdPlacement.id == placement_id, AdPlacement.status == "held")
        .values(status="active")
    )
    await session.commit()
