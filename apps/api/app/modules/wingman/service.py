"""The wingman (01 §8.4, 06 §4.4): private, sender-side writing help.

It only ever returns editable text. Nothing here can send a message: the user taps
send in the chat like for any message they typed (00 §4 invariant 6).
"""

import json
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.errors import DependencyUnavailable, ValidationFailed
from app.modules.ai import public as ai
from app.modules.chat import public as chat
from app.modules.profiles import public as profiles
from app.modules.wingman.schemas import AssistIn

FREE_PER_HOUR, PREMIUM_PER_HOUR = 30, 120


class WingmanUnavailable(DependencyUnavailable):
    code, message = "ai_unavailable", "Wingman is unavailable right now"


class ToneUnavailable(ValidationFailed):
    code, message = "tone_unavailable", "The wingman keeps it professional"


async def _prompt(session: AsyncSession, me: str, premium: bool, data: AssistIn) -> tuple[str, str]:
    """Authorize (participant, not blocked), meter, and build the prompt."""
    event_id, peer, history = await chat.assist_context(session, data.conversation_id, me)
    await ratelimit.hit(
        "assist", me, limit=PREMIUM_PER_HOUR if premium else FREE_PER_HOUR, window_s=3600
    )
    await ai.consume_daily_assist(me, premium=premium)
    people = await profiles.load_profiles(session, event_id, [me, peer])
    mine, theirs = people.get(me), people.get(peer)
    goal = mine.goals[0].raw_input if mine and mine.goals else None
    lines = [
        f"{'USER' if is_mine else 'OTHER'}: {ai.user_data('message', text)}"
        for is_mine, text in history
    ]
    prompt = "\n".join(
        [
            f"ACTION: {data.action}",
            f"TONE: {data.tone or 'professional'}",
            f"User's goal: {ai.user_data('goal', goal)}",
            f"Other person: {ai.user_data('other_card', theirs.headline if theirs else None)}",
            "Conversation so far:",
            *(lines or ["(no messages yet)"]),
            f"User's draft: {ai.user_data('draft', data.text)}" if data.text else "",
        ]
    )
    return prompt, event_id


def _clean(options: list[str], want: int) -> list[str]:
    if any(o.strip() == "tone_unavailable" for o in options):
        raise ToneUnavailable
    out = [
        ai.validators.clamp(o, 600)
        for o in options
        if o.strip() and not ai.validators.contains_contact_details(o)
    ]
    return out[:want]


async def assist(session: AsyncSession, me: str, premium: bool, data: AssistIn) -> list[str]:
    prompt, event_id = await _prompt(session, me, premium, data)
    try:
        result = await ai.run_task("chat_assist", prompt, user_id=me, event_id=event_id)
    except ai.AiUnavailable as e:
        raise WingmanUnavailable from e
    options = _clean(
        ai.parsed(result, ai.schemas.Options).options, 3 if data.action == "suggest_replies" else 1
    )
    if not options:
        raise WingmanUnavailable
    return options


async def assist_stream(
    session: AsyncSession, me: str, premium: bool, data: AssistIn
) -> AsyncIterator[str]:
    """Server-sent events for draft and rewrite: `{"delta": ...}` chunks, then
    `{"done": true}`. Authorization and metering run before the first byte."""
    prompt, event_id = await _prompt(session, me, premium, data)
    stream = ai.stream_task("chat_assist", prompt, user_id=me, event_id=event_id)

    async def events() -> AsyncIterator[str]:
        text = ""
        try:
            async for chunk in stream:
                text += chunk
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except ai.AiUnavailable:
            yield f"data: {json.dumps({'error': 'ai_unavailable'})}\n\n"
            return
        # the client must discard a draft that leaked contact details or broke tone
        rejected = (
            ai.validators.contains_contact_details(text) or text.strip() == "tone_unavailable"
        )
        yield f"data: {json.dumps({'done': True, 'rejected': rejected})}\n\n"

    return events()
