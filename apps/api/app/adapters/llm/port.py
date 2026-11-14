"""LLMProvider port (06 §1a). Business code never imports a vendor SDK."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    stop_reason: str = "end_turn"


class LLMError(Exception):
    """Provider failure (timeout, 5xx, rate limit, connection). Retryable on another model."""


class LLMRefused(LLMError):
    """The model declined the request."""


Message = dict[str, Any]


class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        *,
        task: str,
        model: str,
        system: str,
        messages: list[Message],
        schema: type[BaseModel] | None = None,
        max_tokens: int = 1024,
        timeout_s: float = 5.0,
        effort: str | None = None,
    ) -> LLMResult: ...

    def stream(
        self,
        *,
        task: str,
        model: str,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        timeout_s: float = 20.0,
        effort: str | None = None,
    ) -> AsyncIterator[str]: ...
