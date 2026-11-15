"""OpenAI-compatible chat-completions adapter (OpenAI, Gemini-compat, open-weight servers).

Plain HTTP so no second vendor SDK is needed. Structured output uses JSON-schema
response_format and is validated with Pydantic before returning.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.adapters.llm.port import LLMError, LLMResult, Message


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers={"Authorization": f"Bearer {api_key}"}
        )

    def _body(
        self,
        model: str,
        system: str,
        messages: list[Message],
        max_tokens: int,
        schema: type[BaseModel] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                },
            }
        return body

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
        try:
            r = await self._http.post(
                "/chat/completions",
                timeout=timeout_s,
                json=self._body(model, system, messages, max_tokens, schema),
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"openai_compat: {type(e).__name__}") from e
        data = r.json()
        text = data["choices"][0]["message"].get("content") or ""
        parsed = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(text)
            except ValidationError as e:
                raise LLMError("openai_compat: schema validation failed") from e
        usage = data.get("usage", {})
        return LLMResult(
            text=text,
            parsed=parsed,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=data["choices"][0].get("finish_reason", "stop"),
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
        body = {**self._body(model, system, messages, max_tokens, None), "stream": True}
        try:
            async with self._http.stream(
                "POST", "/chat/completions", json=body, timeout=timeout_s
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    delta = json.loads(line[6:])["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except httpx.HTTPError as e:
            raise LLMError(f"openai_compat: {type(e).__name__}") from e
