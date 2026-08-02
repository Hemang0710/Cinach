"""Pluggable job sources (official APIs only — never scraping).

``JobSource`` is a narrow interface; ``get_job_source`` selects the adapter from
settings (no global singleton), mirroring the LLM provider layer.
"""

from __future__ import annotations

from cinch.core.config import Settings
from cinch.providers.jobs.adzuna import AdzunaJobSource
from cinch.providers.jobs.base import JobQuery, JobSource, JobSourceError, RawJob
from cinch.providers.jobs.fake import FakeJobSource

__all__ = [
    "AdzunaJobSource",
    "FakeJobSource",
    "JobQuery",
    "JobSource",
    "JobSourceError",
    "RawJob",
    "get_job_source",
]


def get_job_source(settings: Settings) -> JobSource:
    """Return the configured job source adapter.

    Raises:
        JobSourceError: if no adapter is available (or credentials are missing).
    """
    # Adzuna is the only official source wired up so far; add others here.
    return AdzunaJobSource.from_settings(settings)
