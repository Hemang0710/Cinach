"""Pluggable adapters behind narrow interfaces.

- ``LLMProvider``: anthropic / openai / google (Phase 2).
- ``JobSource``: adzuna and other official APIs (Phase 4).
- ``Submitter``: optional Playwright-based assisted submission (Phase 6).
"""

from __future__ import annotations

from cinch.providers.llm import (
    AnthropicProvider,
    FakeLLMProvider,
    GroundingJudge,
    LLMError,
    LLMProvider,
    get_llm_provider,
)

__all__ = [
    "AnthropicProvider",
    "FakeLLMProvider",
    "GroundingJudge",
    "LLMError",
    "LLMProvider",
    "get_llm_provider",
]
