"""CompositeJobSource + get_job_source factory."""

from __future__ import annotations

import pytest

from cinch.core.config import Settings
from cinch.domain.enums import JobSourceName
from cinch.providers.jobs import (
    AdzunaJobSource,
    CompositeJobSource,
    RemoteOKJobSource,
    get_job_source,
)
from cinch.providers.jobs.base import JobQuery, JobSourceError, RawJob


class _StaticSource:
    """A stub JobSource that returns pre-canned RawJob objects."""

    def __init__(self, name: JobSourceName, jobs: list[RawJob]) -> None:
        self.source_name = name
        self._jobs = jobs
        self.calls = 0

    async def search(self, query: JobQuery) -> list[RawJob]:
        self.calls += 1
        return list(self._jobs)


class _FailingSource:
    """A stub JobSource that always raises — used to prove per-source isolation."""

    source_name = JobSourceName.REMOTEOK

    async def search(self, query: JobQuery) -> list[RawJob]:
        raise RuntimeError("upstream on fire")


def _raw(source: JobSourceName, external_id: str) -> RawJob:
    return RawJob(
        external_id=external_id,
        title="Engineer",
        company="Acme",
        description="",
        url=f"https://example.com/{external_id}",
        source=source,
    )


async def test_composite_merges_results_from_all_sources() -> None:
    a = _StaticSource(JobSourceName.ADZUNA, [_raw(JobSourceName.ADZUNA, "a1")])
    b = _StaticSource(JobSourceName.REMOTEOK, [_raw(JobSourceName.REMOTEOK, "r1")])
    composite = CompositeJobSource([a, b])

    jobs = await composite.search(JobQuery(what="engineer"))

    assert sorted(j.external_id for j in jobs) == ["a1", "r1"]
    assert {j.source for j in jobs} == {JobSourceName.ADZUNA, JobSourceName.REMOTEOK}
    assert (a.calls, b.calls) == (1, 1)  # every source is hit


async def test_composite_isolates_failing_source() -> None:
    """One dead source must not kill the whole cycle."""
    good = _StaticSource(JobSourceName.ADZUNA, [_raw(JobSourceName.ADZUNA, "a1")])
    composite = CompositeJobSource([good, _FailingSource()])

    jobs = await composite.search(JobQuery(what="engineer"))

    assert [j.external_id for j in jobs] == ["a1"]  # failure swallowed; peer succeeded


def test_composite_requires_at_least_one_source() -> None:
    with pytest.raises(ValueError):
        CompositeJobSource([])


def test_factory_returns_single_source_when_only_one_enabled() -> None:
    settings = Settings(
        _env_file=None,
        job_sources="adzuna",
        adzuna_app_id="id",
        adzuna_app_key="key",
    )
    source = get_job_source(settings)
    assert isinstance(source, AdzunaJobSource)  # not wrapped in a composite


def test_factory_returns_composite_when_multiple_enabled() -> None:
    settings = Settings(
        _env_file=None,
        job_sources="adzuna,remoteok,arbeitnow",
        adzuna_app_id="id",
        adzuna_app_key="key",
    )
    source = get_job_source(settings)
    assert isinstance(source, CompositeJobSource)


def test_factory_skips_sources_missing_credentials() -> None:
    """Adzuna without creds is skipped; free sources still power the pipeline."""
    settings = Settings(_env_file=None, job_sources="adzuna,remoteok")
    source = get_job_source(settings)
    # Only remoteok survived — factory returns it directly, not wrapped.
    assert isinstance(source, RemoteOKJobSource)


def test_factory_ignores_unknown_source_names() -> None:
    settings = Settings(
        _env_file=None,
        job_sources="adzuna,not-a-real-source,remoteok",
        adzuna_app_id="id",
        adzuna_app_key="key",
    )
    source = get_job_source(settings)
    assert isinstance(source, CompositeJobSource)  # adzuna + remoteok survived; bogus dropped


def test_factory_raises_when_no_source_survives() -> None:
    # Adzuna needs creds; without them, nothing enabled → factory fails loudly.
    settings = Settings(_env_file=None, job_sources="adzuna")
    with pytest.raises(JobSourceError):
        get_job_source(settings)
