"""Tests for the TailoringService with a fake LLM provider (no live calls)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cinch.core.config import Settings
from cinch.domain.enums import JobSourceName
from cinch.domain.models import Job, Resume
from cinch.providers.llm.fake import FakeLLMProvider
from cinch.services.tailoring import TailoringError, TailoringService

RESUME_CONTENT: dict[str, object] = {
    "summary": "Backend engineer.",
    "skills": ["Python"],
    "experiences": [
        {
            "company": "Acme",
            "title": "Engineer",
            "start": "2020",
            "bullets": ["Built a payments API handling 500 requests per second"],
        }
    ],
}


def _now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def resume() -> Resume:
    return Resume(
        id=uuid4(),
        user_id=uuid4(),
        is_master=True,
        content=RESUME_CONTENT,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture
def job() -> Job:
    return Job(
        id=uuid4(),
        source=JobSourceName.ADZUNA,
        external_id="job-1",
        title="Backend Engineer",
        company="Beta Inc",
        description="Build scalable APIs.",
        url="https://example.com/jobs/1",
        discovered_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


def _response(source: str, tailored: str) -> str:
    return json.dumps({"bullets": [{"source_text": source, "tailored_text": tailored}]})


async def test_happy_path_is_grounded(resume: Resume, job: Job, settings: Settings) -> None:
    provider = FakeLLMProvider(
        [
            _response(
                "Built a payments API handling 500 requests per second",
                "Developed a payments API serving 500 requests per second",
            )
        ]
    )
    result = await TailoringService(provider, settings).tailor(resume=resume, job=job)

    assert result.is_grounded is True
    assert result.job_id == job.id
    assert result.resume_id == resume.id
    assert len(result.bullets) == 1
    assert result.bullets[0].grounded is True
    # The provider actually received the master's real bullet in the prompt.
    assert "500 requests per second" in provider.calls[0]["user"]  # type: ignore[operator]


async def test_fabricated_bullet_is_flagged(resume: Resume, job: Job, settings: Settings) -> None:
    provider = FakeLLMProvider(
        [
            _response(
                "Built a payments API handling 500 requests per second",
                "Built a payments API and increased revenue by 40%",  # 40% is fabricated
            )
        ]
    )
    result = await TailoringService(provider, settings).tailor(resume=resume, job=job)

    assert result.is_grounded is False
    assert result.ungrounded == ["Built a payments API and increased revenue by 40%"]
    assert result.bullets[0].grounded is False


async def test_malformed_json_raises(resume: Resume, job: Job, settings: Settings) -> None:
    provider = FakeLLMProvider(["this is not json at all"])
    with pytest.raises(TailoringError):
        await TailoringService(provider, settings).tailor(resume=resume, job=job)


async def test_invalid_resume_content_raises(job: Job, settings: Settings) -> None:
    bad_resume = Resume(
        id=uuid4(),
        user_id=uuid4(),
        is_master=True,
        content={"skills": "not-a-list"},
        created_at=_now(),
        updated_at=_now(),
    )
    provider = FakeLLMProvider(["{}"])
    with pytest.raises(TailoringError):
        await TailoringService(provider, settings).tailor(resume=bad_resume, job=job)


class _RejectingJudge:
    """Fake grounding judge that fails everything (exercises the judge branch)."""

    async def is_grounded(self, *, tailored: str, source: str, corpus: str) -> bool:
        return False


async def test_llm_judge_can_demote_a_deterministically_grounded_bullet(
    resume: Resume, job: Job
) -> None:
    settings = Settings(_env_file=None, grounding_use_llm_judge=True)
    provider = FakeLLMProvider(
        [
            _response(
                "Built a payments API handling 500 requests per second",
                "Developed a payments API serving 500 requests per second",
            )
        ]
    )
    service = TailoringService(provider, settings, judge=_RejectingJudge())
    result = await service.tailor(resume=resume, job=job)

    # Passed the deterministic gate but the judge vetoed it.
    assert result.is_grounded is False
    assert result.bullets[0].grounded is False
