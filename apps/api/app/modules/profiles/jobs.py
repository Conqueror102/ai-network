from sqlalchemy import select

from app.core import jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.ai import public as ai
from app.modules.identity import public as identity
from app.modules.profiles.models import EventProfile, Goal
from app.modules.profiles.service import ask_text, offer_text


@jobs.job("profiles.embed", max_tries=5, timeout_s=60)
async def embed_profile(profile_id: str) -> None:
    """(Re)embed a profile and its active goals, then ask matching to recompute.
    Idempotent: re-running writes the same vectors."""
    async with UnitOfWork() as session:
        profile = await session.get(EventProfile, profile_id)
        if profile is None:
            return
        user = await identity.get_card(session, profile.user_id)
        goals = list(
            (
                await session.execute(
                    select(Goal).where(Goal.event_profile_id == profile_id, Goal.status == "active")
                )
            ).scalars()
        )
        docs = [f"{profile.offer_text or ''}. {profile.headline or ''}. {user.bio or ''}"]
        docs += [offer_text(g, profile) for g in goals]
        doc_vecs, model = await ai.embed(docs, input_type="document")  # raises => retry
        profile.profile_embedding, profile.embedding_model = doc_vecs[0], model
        if goals:
            ask_vecs, _ = await ai.embed([ask_text(g) for g in goals], input_type="query")
            for goal, ask_vec, offer_vec in zip(goals, ask_vecs, doc_vecs[1:], strict=True):
                goal.ask_embedding, goal.offer_embedding = ask_vec, offer_vec
                goal.embedding_model = model
        outbox.emit(
            session, "profiles.embedded", {"event_id": profile.event_id, "user_id": profile.user_id}
        )


@outbox.subscribe("identity.user_purged")
async def on_user_purged(payload: dict[str, object]) -> None:
    """Event profiles, goals and their embeddings go with the account (08 §3)."""
    from sqlalchemy import delete

    async with UnitOfWork() as session:
        await session.execute(
            delete(EventProfile).where(EventProfile.user_id == payload["user_id"])
        )
