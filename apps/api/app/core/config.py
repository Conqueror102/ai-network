"""Single source of configuration (doc 11 §6). No os.getenv anywhere else."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-secret-change-me-dev-only-secret"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "staging", "prod"] = "dev"
    role: Literal["api", "ws", "worker", "scheduler"] = "api"
    release: str = "dev"

    database_url: str = "postgresql+asyncpg://postgres@localhost:5432/ainet"
    database_pooled: bool = False  # True behind PgBouncer (Neon pooled URL)
    db_pool_size: int = 10
    db_statement_timeout_ms: int = 5000
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: SecretStr = SecretStr(DEV_SECRET)
    jwt_secret_next: SecretStr | None = None
    jwt_kid: str = "k1"
    jwt_kid_next: str = "k2"
    jwt_issuer: str = "ainet-api"
    jwt_audience: str = "ainet"
    access_ttl_s: int = 900
    refresh_ttl_s: int = 30 * 24 * 3600
    otp_pepper: SecretStr = SecretStr(DEV_SECRET)
    otp_ttl_s: int = 600
    otp_max_attempts: int = 5
    otp_sms_country_allowlist: list[str] = Field(default_factory=lambda: ["+234"])
    msg_enc_key: SecretStr = SecretStr("00" * 32)  # hex, 32 bytes
    msg_enc_kid: str = "m1"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_hosts: list[str] = Field(default_factory=lambda: ["*"])
    max_body_bytes: int = 1_000_000
    staff_ip_allowlist: list[str] = Field(default_factory=list)

    # adapter selection: "fake" or a vendor name
    llm_provider: str = "fake"
    embeddings_provider: str = "fake"
    otp_primary: str = "fake"
    otp_fallback: str | None = None
    email_provider: str = "fake"
    push_provider: str = "fake"
    payments_provider: str = "fake"
    storage_provider: str = "fake"
    tracing_provider: str = "noop"
    turnstile_enabled: bool = False

    anthropic_api_key: SecretStr | None = None
    openai_compat_api_key: SecretStr | None = None
    openai_compat_base_url: str | None = None
    voyage_api_key: SecretStr | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    termii_api_key: SecretStr | None = None
    termii_sender_id: str = "AiNetwork"
    twilio_account_sid: SecretStr | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_verify_service_sid: str | None = None
    resend_api_key: SecretStr | None = None
    email_from: str = "AiNetwork <no-reply@example.com>"
    turnstile_secret: SecretStr | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:ops@example.com"
    bachs_api_key: SecretStr | None = None
    bachs_webhook_secret: SecretStr | None = None
    bachs_base_url: str = "https://api.bachs.io"
    r2_account_id: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str = "ainet-media"
    cdn_base_url: str = "https://cdn.example.com"
    sentry_dsn: SecretStr | None = None

    # AI routing: task -> model chain (06 §1a). Overridable via env JSON.
    ai_routing: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "safety_screen": ["small"],
            "match_explainer": ["small"],
            "goal_parser": ["mid", "small"],
            "icebreakers": ["mid", "small"],
            "chat_assist": ["mid", "small"],
            "followup_drafts": ["mid"],
            "meeting_brief": ["mid"],
        }
    )
    ai_models: dict[str, str] = Field(
        default_factory=lambda: {"small": "claude-haiku-5-5", "mid": "claude-sonnet-5-5"}
    )
    ai_event_budget_usd: float = 150.0
    ai_user_daily_assist_cap: int = 50

    flags: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _prod_guards(self) -> "Settings":
        if self.env in ("staging", "prod"):
            problems = []
            if self.jwt_secret.get_secret_value() == DEV_SECRET:
                problems.append("JWT_SECRET is the dev default")
            if self.otp_pepper.get_secret_value() == DEV_SECRET:
                problems.append("OTP_PEPPER is the dev default")
            if self.msg_enc_key.get_secret_value() == "00" * 32:
                problems.append("MSG_ENC_KEY is the dev default")
            if self.env == "prod":
                for name in ("llm_provider", "otp_primary", "storage_provider"):
                    if getattr(self, name) == "fake":
                        problems.append(f"{name.upper()} is fake")
            if problems:
                raise ValueError("unsafe configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
