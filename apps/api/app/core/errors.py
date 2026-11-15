"""Domain error hierarchy and the single error envelope (00 §4, doc 11 §10)."""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger()


class DomainError(Exception):
    code = "error"
    status = 400
    message = "Request failed"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or self.code
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class NotFound(DomainError):
    code, status, message = "not_found", 404, "Not found"


class Forbidden(DomainError):
    code, status, message = "forbidden", 403, "Forbidden"


class Unauthenticated(DomainError):
    code, status, message = "unauthenticated", 401, "Authentication required"


class Conflict(DomainError):
    code, status, message = "conflict", 409, "Conflict"


class ValidationFailed(DomainError):
    code, status, message = "validation_error", 422, "Validation failed"


class RateLimited(DomainError):
    code, status, message = "rate_limited", 429, "Too many requests"

    def __init__(
        self, message: str | None = None, *, code: str | None = None, retry_after_s: int = 60
    ) -> None:
        super().__init__(message, code=code, details={"retry_after_s": retry_after_s})


class DependencyUnavailable(DomainError):
    code, status, message = "dependency_unavailable", 503, "A dependency is unavailable"


class DependencyRejected(DomainError):
    code, status, message = "dependency_rejected", 502, "A dependency rejected the request"


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        headers = {}
        if isinstance(exc, RateLimited):
            headers["Retry-After"] = str(exc.details.get("retry_after_s", 60))
        return JSONResponse(
            envelope(exc.code, exc.message, exc.details), exc.status, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"path": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            envelope("validation_error", "Validation failed", {"fields": fields}), 422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            404: "not_found",
            405: "method_not_allowed",
            401: "unauthenticated",
            403: "forbidden",
        }.get(exc.status_code, "http_error")
        return JSONResponse(envelope(code, str(exc.detail)), exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(envelope("internal_error", "Internal error", {"request_id": rid}), 500)
