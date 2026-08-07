"""RemoteOKJobSource parsing + client-side filter, with a mocked httpx transport."""

from __future__ import annotations

import httpx
import pytest

from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.base import JobQuery, JobSourceError
from cinch.providers.jobs.remoteok import RemoteOKJobSource, _strip_html

# First element mimics RemoteOK's legal-notice sentinel that must be skipped.
_SAMPLE = [
    {"legal": "notice — not a job"},
    {
        "id": "rok-1",
        "position": "Senior Python Engineer",
        "company": "Acme",
        "description": "<p>Build <b>async</b> services.</p>",
        "url": "https://remoteok.com/l/1",
        "location": "Remote",
        "tags": ["python", "async"],
    },
    {
        "id": "rok-2",
        "position": "Rust Developer",  # won't match a "python" query
        "company": "Beta",
        "description": "Systems programming.",
        "url": "https://remoteok.com/l/2",
        "location": "Remote",
        "tags": ["rust"],
    },
    {
        "id": "rok-3",
        "position": "Backend Engineer",
        "company": "Gamma",
        "description": "APIs.",
        "url": "https://remoteok.com/l/3",
        "location": "Remote",
        "tags": ["python", "postgres"],  # matches on tag even without "python" in title
    },
]


async def test_search_filters_by_title_or_tag_and_stamps_source() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "remoteok.com/api" in str(request.url)
        assert "Cinch" in request.headers.get("user-agent", "")
        return httpx.Response(200, json=_SAMPLE)

    source = RemoteOKJobSource(transport=httpx.MockTransport(handler))
    jobs = await source.search(JobQuery(what="python", results=5))

    external_ids = {j.external_id for j in jobs}
    assert external_ids == {"rok-1", "rok-3"}  # Rust job filtered out
    assert all(j.source is JobSourceName.REMOTEOK for j in jobs)
    # HTML stripped from description.
    py_job = next(j for j in jobs if j.external_id == "rok-1")
    assert "<" not in py_job.description
    assert "Build" in py_job.description and "async services" in py_job.description


async def test_search_honours_results_cap() -> None:
    handler = httpx.MockTransport(lambda req: httpx.Response(200, json=_SAMPLE))
    source = RemoteOKJobSource(transport=handler)
    jobs = await source.search(JobQuery(what="python", results=1))
    assert len(jobs) == 1


async def test_non_2xx_raises_job_source_error() -> None:
    handler = httpx.MockTransport(lambda req: httpx.Response(503, text="down"))
    source = RemoteOKJobSource(transport=handler)
    with pytest.raises(JobSourceError):
        await source.search(JobQuery(what="python", results=5))


def test_strip_html_removes_tags_and_unescapes() -> None:
    assert _strip_html("<p>hello &amp; world</p>") == "hello & world"
    assert _strip_html("") == ""
    assert _strip_html("plain") == "plain"
