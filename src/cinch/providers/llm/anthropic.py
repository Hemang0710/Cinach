"""Anthropic adapter for the ``LLMProvider`` contract.

Wraps the official async SDK (``AsyncAnthropic``). Current Claude models reject
``temperature``/``top_p``/``top_k`` (they 400), so none are sent — faithfulness is
steered through the prompt. See the ``claude-api`` skill for SDK/model details.
"""

from __future__ import annotations

from anthropic import APIError, AsyncAnthropic
from anthropic.types import TextBlock

from cinch.core.config import Settings
from cinch.providers.llm.base import LLMError


class AnthropicProvider:
    """LLM provider backed by the Anthropic Messages API."""

    def __init__(self, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> AnthropicProvider:
        """Build a provider from settings; raise if the API key is missing."""
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return cls(client=client, model=settings.llm_model)

    async def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        """Call the Messages API and return the first text block's content."""
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except APIError as exc:  # network / status / auth errors
            raise LLMError(f"Anthropic API error: {exc}") from exc

        if message.stop_reason == "refusal":
            raise LLMError("Anthropic declined the request (stop_reason=refusal)")

        text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
        if not text:
            raise LLMError("Anthropic returned no text content")
        return text
