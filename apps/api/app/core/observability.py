"""Sentry + Prometheus metrics (doc 11 §11). OpenTelemetry is opt-in via OTEL_* env."""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from app.core.config import Settings

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["route"])
WS_CONNECTIONS = Gauge("ws_connections", "Open WebSocket connections")
OUTBOX_LAG = Gauge("outbox_lag_seconds", "Age of oldest undelivered outbox row")
JOBS = Counter("jobs_total", "Background jobs", ["name", "outcome"])
AI_CALLS = Counter("ai_calls_total", "AI calls", ["task", "model", "outcome"])
AI_TOKENS = Counter("ai_tokens_total", "AI tokens", ["task", "direction"])
OTP_SENT = Counter("otp_sent_total", "OTP sends", ["provider", "outcome"])
CHECKINS = Counter("checkins_total", "Door check-ins")
WAVES = Counter("waves_total", "Waves", ["action"])


def init_sentry(settings: Settings) -> None:
    if settings.sentry_dsn is None:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.env,
        release=settings.release,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )


def init_tracing(app: object) -> None:
    """Enable OpenTelemetry if the optional packages are installed (`uv sync --extra otel`)."""
    try:
        from opentelemetry.instrumentation.fastapi import (  # type: ignore[import-not-found]
            FastAPIInstrumentor,
        )
    except ImportError:
        return
    FastAPIInstrumentor.instrument_app(app)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
