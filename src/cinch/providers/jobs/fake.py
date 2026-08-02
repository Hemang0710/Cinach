"""In-memory fake job source for tests and local development (no network)."""

from __future__ import annotations

from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.base import JobQuery, RawJob


class FakeJobSource:
    """Returns a fixed list of postings, ignoring the query. Records calls."""

    source_name = JobSourceName.ADZUNA

    def __init__(self, jobs: list[RawJob]) -> None:
        self._jobs = jobs
        self.calls: list[JobQuery] = []

    async def search(self, query: JobQuery) -> list[RawJob]:
        """Record the query and return the scripted postings (capped by results)."""
        self.calls.append(query)
        return self._jobs[: query.results]
