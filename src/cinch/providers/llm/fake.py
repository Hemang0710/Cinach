"""In-memory fake LLM provider for tests and local dev (no network, no key)."""

from __future__ import annotations

from collections import deque

from cinch.providers.llm.base import LLMError


class FakeLLMProvider:
    """Returns scripted responses in order.

    Args:
        responses: Text responses to return, one per ``complete`` call, in order.
            When exhausted, ``complete`` raises :class:`LLMError` (surfacing an
            over-call in tests rather than hanging or returning stale data).
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses: deque[str] = deque(responses or [])
        self.calls: list[dict[str, object]] = []

    async def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        """Record the call and return the next scripted response."""
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if not self._responses:
            raise LLMError("FakeLLMProvider: no scripted response left for this call")
        return self._responses.popleft()
