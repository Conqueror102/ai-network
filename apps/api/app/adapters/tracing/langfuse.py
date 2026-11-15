"""Langfuse tracing (06 §6). PII is masked before anything leaves the process."""

from typing import Any

import structlog
from langfuse import Langfuse

from app.core.logging import scrub

log = structlog.get_logger()


class LangfuseTracer:
    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        self._lf = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    def record(
        self,
        *,
        name: str,
        model: str,
        input: Any,
        output: Any,
        metadata: dict[str, Any],
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        ok: bool,
    ) -> None:
        try:
            gen = self._lf.start_observation(
                name=name,
                as_type="generation",
                model=model,
                input=scrub(input),
                output=scrub(output),
                metadata=metadata,
                usage_details={"input": input_tokens, "output": output_tokens},
                cost_details={"total": cost_usd},
                level="DEFAULT" if ok else "ERROR",
            )
            gen.end()
        except Exception:  # noqa: BLE001 - tracing must never break a request
            log.warning("langfuse_record_failed")

    def flush(self) -> None:
        self._lf.flush()
