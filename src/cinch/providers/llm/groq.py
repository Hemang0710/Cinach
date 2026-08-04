"""Groq adapter for the ``LLMProvider`` contract.

Groq exposes an **OpenAI-compatible** API, so this wraps the async OpenAI SDK pointed
at Groq's endpoint. It is free to use (get a key at https://console.groq.com) and very
fast — pair it with a Llama model via ``LLM_MODEL`` (e.g. ``llama-3.3-70b-versatile``).
Faithfulness is steered through the prompt and enforced by the deterministic grounding
validator, so no sampling parameters are sent (mirroring the Anthropic adapter).
"""

from __future__ import annotations

from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from cinch.core.config import Settings
from cinch.providers.llm.base import LLMError


class GroqProvider:
    """LLM provider backed by Groq's OpenAI-compatible chat completions API."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> GroqProvider:
        """Build a provider from settings; raise if the API key is missing."""
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY is not set")
        client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
        return cls(client=client, model=settings.llm_model)

    async def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        """Call the chat completions API and return the first choice's message text."""
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=messages,
            )
        except APIError as exc:  # network / status / auth errors
            raise LLMError(f"Groq API error: {exc}") from exc

        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise LLMError("Groq returned no text content")
        return text
