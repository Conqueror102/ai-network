"""One place that knows every module: routers, models, jobs, event handlers."""

import importlib

from fastapi import FastAPI

MODULES: list[str] = [
    "ai",
    "identity",
    "organizers",
    "events",
    "safety",
    "profiles",
    "connections",
    "matching",
    "chat",
    "waves",
]


def _try_import(path: str) -> object | None:
    try:
        return importlib.import_module(path)
    except ModuleNotFoundError as e:
        if e.name == path:
            return None
        raise


def load_models() -> None:
    """Import every module's models so Base.metadata is complete (Alembic, tests)."""
    importlib.import_module("app.core.outbox")
    for name in MODULES:
        _try_import(f"app.modules.{name}.models")


def load_handlers() -> None:
    """Import jobs and event handlers so they register themselves."""
    for name in MODULES:
        _try_import(f"app.modules.{name}.jobs")
        _try_import(f"app.modules.{name}.handlers")


def mount_routers(app: FastAPI, role: str) -> None:
    load_models()
    load_handlers()
    for name in MODULES:
        mod = _try_import(f"app.modules.{name}.router")
        if mod is None:
            continue
        if role in ("api",) and hasattr(mod, "router"):
            app.include_router(mod.router, prefix="/v1")
        if hasattr(mod, "ws_router"):
            app.include_router(mod.ws_router, prefix="/v1")
