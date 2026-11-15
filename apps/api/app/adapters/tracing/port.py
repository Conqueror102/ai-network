from typing import Any, Protocol


class AiTracer(Protocol):
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
    ) -> None: ...

    def flush(self) -> None: ...
