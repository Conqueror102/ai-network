.PHONY: dev test lint fmt migrate revision seed evals worker
dev:      ; uv run uvicorn app.entrypoints.api:app --reload --port 8000
worker:   ; uv run arq app.entrypoints.worker.WorkerSettings
test:     ; uv run pytest -q
lint:     ; uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports
fmt:      ; uv run ruff check --fix . && uv run ruff format .
migrate:  ; uv run alembic upgrade head
revision: ; uv run alembic revision --autogenerate -m "$(m)"
seed:     ; uv run python -m scripts.seed_event $(n)
evals:    ; uv run pytest -q tests/evals
