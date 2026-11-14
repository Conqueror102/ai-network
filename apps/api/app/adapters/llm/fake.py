"""Deterministic in-memory LLM for dev and tests.

Responders are registered per task (see modules/ai/fakes.py). Tests can script
failures with `fail_models` / `down` to exercise fallbacks and breakers.
"""

from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel

from app.adapters.llm.port import LLMError, LLMResult, Message

Responder = Callable[[list[Message], type[BaseModel] | None], Any]


class FakeLLM:
    name = "fake"

    def __init__(self) -> None:
        self.responders: dict[str, Responder] = {}
        self.calls: list[dict[str, Any]] = []
        self.down = False
        self.fail_models: set[str] = set()

    def reset(self) -> None:
        self.calls.clear()
        self.down = False
        self.fail_models.clear()

    def _respond(
        self,
        task: str,
        model: str,
        system: str,
        messages: list[Message],
        schema: type[BaseModel] | None,
    ) -> Any:
        self.calls.append({"task": task, "model": model, "system": system, "messages": messages})
        if self.down or model in self.fail_models:
            raise LLMError("fake outage")
        responder = self.responders.get(task)
        if responder is None:
            raise LLMError(f"no fake responder for task {task}")
        return responder(messages, schema)

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
        out = self._respond(task, model, system, messages, schema)
        if isinstance(out, BaseModel):
            return LLMResult(
                text=out.model_dump_json(),
                parsed=out,
                model=model,
                input_tokens=100,
                output_tokens=20,
            )
        return LLMResult(
            text=str(out), parsed=None, model=model, input_tokens=100, output_tokens=20
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
        out = str(self._respond(task, model, system, messages, None))
        for word in out.split(" "):
            yield word + " "
