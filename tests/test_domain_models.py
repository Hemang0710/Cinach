"""Tests for the pure-Pydantic domain models and enums."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cinch.domain import (
    Application,
    ApplicationStatus,
    Job,
    JobSourceName,
    TailoredBullet,
    TailoringResult,
    User,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_application_status_values() -> None:
    # StrEnum members serialise to their plain string value.
    assert ApplicationStatus.PENDING_APPROVAL.value == "pending_approval"
    assert JobSourceName.ADZUNA.value == "adzuna"


def test_user_model_is_frozen_and_typed() -> None:
    user = User(
        id=uuid4(),
        telegram_user_id=123,
        telegram_chat_id=456,
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(ValidationError):
        # frozen=True → immutable; state changes go through repositories.
        user.telegram_user_id = 999  # type: ignore[misc]


def test_unexpected_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        User(
            id=uuid4(),
            telegram_user_id=1,
            telegram_chat_id=2,
            created_at=_now(),
            updated_at=_now(),
            surprise="nope",  # type: ignore[call-arg]
        )


def test_job_coerces_source_and_url() -> None:
    job = Job(
        id=uuid4(),
        source="adzuna",  # coerced str -> JobSourceName
        external_id="abc123",
        title="Staff Engineer",
        company="Acme",
        description="Build things.",
        url="https://example.com/jobs/1",
        discovered_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    assert job.source is JobSourceName.ADZUNA
    assert str(job.url).startswith("https://example.com/jobs/1")


def test_application_defaults_optional_tailored_resume() -> None:
    app = Application(
        id=uuid4(),
        user_id=uuid4(),
        job_id=uuid4(),
        status=ApplicationStatus.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
    )
    assert app.tailored_resume_id is None


def test_tailoring_result_grounding_flag() -> None:
    grounded = TailoringResult(
        job_id=uuid4(),
        resume_id=uuid4(),
        bullets=[TailoredBullet(text="Led X", source_text="Led project X", grounded=True)],
    )
    assert grounded.is_grounded is True

    fabricated = TailoringResult(
        job_id=uuid4(),
        resume_id=uuid4(),
        ungrounded=["Invented a metric that isn't in the resume"],
    )
    assert fabricated.is_grounded is False
