"""Pluggable, provider-agnostic LLM layer.

``LLMProvider`` is a thin text-completion contract so the tailoring service owns
prompt-building and response parsing. ``get_llm_provider`` selects the adapter from
settings (no global singleton).
"""

from __future__ import annotations

from cinch.core.config import LLMProviderName, Settings
from cinch.providers.llm.anthropic import AnthropicProvider
from cinch.providers.llm.base import LLMError, LLMProvider
from cinch.providers.llm.fake import FakeLLMProvider
from cinch.providers.llm.groq import GroqProvider

__all__ = [
    "AnthropicProvider",
    "FakeLLMProvider",
    "GroqProvider",
    "LLMError",
    "LLMProvider",
    "get_llm_provider",
]


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Return the configured LLM provider adapter.

    Args:
        settings: Application settings (carries ``llm_provider`` + credentials).

    Raises:
        LLMError: If the selected provider has no adapter yet, or credentials are missing.
    """
    if settings.llm_provider is LLMProviderName.ANTHROPIC:
        return AnthropicProvider.from_settings(settings)
    if settings.llm_provider is LLMProviderName.GROQ:
        return GroqProvider.from_settings(settings)
    # OpenAI / Google adapters arrive in a later iteration; fail loudly, not silently.
    raise LLMError(f"No LLM adapter implemented for provider: {settings.llm_provider.value}")
