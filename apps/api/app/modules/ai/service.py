"""AI task runner: routing chain, breaker, fallbacks, kill switches, audit, tracing."""

import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from app.adapters import factory
from app.adapters.embeddings.port import EmbeddingError
from app.adapters.llm.port import LLMError, LLMProvider, LLMRefused, LLMResult, Message
from app.core import flags
from app.core.config import get_settings
from app.core.db.uow import UnitOfWork
from app.core.ids import new_id
from app.core.observability import AI_CALLS, AI_TOKENS
from app.modules.ai import breaker, budget
from app.modules.ai.errors import AiUnavailable
from app.modules.ai.models import AiCall
from app.modules.ai.prompts import TASKS, TaskSpec
from app.modules.ai.schemas import SafetyVerdict

log = structlog.get_logger()


def user_data(source: str, text: str | None) -> str:
    """Wrap user-authored text so prompts treat it as data (06 §2)."""
    safe = (text or "").replace("<user_data", "<user-data").replace("</user_data", "</user-data")
    return f'<user_data source="{source}">{safe}</user_data>'


def resolve_chain(task: str) -> list[tuple[LLMProvider, str]]:
    """task -> [(provider, model id), ...] from config. No code change to switch models."""
    s = get_settings()
    providers = factory.llm_providers()
    chain: list[tuple[LLMProvider, str]] = []
    for entry in s.ai_routing.get(task, ["mid"]):
        provider_name, _, model = entry.rpartition(":")
        model = s.ai_models.get(model, model)
        if "fake" in providers:
            chain.append((providers["fake"], model))
        elif provider_name:
            chain.append((providers[provider_name], model))
        elif model.startswith("claude"):
            chain.append((providers["anthropic"], model))
        else:
            chain.append((providers["openai_compat"], model))
    return chain


async def _spec(task: str) -> tuple[TaskSpec, str, str]:
    spec = TASKS[task]
    version = await flags.get_value(f"ai.prompt.{task}", spec.default_version)
    if version not in spec.prompts:
        version = spec.default_version
    return spec, version, spec.prompts[version]


async def _audit(
    *,
    task: str,
    version: str,
    provider: str,
    model: str,
    user_id: str | None,
    event_id: str | None,
    result: LLMResult | None,
    latency_ms: int,
    outcome: str,
    error: str | None,
    input_preview: Any,
) -> None:
    it = result.input_tokens if result else 0
    ot = result.output_tokens if result else 0
    usd = budget.cost_usd(model, it, ot)
    ctx = structlog.contextvars.get_contextvars()
    try:
        async with UnitOfWork() as session:
            session.add(
                AiCall(
                    id=new_id("aic"),
                    task=f"{task}:{version}",
                    provider=provider,
                    model=model,
                    user_id=user_id,
                    event_id=event_id,
                    request_id=ctx.get("request_id"),
                    input_tokens=it,
                    output_tokens=ot,
                    cache_read_tokens=result.cache_read_tokens if result else 0,
                    latency_ms=latency_ms,
                    cost_usd=usd,
                    outcome=outcome,
                    ok=outcome == "ok",
                    error=error,
                )
            )
    except Exception:
        log.exception("ai_audit_failed")
    AI_CALLS.labels(task, model, outcome).inc()
    AI_TOKENS.labels(task, "input").inc(it)
    AI_TOKENS.labels(task, "output").inc(ot)
    total = await budget.add_event_spend(event_id, usd)
    if event_id and total >= get_settings().ai_event_budget_usd:
        log.warning("ai_event_budget_exceeded", event_id=event_id, spend_usd=round(total, 2))
    factory.tracer().record(
        name=f"{task}:{version}",
        model=model,
        input=input_preview,
        output=result.text if result else None,
        metadata={
            "task": task,
            "provider": provider,
            "outcome": outcome,
            "user_id": user_id,
            "event_id": event_id,
            "request_id": ctx.get("request_id"),
        },
        input_tokens=it,
        output_tokens=ot,
        cost_usd=usd,
        ok=outcome == "ok",
    )


async def run_task(
    task: str,
    content: str | list[Message],
    *,
    user_id: str | None = None,
    event_id: str | None = None,
) -> LLMResult:
    """Run a registered task through its model chain. Raises AiUnavailable when every
    model fails, the task is switched off, or the event is over its AI budget. Callers
    own the product fallback (template, manual form, "wingman unavailable")."""
    if not await flags.is_enabled(f"ai.task.{task}", True):
        raise AiUnavailable(details={"reason": "disabled"})
    if await budget.event_over_budget(event_id) and task != "safety_screen":
        raise AiUnavailable(details={"reason": "event_budget"})
    spec, version, system = await _spec(task)
    messages: list[Message] = (
        [{"role": "user", "content": content}] if isinstance(content, str) else content
    )
    for provider, model in resolve_chain(task):
        if await breaker.is_open(model):
            continue
        for attempt in (1, 2):  # invalid structured output => one retry, then next model
            start = time.perf_counter()
            try:
                result = await provider.complete(
                    task=task,
                    model=model,
                    system=system,
                    messages=messages,
                    schema=spec.schema,
                    max_tokens=spec.max_tokens,
                    timeout_s=spec.timeout_s,
                    effort=spec.effort,
                )
                if spec.schema is not None and result.parsed is None:
                    raise LLMError("no structured output")
            except LLMRefused:
                await _audit(
                    task=task,
                    version=version,
                    provider=provider.name,
                    model=model,
                    user_id=user_id,
                    event_id=event_id,
                    result=None,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    outcome="refused",
                    error=None,
                    input_preview=messages,
                )
                break
            except LLMError as e:
                await _audit(
                    task=task,
                    version=version,
                    provider=provider.name,
                    model=model,
                    user_id=user_id,
                    event_id=event_id,
                    result=None,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    outcome="error",
                    error=str(e)[:300],
                    input_preview=messages,
                )
                if "structured" in str(e) and attempt == 1:
                    continue
                await breaker.record_failure(model)
                break
            await breaker.record_success(model)
            await _audit(
                task=task,
                version=version,
                provider=provider.name,
                model=model,
                user_id=user_id,
                event_id=event_id,
                result=result,
                latency_ms=int((time.perf_counter() - start) * 1000),
                outcome="ok",
                error=None,
                input_preview=messages,
            )
            return result
    raise AiUnavailable


async def stream_task(
    task: str,
    content: str | list[Message],
    *,
    user_id: str | None = None,
    event_id: str | None = None,
) -> AsyncIterator[str]:
    """Streaming variant (wingman). Falls through the chain only before the first token."""
    if not await flags.is_enabled(f"ai.task.{task}", True):
        raise AiUnavailable(details={"reason": "disabled"})
    spec, version, system = await _spec(task)
    messages: list[Message] = (
        [{"role": "user", "content": content}] if isinstance(content, str) else content
    )
    for provider, model in resolve_chain(task):
        if await breaker.is_open(model):
            continue
        start = time.perf_counter()
        chunks: list[str] = []
        try:
            async for chunk in provider.stream(
                task=task,
                model=model,
                system=system,
                messages=messages,
                max_tokens=spec.max_tokens,
                effort=spec.effort,
            ):
                chunks.append(chunk)
                yield chunk
        except LLMError as e:
            await breaker.record_failure(model)
            await _audit(
                task=task,
                version=version,
                provider=provider.name,
                model=model,
                user_id=user_id,
                event_id=event_id,
                result=None,
                latency_ms=int((time.perf_counter() - start) * 1000),
                outcome="error",
                error=str(e)[:300],
                input_preview=messages,
            )
            if chunks:
                return  # partial output already sent; client keeps what it has
            continue
        await breaker.record_success(model)
        text = "".join(chunks)
        await _audit(
            task=task,
            version=version,
            provider=provider.name,
            model=model,
            user_id=user_id,
            event_id=event_id,
            result=LLMResult(text=text, parsed=None, model=model, output_tokens=len(text) // 4),
            latency_ms=int((time.perf_counter() - start) * 1000),
            outcome="ok",
            error=None,
            input_preview=messages,
        )
        return
    raise AiUnavailable


async def screen(
    text: str, *, kind: str, user_id: str | None = None, event_id: str | None = None
) -> SafetyVerdict:
    """Safety gate (06 §4.6). Raises AiUnavailable when it cannot decide; callers must
    fail closed (drop the note, hold the content) rather than pass unscreened text."""
    if not text.strip():
        return SafetyVerdict(allow=True, category="none", confidence=1.0)
    result = await run_task(
        "safety_screen",
        f"Kind: {kind}\n{user_data(kind, text)}",
        user_id=user_id,
        event_id=event_id,
    )
    verdict = result.parsed
    assert isinstance(verdict, SafetyVerdict)
    if verdict.category != "none":
        verdict.allow = False
    return verdict


async def embed(
    texts: list[str], *, input_type: Literal["query", "document"]
) -> tuple[list[list[float]], str]:
    """Returns (vectors, embedding model name). Vectors from different models never mix."""
    provider = factory.embeddings()
    try:
        return await provider.embed(texts, input_type=input_type), provider.model
    except EmbeddingError as e:
        raise AiUnavailable(details={"reason": "embeddings"}) from e


def parsed(result: LLMResult, schema: type[BaseModel]) -> Any:
    assert isinstance(result.parsed, schema)
    return result.parsed
