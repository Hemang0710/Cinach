"""ArbeitnowJobSource parsing + client-side filter, with a mocked httpx transport."""

from __future__ import annotations

import httpx
import pytest

from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.arbeitnow import ArbeitnowJobSource
from cinch.providers.jobs.base import JobQuery, JobSourceError

_SAMPLE = {
    "data": [
        {
            "slug": "senior-backend-eng-acme-berlin",
            "company_name": "Acme",
            "title": "Senior Backend Engineer",
            "description": "<p>Build <b>APIs</b>.</p>",
            "url": "https://www.arbeitnow.com/jobs/senior-backend-eng-acme-berlin",
            "location": "Berlin, DE",
            "tags": ["python", "postgres"],
        },
        {
            "slug": "designer-beta-remote",
            "company_name": "Beta",
            "title": "Product Designer",  # won't match a "backend" query
            "description": "Design work.",
            "url": "https://www.arbeitnow.com/jobs/designer-beta-remote",
            "location": "Remote",
            "tags": ["figma"],
        },
    ]
}


async def test_search_filters_and_stamps_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "arbeitnow.com/api" in str(request.url)
        return httpx.Response(200, json=_SAMPLE)

    source = ArbeitnowJobSource(transport=httpx.MockTransport(handler))
    jobs = await source.search(JobQuery(what="backend", results=5))

    assert [j.external_id for j in jobs] == ["senior-backend-eng-acme-berlin"]
    assert jobs[0].source is JobSourceName.ARBEITNOW
    assert jobs[0].company == "Acme"
    assert "<" not in jobs[0].description  # HTML stripped
    assert "Build" in jobs[0].description and "APIs" in jobs[0].description


async def test_search_handles_missing_data_key() -> None:
    handler = httpx.MockTransport(lambda req: httpx.Response(200, json={"unexpected": []}))
    source = ArbeitnowJobSource(transport=handler)
    jobs = await source.search(JobQuery(what="python", results=5))
    assert jobs == []


async def test_non_2xx_raises_job_source_error() -> None:
    handler = httpx.MockTransport(lambda req: httpx.Response(500, text="down"))
    source = ArbeitnowJobSource(transport=handler)
    with pytest.raises(JobSourceError):
        await source.search(JobQuery(what="python", results=5))
