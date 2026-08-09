"""LLM provider contract.

Kept deliberately thin — a single text-completion method — so the tailoring
service owns prompt construction and JSON parsing, and every provider (Anthropic
now; OpenAI/Google later) implements the same surface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Raised when an LLM call fails (API error, missing credentials, bad output)."""


@runtime_checkable
class LLMProvider(Protocol):
    """A provider-agnostic single-shot text completion."""

    async def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        """Return the model's text response to a system + user prompt.

        Sampling parameters are intentionally absent: current Claude models reject
        them, and behaviour is steered through the prompt. Implementations must
        raise :class:`LLMError` on failure.
        """
        ...
