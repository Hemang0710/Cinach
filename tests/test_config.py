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
