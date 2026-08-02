"""Application configuration via pydantic-settings.

All configuration is sourced from environment variables (and, for local
development only, a ``.env`` file). Secrets are NEVER hard-coded or committed;
see ``.env.example`` for the full list of supported variables with placeholders.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProviderName(StrEnum):
    """Supported LLM providers behind the provider-agnostic interface."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables. Field names map to upper-case
    env keys (e.g. ``telegram_bot_token`` <- ``TELEGRAM_BOT_TOKEN``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---------------------------------------------------------------
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # --- Database ----------------------------------------------------------
    # Local dev defaults to SQLite (aiosqlite); production uses PostgreSQL
    # (asyncpg), e.g. postgresql+asyncpg://user:pass@host:5432/cinch
    database_url: str = "sqlite+aiosqlite:///./cinch.db"

    # --- Telegram ----------------------------------------------------------
    telegram_bot_token: str | None = None
    # Secret token echoed in the X-Telegram-Bot-Api-Secret-Token header and
    # verified (constant-time) on the webhook route.
    telegram_webhook_secret: str | None = None
    # Path the webhook is served on (relative to the app root).
    telegram_webhook_path: str = "/telegram/webhook"
    # Public HTTPS base URL of this app. When set, the webhook is registered with
    # Telegram on startup; leave unset for local development (no public URL).
    telegram_webhook_url: str | None = None

    # --- LLM providers -----------------------------------------------------
    llm_provider: LLMProviderName = LLMProviderName.ANTHROPIC
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    # Model id for the active provider. Defaults to a current Claude model; when
    # llm_provider is not Anthropic, set this to that provider's model id.
    # NOTE: current Claude models reject temperature/top_p/top_k (they 400), so
    # tailoring faithfulness is steered via the prompt, not a sampling knob.
    llm_model: str = "claude-opus-4-8"
    llm_max_tokens: int = 4096
    # Optional second-layer LLM grounding judge (off by default). The deterministic
    # validator is always the hard gate; the judge only adds semantic checks.
    grounding_use_llm_judge: bool = False

    # --- Job sources -------------------------------------------------------
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    adzuna_country: str = "us"  # Adzuna is country-scoped (us, gb, in, ...)
    adzuna_where: str | None = None  # optional global location filter

    # --- Discovery / scheduler ---------------------------------------------
    # The discovery scheduler is OFF unless explicitly enabled — nothing runs in
    # dev/tests inadvertently, and enabling it is a deliberate ops decision.
    discovery_enabled: bool = False
    discovery_interval_minutes: int = 60
    discovery_results_per_user: int = 5  # per cycle — politeness + rate-limit headroom

    # --- Assisted submission (Phase 6, EXPERIMENTAL) -----------------------
    # OFF by default. Auto-submitting to job sites may violate their Terms of
    # Service; only enable with explicit sign-off. Never bypasses CAPTCHAs/logins —
    # those hand back to the user. Only user-APPROVED applications are ever submitted.
    submission_enabled: bool = False
    submission_interval_minutes: int = 5
    submission_headless: bool = True
    submission_timeout_seconds: int = 60

    # --- Security ----------------------------------------------------------
    # Fernet key for encrypting resume PII at rest. Generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    # When unset, resume content is stored plaintext (a startup warning is logged).
    encryption_key: str | None = None

    # --- Observability -----------------------------------------------------
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @property
    def is_production(self) -> bool:
        """True when running in the production environment."""
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (dependency-injection friendly)."""
    return Settings()
