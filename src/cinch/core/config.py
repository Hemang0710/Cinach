"""Application configuration via pydantic-settings.

All configuration is sourced from environment variables (and, for local
development only, a ``.env`` file). Secrets are NEVER hard-coded or committed;
see ``.env.example`` for the full list of supported variables with placeholders.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property, lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cinch.core.logging import get_logger

logger = get_logger(__name__)


class LLMProviderName(StrEnum):
    """Supported LLM providers behind the provider-agnostic interface."""

    ANTHROPIC = "anthropic"
    GROQ = "groq"  # free, OpenAI-compatible (console.groq.com)
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
    # ASGI bind port. PaaS platforms (Render, Heroku, Cloud Run) inject ``PORT``.
    port: int = 8000

    # --- Database ----------------------------------------------------------
    # Local dev defaults to SQLite (aiosqlite); production uses PostgreSQL
    # (asyncpg), e.g. postgresql+asyncpg://user:pass@host:5432/cinch
    database_url: str = "sqlite+aiosqlite:///./cinch.db"

    # --- Telegram ----------------------------------------------------------
    telegram_bot_token: str | None = None
    # Comma-separated Telegram user ids permitted to register (Phase 14). EMPTY
    # means OPEN — anyone who messages the bot may register (backward-compatible).
    # Set it to lock a self-hosted deploy to its owner(s) so strangers can't spend
    # your LLM / job-API quota. Only gates *registration*; existing users are
    # unaffected. See ``is_telegram_id_allowed``.
    allowed_telegram_ids: str = ""
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
    # Groq: free & OpenAI-compatible. Set llm_provider=groq, a Llama model as
    # llm_model (e.g. "llama-3.3-70b-versatile"), and groq_api_key.
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Model id for the active provider. Defaults to a current Claude model; when
    # llm_provider is not Anthropic, set this to that provider's model id.
    # NOTE: current Claude models reject temperature/top_p/top_k (they 400), so
    # tailoring faithfulness is steered via the prompt, not a sampling knob.
    llm_model: str = "claude-opus-4-8"
    llm_max_tokens: int = 4096

    # --- Job sources -------------------------------------------------------
    # Comma-separated names from ``JobSourceName``. Common values:
    #   adzuna,remoteok,arbeitnow  -> fans out to all three (CompositeJobSource)
    #   remoteok,arbeitnow         -> free-only, no Adzuna signup needed
    # A source with missing credentials is logged and skipped, so a partial
    # config still yields a working pipeline (as long as at least one succeeds).
    job_sources: str = "adzuna"
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

    # --- Ghosted sweep (Phase 12) ------------------------------------------
    # A SUBMITTED application silent past ``ghosted_after_days`` is flagged
    # GHOSTED so a long-dead application stops reading as "still in play". OFF
    # unless explicitly enabled, like the other schedulers. Default interval is
    # daily (1440 min) — this is housekeeping, not a hot loop.
    ghosted_sweep_enabled: bool = False
    ghosted_after_days: int = 30
    ghosted_sweep_interval_minutes: int = 1440

    # --- Email webhook (Phase 11 → per-user in Phase 14) -------------------
    # Auth for POST /webhook/email is now a PER-USER token in the
    # X-Cinch-Webhook-Secret header (issued by the bot's /emailhook command and
    # stored on the user row) — there is no global shared secret to configure.
    # Deterministic pre-LLM noise gate (Phase 13): drops job-alert digests and
    # marketing newsletters before the classifier runs — saving an LLM call and
    # removing false-advance risk. ON by default (the rules are high-precision);
    # set False to send every email to the LLM (Phase 11 behaviour).
    email_sanity_filter_enabled: bool = True

    # --- Security ----------------------------------------------------------
    # Fernet key for encrypting resume PII at rest. Generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    # When unset, resume content is stored plaintext (a startup warning is logged).
    encryption_key: str | None = None

    # --- Observability -----------------------------------------------------
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @field_validator("database_url")
    @classmethod
    def _ensure_async_pg_driver(cls, value: str) -> str:
        """Rewrite PaaS ``postgres[ql]://`` URLs to the async driver SQLAlchemy needs.

        Render/Heroku expose ``postgres://`` connection strings, but the async engine
        requires an explicit ``postgresql+asyncpg://`` driver. Already-qualified URLs
        (``…+asyncpg``, ``sqlite+aiosqlite``) pass through untouched.
        """
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

    @property
    def is_production(self) -> bool:
        """True when running in the production environment."""
        return self.environment == "production"

    @cached_property
    def allowed_telegram_id_set(self) -> frozenset[int]:
        """Parsed ``allowed_telegram_ids`` as a set of ints (empty ⇒ open bot).

        Tolerant of whitespace and stray commas; a non-integer entry is skipped
        with a warning rather than crashing startup on a fat-fingered config.
        """
        ids: set[int] = set()
        for raw in self.allowed_telegram_ids.split(","):
            token = raw.strip()
            if not token:
                continue
            try:
                ids.add(int(token))
            except ValueError:
                logger.warning("ignoring non-integer ALLOWED_TELEGRAM_IDS entry", entry=token)
        return frozenset(ids)

    def is_telegram_id_allowed(self, telegram_user_id: int) -> bool:
        """Whether ``telegram_user_id`` may register. Empty allowlist ⇒ always True."""
        allowed = self.allowed_telegram_id_set
        return not allowed or telegram_user_id in allowed


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (dependency-injection friendly)."""
    return Settings()
