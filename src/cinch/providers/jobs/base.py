"""JobSource contract.

Mirrors the ``LLMProvider`` design: a narrow ``Protocol`` plus a settings-driven
factory, so the orchestrator depends on the interface, not a concrete source. Only
official / licensed APIs are permitted behind this interface (never scraped sources).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from cinch.domain.enums import JobSourceName


class JobSourceError(RuntimeError):
    """Raised when a job source fails (API error, missing credentials, bad response)."""


class JobQuery(BaseModel):
    """A search request against a job source."""

    what: str  # role / keywords
    where: str | None = None  # location filter (optional)
    results: int = 5  # max postings to return


class RawJob(BaseModel):
    """A normalized posting from a source, before it is persisted as a ``Job``.

    Framework- and ORM-agnostic; the orchestrator maps this onto
    ``JobRepository.get_or_create``.

    ``source`` is populated by each adapter so the multi-source :class:`CompositeJobSource`
    can preserve provenance when merging results from many APIs. It is optional for
    backward compatibility — when unset, the orchestrator falls back to the calling
    ``JobSource.source_name``.
    """

    external_id: str
    title: str
    company: str
    description: str
    url: str
    location: str | None = None
    source: JobSourceName | None = None


@runtime_checkable
class JobSource(Protocol):
    """A provider-agnostic source of job postings."""

    source_name: JobSourceName

    async def search(self, query: JobQuery) -> list[RawJob]:
        """Return postings matching ``query``.

        Implementations must raise :class:`JobSourceError` on failure and must not
        exceed the source's rate limits.
        """
        ...


__all__ = ["JobQuery", "JobSource", "JobSourceError", "RawJob"]
