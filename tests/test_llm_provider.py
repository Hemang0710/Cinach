"""Tests for the LLM provider layer — all mocked, no live API calls."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from anthropic import APIError, AsyncAnthropic
from anthropic.types import TextBlock
from openai import APIError as OpenAIAPIError
from openai import AsyncOpenAI

from cinch.core.config import LLMProviderName, Settings
from cinch.providers.llm import get_llm_provider
from cinch.providers.llm.anthropic import AnthropicProvider
from cinch.providers.llm.base import LLMError
from cinch.providers.llm.fake import FakeLLMProvider
from cinch.providers.llm.groq import GroqProvider


def _message(text: str, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    block = TextBlock(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def _client_returning(message: object) -> AsyncAnthropic:
    client = Mock()
    client.messages.create = AsyncMock(return_value=message)
    return cast(AsyncAnthropic, client)


async def test_anthropic_complete_returns_text() -> None:
    provider = AnthropicProvider(_client_returning(_message("Hello there")), "claude-opus-4-8")
    assert await provider.complete(system="s", user="u", max_tokens=64) == "Hello there"


async def test_anthropic_refusal_raises() -> None:
    client = _client_returning(_message("", stop_reason="refusal"))
    provider = AnthropicProvider(client, "claude-opus-4-8")
    with pytest.raises(LLMError):
        await provider.complete(system="s", user="u", max_tokens=64)


async def test_anthropic_api_error_becomes_llm_error() -> None:
    client = Mock()
    err = APIError("boom", request=httpx.Request("POST", "https://api.anthropic.com"), body=None)
    client.messages.create = AsyncMock(side_effect=err)
    provider = AnthropicProvider(cast(AsyncAnthropic, client), "claude-opus-4-8")
    with pytest.raises(LLMError):
        await provider.complete(system="s", user="u", max_tokens=64)


def test_from_settings_requires_api_key() -> None:
    with pytest.raises(LLMError):
        AnthropicProvider.from_settings(Settings(_env_file=None, anthropic_api_key=None))


def test_factory_selects_anthropic() -> None:
    settings = Settings(_env_file=None, anthropic_api_key="test-key")
    assert isinstance(get_llm_provider(settings), AnthropicProvider)


def test_factory_rejects_unimplemented_provider() -> None:
    settings = Settings(_env_file=None, llm_provider=LLMProviderName.OPENAI)
    with pytest.raises(LLMError):
        get_llm_provider(settings)


async def test_fake_provider_scripts_and_exhausts() -> None:
    provider = FakeLLMProvider(["one"])
    assert await provider.complete(system="s", user="u", max_tokens=8) == "one"
    with pytest.raises(LLMError):
        await provider.complete(system="s", user="u", max_tokens=8)


def _groq_client_returning(content: str | None) -> AsyncOpenAI:
    client = Mock()
    choice = SimpleNamespace(message=SimpleNamespace(content=content))
    client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(choices=[choice]))
    return cast(AsyncOpenAI, client)


async def test_groq_complete_returns_text() -> None:
    provider = GroqProvider(_groq_client_returning("Hi from Llama"), "llama-3.3-70b-versatile")
    assert await provider.complete(system="s", user="u", max_tokens=64) == "Hi from Llama"


async def test_groq_empty_content_raises() -> None:
    provider = GroqProvider(_groq_client_returning(None), "llama-3.3-70b-versatile")
    with pytest.raises(LLMError):
        await provider.complete(system="s", user="u", max_tokens=64)


async def test_groq_api_error_becomes_llm_error() -> None:
    client = Mock()
    err = OpenAIAPIError("boom", request=httpx.Request("POST", "https://api.groq.com"), body=None)
    client.chat.completions.create = AsyncMock(side_effect=err)
    provider = GroqProvider(cast(AsyncOpenAI, client), "llama-3.3-70b-versatile")
    with pytest.raises(LLMError):
        await provider.complete(system="s", user="u", max_tokens=64)


def test_groq_from_settings_requires_api_key() -> None:
    with pytest.raises(LLMError):
        GroqProvider.from_settings(Settings(_env_file=None, groq_api_key=None))


def test_factory_selects_groq() -> None:
    settings = Settings(_env_file=None, llm_provider=LLMProviderName.GROQ, groq_api_key="test-key")
    assert isinstance(get_llm_provider(settings), GroqProvider)
