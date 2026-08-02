"""Pluggable adapters behind narrow interfaces.

- ``LLMProvider``: anthropic / openai / google (Phase 2).
- ``JobSource``: adzuna and other official APIs (Phase 4).
- ``Submitter``: optional Playwright-based assisted submission (Phase 6).
"""

from __future__ import annotations

from cinch.providers.jobs import (
    AdzunaJobSource,
    FakeJobSource,
    JobQuery,
    JobSource,
    JobSourceError,
    RawJob,
    get_job_source,
)
from cinch.providers.llm import (
    AnthropicProvider,
    FakeLLMProvider,
    GroundingJudge,
    LLMError,
    LLMProvider,
    get_llm_provider,
)

__all__ = [
    "AdzunaJobSource",
    "AnthropicProvider",
    "FakeJobSource",
    "FakeLLMProvider",
    "GroundingJudge",
    "JobQuery",
    "JobSource",
    "JobSourceError",
    "LLMError",
    "LLMProvider",
    "RawJob",
    "get_job_source",
    "get_llm_provider",
]
