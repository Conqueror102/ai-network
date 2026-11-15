"""Builds the adapter selected by config for each port. Cached; tests can override."""

from typing import Any

from app.adapters.email.port import EmailSender
from app.adapters.embeddings.port import EmbeddingProvider
from app.adapters.llm.port import LLMProvider
from app.adapters.otp.port import OtpSender
from app.adapters.payments.port import PaymentProvider
from app.adapters.push.port import PushSender
from app.adapters.storage.port import ObjectStorage
from app.adapters.tracing.port import AiTracer
from app.core.config import get_settings

_cache: dict[str, Any] = {}


def _req(value: Any, name: str) -> str:
    if value is None:
        raise RuntimeError(f"missing required setting: {name}")
    return str(value.get_secret_value() if hasattr(value, "get_secret_value") else value)


def override(port: str, adapter: Any) -> None:
    _cache[port] = adapter


def reset() -> None:
    _cache.clear()


def _install_fake_responders(fake: Any) -> None:
    """Responders live with the AI module's task definitions; loaded lazily to keep
    adapters free of module imports at import time."""
    import importlib

    importlib.import_module("app.modules.ai.fakes").install(fake)


def llm_providers() -> dict[str, LLMProvider]:
    """All configured LLM providers by name; routing picks per model (06 §1a)."""
    if "llm" not in _cache:
        s = get_settings()
        providers: dict[str, LLMProvider] = {}
        if s.llm_provider == "fake":
            from app.adapters.llm.fake import FakeLLM

            fake = FakeLLM()
            providers["fake"] = fake
            _install_fake_responders(fake)
        else:
            from app.adapters.llm.anthropic import AnthropicProvider

            providers["anthropic"] = AnthropicProvider(
                s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None
            )
            if s.openai_compat_base_url and s.openai_compat_api_key:
                from app.adapters.llm.openai_compat import OpenAICompatProvider

                providers["openai_compat"] = OpenAICompatProvider(
                    s.openai_compat_base_url, s.openai_compat_api_key.get_secret_value()
                )
        _cache["llm"] = providers
    return _cache["llm"]  # type: ignore[no-any-return]


def embeddings() -> EmbeddingProvider:
    if "embeddings" not in _cache:
        s = get_settings()
        if s.embeddings_provider == "voyage":
            from app.adapters.embeddings.voyage import VoyageEmbeddings

            _cache["embeddings"] = VoyageEmbeddings(_req(s.voyage_api_key, "VOYAGE_API_KEY"))
        else:
            from app.adapters.embeddings.fake import FakeEmbeddings

            _cache["embeddings"] = FakeEmbeddings()
    return _cache["embeddings"]  # type: ignore[no-any-return]


def _otp(name: str) -> OtpSender:
    s = get_settings()
    if name == "termii":
        from app.adapters.otp.termii import TermiiOtp

        return TermiiOtp(_req(s.termii_api_key, "TERMII_API_KEY"), s.termii_sender_id)
    if name == "twilio":
        from app.adapters.otp.twilio_sms import TwilioSmsOtp

        return TwilioSmsOtp(
            _req(s.twilio_account_sid, "TWILIO_ACCOUNT_SID"),
            _req(s.twilio_auth_token, "TWILIO_AUTH_TOKEN"),
            _req(s.twilio_verify_service_sid, "TWILIO_VERIFY_SERVICE_SID"),
        )
    from app.adapters.otp.fake import FakeOtp

    return FakeOtp(name)


def otp_senders() -> list[OtpSender]:
    """Primary first, then fallback."""
    if "otp" not in _cache:
        s = get_settings()
        senders = [_otp(s.otp_primary)]
        if s.otp_fallback:
            senders.append(_otp(s.otp_fallback))
        _cache["otp"] = senders
    return _cache["otp"]  # type: ignore[no-any-return]


def email() -> EmailSender:
    if "email" not in _cache:
        s = get_settings()
        if s.email_provider == "resend":
            from app.adapters.email.resend import ResendEmail

            _cache["email"] = ResendEmail(_req(s.resend_api_key, "RESEND_API_KEY"), s.email_from)
        else:
            from app.adapters.email.fake import FakeEmail

            _cache["email"] = FakeEmail()
    return _cache["email"]  # type: ignore[no-any-return]


def push() -> PushSender:
    if "push" not in _cache:
        s = get_settings()
        if s.push_provider == "webpush":
            from app.adapters.push.webpush import WebPushSender

            _cache["push"] = WebPushSender(
                _req(s.vapid_private_key, "VAPID_PRIVATE_KEY"), s.vapid_subject
            )
        else:
            from app.adapters.push.fake import FakePush

            _cache["push"] = FakePush()
    return _cache["push"]  # type: ignore[no-any-return]


def storage() -> ObjectStorage:
    if "storage" not in _cache:
        s = get_settings()
        if s.storage_provider == "r2":
            from app.adapters.storage.r2 import R2Storage

            _cache["storage"] = R2Storage(
                _req(s.r2_account_id, "R2_ACCOUNT_ID"),
                _req(s.r2_access_key_id, "R2_ACCESS_KEY_ID"),
                _req(s.r2_secret_access_key, "R2_SECRET_ACCESS_KEY"),
                s.r2_bucket,
                s.cdn_base_url,
            )
        else:
            from app.adapters.storage.fake import FakeStorage

            _cache["storage"] = FakeStorage()
    return _cache["storage"]  # type: ignore[no-any-return]


def tracer() -> AiTracer:
    if "tracer" not in _cache:
        s = get_settings()
        if s.tracing_provider == "langfuse":
            from app.adapters.tracing.langfuse import LangfuseTracer

            _cache["tracer"] = LangfuseTracer(
                _req(s.langfuse_public_key, "LANGFUSE_PUBLIC_KEY"),
                _req(s.langfuse_secret_key, "LANGFUSE_SECRET_KEY"),
                s.langfuse_host,
            )
        else:
            from app.adapters.tracing.noop import NoopTracer

            _cache["tracer"] = NoopTracer()
    return _cache["tracer"]  # type: ignore[no-any-return]


def payments() -> PaymentProvider:
    if "payments" not in _cache:
        s = get_settings()
        if s.payments_provider == "bachs":
            from app.adapters.payments.bachs import BachsPayments

            _cache["payments"] = BachsPayments(
                _req(s.bachs_api_key, "BACHS_API_KEY"),
                _req(s.bachs_webhook_secret, "BACHS_WEBHOOK_SECRET"),
                s.bachs_base_url,
            )
        else:
            from app.adapters.payments.fake import FakePayments

            _cache["payments"] = FakePayments()
    return _cache["payments"]  # type: ignore[no-any-return]
