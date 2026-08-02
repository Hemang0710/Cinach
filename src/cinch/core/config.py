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

    # --- Observability -----------------------------------------------------
    sentry_dsn: str | None = None

    @property
    def is_production(self) -> bool:
        """True when running in the production environment."""
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (dependency-injection friendly)."""
    return Settings()
