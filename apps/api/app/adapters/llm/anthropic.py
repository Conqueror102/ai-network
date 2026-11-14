"""Anthropic adapter. The only place the `anthropic` SDK is imported."""

from collections.abc import AsyncIterator
from typing import Any, cast

import anthropic
from pydantic import BaseModel

from app.adapters.llm.port import LLMError, LLMRefused, LLMResult, Message


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        # max_retries=2 is the SDK default (06 §1); our routing chain handles the rest
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)

    @staticmethod
    def _system(system: str) -> list[dict[str, Any]]:
        # frozen system prompt + cache breakpoint; volatile content goes in the user turn
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    @staticmethod
    def _kwargs(effort: str | None) -> dict[str, Any]:
        return {"output_config": {"effort": effort}} if effort else {}

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
    ) -> LLMResult:
        client = self._client.with_options(timeout=timeout_s)
        try:
            if schema is not None:
                resp: Any = await client.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=cast(Any, self._system(system)),
                    messages=cast(Any, messages),
                    output_format=schema,
                    **self._kwargs(effort),
                )
                parsed = resp.parsed_output
            else:
                resp = await client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=cast(Any, self._system(system)),
                    messages=cast(Any, messages),
                    **self._kwargs(effort),
                )
                parsed = None
        except (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ) as e:
            raise LLMError(f"anthropic transient: {type(e).__name__}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic status {e.status_code}") from e
        if resp.stop_reason == "refusal":
            raise LLMRefused("refused")
        text = "".join(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        return LLMResult(
            text=text,
            parsed=parsed,
            model=model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            stop_reason=resp.stop_reason or "end_turn",
        )

    async def stream(
        self,
        *,
        task: str,
        model: str,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        timeout_s: float = 20.0,
        effort: str | None = None,
    ) -> AsyncIterator[str]:
        client = self._client.with_options(timeout=timeout_s)
        try:
            async with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=cast(Any, self._system(system)),
                messages=cast(Any, messages),
                **self._kwargs(effort),
            ) as stream:
                async for chunk in stream.text_stream:
                    yield chunk
                final = await stream.get_final_message()
                if final.stop_reason == "refusal":
                    raise LLMRefused("refused")
        except (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ) as e:
            raise LLMError(f"anthropic transient: {type(e).__name__}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"anthropic status {e.status_code}") from e
