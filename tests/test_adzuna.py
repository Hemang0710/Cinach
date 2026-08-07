"""AdzunaJobSource parsing + error handling, with a mocked httpx transport (no network)."""

from __future__ import annotations

import httpx
import pytest

from cinch.core.config import Settings
from cinch.domain.enums import JobSourceName
from cinch.providers.jobs import get_job_source
from cinch.providers.jobs.adzuna import AdzunaJobSource
from cinch.providers.jobs.base import JobQuery, JobSourceError

_SAMPLE = {
    "results": [
        {
            "id": "12345",
            "title": "Senior Python Engineer",
            "company": {"display_name": "Acme Corp"},
            "location": {"display_name": "Remote, US"},
            "description": "Build async services.",
            "redirect_url": "https://www.adzuna.com/details/12345",
        },
        {
            "id": 67890,  # numeric id → coerced to str
            "title": "Backend Developer",
            "company": {},  # missing display_name → fallback
            "location": {},
            "description": "APIs.",
            "redirect_url": "https://www.adzuna.com/details/67890",
        },
    ]
}


def _source(handler: httpx.MockTransport) -> AdzunaJobSource:
    return AdzunaJobSource(app_id="id", app_key="key", country="us", transport=handler)


async def test_search_parses_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v1/api/jobs/us/search/1" in str(request.url)
        assert request.url.params.get("what") == "python engineer"
        return httpx.Response(200, json=_SAMPLE)

    source = _source(httpx.MockTransport(handler))
    jobs = await source.search(JobQuery(what="python engineer", results=5))

    assert [j.external_id for j in jobs] == ["12345", "67890"]
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].url == "https://www.adzuna.com/details/12345"
    assert jobs[0].location == "Remote, US"
    assert jobs[1].company == "Unknown company"  # fallback when display_name missing
    assert all(j.source is JobSourceName.ADZUNA for j in jobs)  # source is stamped (Phase 7)


async def test_non_2xx_raises_job_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    source = _source(httpx.MockTransport(handler))
    with pytest.raises(JobSourceError):
        await source.search(JobQuery(what="python", results=5))


def test_from_settings_requires_credentials() -> None:
    with pytest.raises(JobSourceError):
        AdzunaJobSource.from_settings(Settings(_env_file=None))  # no creds


def test_get_job_source_selects_adzuna() -> None:
    settings = Settings(_env_file=None, adzuna_app_id="id", adzuna_app_key="key")
    source = get_job_source(settings)
    assert source.source_name is JobSourceName.ADZUNA
