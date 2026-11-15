from typing import Any


class NoopTracer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kw: Any) -> None:
        self.records.append(kw)

    def flush(self) -> None:
        return None
