"""Composite job source — fans out to N adapters and merges their postings.

Used when ``JOB_SOURCES`` names more than one source (the common production
config). Each per-source search is isolated in a try/except so a single API
outage cannot kill the whole discovery cycle — dead sources are logged and the
cycle continues with whatever else responded.

Deduplication is intentionally left to the persistence layer:
``JobRepository`` already dedupes on the ``(source, external_id)`` unique
constraint, and each :class:`RawJob` carries its ``source`` (set by the
originating adapter). So a job returned by two sources is stored twice — once
per source — which is the correct behaviour: they're separate postings with
separate apply URLs and slightly different metadata.
"""

from __future__ import annotations

import asyncio

from cinch.core.logging import get_logger
from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.base import JobQuery, JobSource, RawJob

logger = get_logger(__name__)


class CompositeJobSource:
    """Aggregates postings from several ``JobSource`` adapters."""

    # ``source_name`` on this class is a sentinel: discovery uses the ``source``
    # field of each ``RawJob`` (populated by the originating adapter), so this
    # attribute is never persisted. Present only to satisfy the ``JobSource`` protocol.
    source_name = JobSourceName.ADZUNA

    def __init__(self, sources: list[JobSource]) -> None:
        if not sources:
            raise ValueError("CompositeJobSource requires at least one underlying source")
        self._sources = sources

    async def search(self, query: JobQuery) -> list[RawJob]:
        """Run every source concurrently; return the concatenated postings."""
        results = await asyncio.gather(
            *(self._safe_search(source, query) for source in self._sources),
            return_exceptions=False,  # _safe_search already swallows per-source failures
        )
        return [job for batch in results for job in batch]

    async def _safe_search(self, source: JobSource, query: JobQuery) -> list[RawJob]:
        """Search one source; log and swallow errors so peers can still succeed."""
        try:
            return await source.search(query)
        except Exception:
            logger.exception("composite_source_failed", source=source.source_name.value)
            return []
