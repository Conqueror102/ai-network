"""The only AI surface other modules may import (00 §4)."""

from app.adapters.llm.port import LLMResult, Message
from app.modules.ai import schemas, validators
from app.modules.ai.budget import consume_daily_assist, event_spend
from app.modules.ai.errors import AiUnavailable
from app.modules.ai.service import embed, parsed, run_task, screen, stream_task, user_data

__all__ = [
    "AiUnavailable",
    "LLMResult",
    "Message",
    "consume_daily_assist",
    "embed",
    "event_spend",
    "parsed",
    "run_task",
    "schemas",
    "screen",
    "stream_task",
    "user_data",
    "validators",
]
