"""Pluggable job sources (official APIs only — never scraping).

``JobSource`` is a narrow interface; ``get_job_source`` selects one or more
adapters from settings (no global singleton), mirroring the LLM provider layer.
When multiple sources are configured (the common case), a :class:`CompositeJobSource`
fans out to all of them and merges results.
"""

from __future__ import annotations

from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.adzuna import AdzunaJobSource
from cinch.providers.jobs.arbeitnow import ArbeitnowJobSource
from cinch.providers.jobs.base import JobQuery, JobSource, JobSourceError, RawJob
from cinch.providers.jobs.composite import CompositeJobSource
from cinch.providers.jobs.fake import FakeJobSource
from cinch.providers.jobs.remoteok import RemoteOKJobSource

logger = get_logger(__name__)

__all__ = [
    "AdzunaJobSource",
    "ArbeitnowJobSource",
    "CompositeJobSource",
    "FakeJobSource",
    "JobQuery",
    "JobSource",
    "JobSourceError",
    "RawJob",
    "RemoteOKJobSource",
    "get_job_source",
]


def _build_source(name: JobSourceName, settings: Settings) -> JobSource | None:
    """Instantiate one adapter by name, returning ``None`` if it can't be built.

    Missing credentials are logged and the source is skipped — the rest of the
    composite still runs — rather than raising and killing the whole cycle.
    """
    try:
        if name is JobSourceName.ADZUNA:
            return AdzunaJobSource.from_settings(settings)
        if name is JobSourceName.REMOTEOK:
            return RemoteOKJobSource()
        # ARBEITNOW is the only remaining variant — mypy exhaustiveness holds.
        return ArbeitnowJobSource()
    except JobSourceError as exc:
        logger.warning("job_source_skipped", source=name.value, reason=str(exc))
        return None


def get_job_source(settings: Settings) -> JobSource:
    """Return a job source built from ``settings.job_sources``.

    - A comma-separated list (e.g. ``"adzuna,remoteok,arbeitnow"``) picks which
      adapters to enable.
    - Sources missing credentials are skipped (logged) so a partial config still
      yields a working pipeline.
    - Returns the single adapter directly if only one survives, or a
      :class:`CompositeJobSource` fanning out otherwise.

    Raises:
        JobSourceError: if no source could be built at all.
    """
    names = [n.strip() for n in settings.job_sources.split(",") if n.strip()]
    sources: list[JobSource] = []
    for raw_name in names:
        try:
            enum_name = JobSourceName(raw_name)
        except ValueError:
            logger.warning("job_source_invalid_name", name=raw_name)
            continue
        adapter = _build_source(enum_name, settings)
        if adapter is not None:
            sources.append(adapter)

    if not sources:
        raise JobSourceError(
            f"No job sources could be built from JOB_SOURCES={settings.job_sources!r}"
        )
    if len(sources) == 1:
        return sources[0]
    return CompositeJobSource(sources)
