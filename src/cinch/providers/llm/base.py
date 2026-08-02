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


@runtime_checkable
class GroundingJudge(Protocol):
    """Optional second-layer semantic grounding check (off by default).

    The deterministic validator is always the hard gate; a judge only adds
    semantic coverage the rules can't express. Implemented in a later iteration.
    """

    async def is_grounded(self, *, tailored: str, source: str, corpus: str) -> bool:
        """Return True if ``tailored`` is faithfully grounded in the master resume."""
        ...
