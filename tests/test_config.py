"""Tests for configuration loading."""

from __future__ import annotations

from cinch.core.config import LLMProviderName, Settings


def test_defaults_are_local_and_safe() -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "local"
    assert settings.is_production is False
    assert settings.llm_provider is LLMProviderName.ANTHROPIC
    # No secrets are baked into defaults.
    assert settings.telegram_bot_token is None
    assert settings.anthropic_api_key is None


def test_production_flag() -> None:
    settings = Settings(_env_file=None, environment="production")
    assert settings.is_production is True


def test_database_url_normalizes_paas_scheme() -> None:
    # Render/Heroku hand out postgres[ql]:// URLs; the async engine needs +asyncpg.
    assert (
        Settings(_env_file=None, database_url="postgres://u:p@h:5432/db").database_url
        == "postgresql+asyncpg://u:p@h:5432/db"
    )
    assert (
        Settings(_env_file=None, database_url="postgresql://u:p@h/db").database_url
        == "postgresql+asyncpg://u:p@h/db"
    )


def test_database_url_left_untouched_when_explicit() -> None:
    for url in ("postgresql+asyncpg://u:p@h/db", "sqlite+aiosqlite:///./x.db"):
        assert Settings(_env_file=None, database_url=url).database_url == url
