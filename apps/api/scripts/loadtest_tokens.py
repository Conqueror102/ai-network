"""Issue access tokens for seeded attendees so k6 can act as real users (09 §5).

    uv run python -m scripts.loadtest_tokens evt_... > ../../infra/k6/tokens.json

Run it with the target environment's settings (staging). It refuses `ENV=prod`:
production is never load tested with minted tokens.
"""

import asyncio
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db.uow import UnitOfWork
from app.core.security.jwt import issue_access_token
from app.modules.profiles.models import EventProfile


async def main(event_id: str, limit: int) -> None:
    if get_settings().env == "prod":
        sys.exit("refusing to mint load-test tokens in prod")
    async with UnitOfWork() as session:
        user_ids = (
            await session.scalars(
                select(EventProfile.user_id).where(EventProfile.event_id == event_id).limit(limit)
            )
        ).all()
    if not user_ids:
        sys.exit(f"no attendees found for {event_id}; run `make seed` first")
    users = [{"id": uid, "token": issue_access_token(uid)} for uid in user_ids]
    json.dump({"event_id": event_id, "users": users}, sys.stdout)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m scripts.loadtest_tokens <event_id> [limit]")
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 500))
