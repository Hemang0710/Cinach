"""Repository tests: mapping, idempotency, and status transitions.

Run against a throwaway SQLite database (see ``conftest.db`` / ``session``).
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    ResumeRepository,
    UserRepository,
)
from cinch.domain import Application, Job, User
from cinch.domain.enums import ApplicationStatus, JobSourceName


async def _make_user(session: AsyncSession) -> User:
    return await UserRepository(session).get_or_create(telegram_user_id=42, telegram_chat_id=99)


async def _make_job(session: AsyncSession) -> Job:
    """Insert (or fetch) a fixed sample job with correctly typed arguments."""
    return await JobRepository(session).get_or_create(
        source=JobSourceName.ADZUNA,
        external_id="posting-1",
        title="Staff Engineer",
        company="Acme",
        description="Build reliable systems.",
        url="https://example.com/jobs/1",
        location="Remote",
    )


async def test_user_get_or_create_is_idempotent(session: AsyncSession) -> None:
    repo = UserRepository(session)
    first = await repo.get_or_create(telegram_user_id=42, telegram_chat_id=99)
    second = await repo.get_or_create(telegram_user_id=42, telegram_chat_id=99)
    assert isinstance(first, User)
    assert first.id == second.id
    assert len(await repo.list()) == 1


async def test_job_get_or_create_deduplicates(session: AsyncSession) -> None:
    first = await _make_job(session)
    second = await _make_job(session)
    assert isinstance(first, Job)
    assert first.id == second.id  # same (source, external_id) → one row
    assert len(await JobRepository(session).list()) == 1


async def test_application_get_or_create_is_idempotent(session: AsyncSession) -> None:
    user = await _make_user(session)
    job = await _make_job(session)
    repo = ApplicationRepository(session)

    first = await repo.get_or_create(user_id=user.id, job_id=job.id)
    second = await repo.get_or_create(user_id=user.id, job_id=job.id)
    assert isinstance(first, Application)
    assert first.id == second.id  # unique (user, job) → approving twice is a no-op
    assert first.status is ApplicationStatus.DISCOVERED
    assert len(await repo.list()) == 1


async def test_application_status_transition_persists(session: AsyncSession) -> None:
    user = await _make_user(session)
    job = await _make_job(session)
    repo = ApplicationRepository(session)
    app = await repo.get_or_create(user_id=user.id, job_id=job.id)

    updated = await repo.set_status(app.id, ApplicationStatus.APPROVED)
    assert updated is not None
    assert updated.status is ApplicationStatus.APPROVED

    reloaded = await repo.get(app.id)
    assert reloaded is not None
    assert reloaded.status is ApplicationStatus.APPROVED


async def test_resume_master_lookup(session: AsyncSession) -> None:
    user = await _make_user(session)
    repo = ResumeRepository(session)
    await repo.create(user.id, {"summary": "Real experience"}, is_master=True)

    master = await repo.get_master(user.id)
    assert master is not None
    assert master.is_master is True
    assert master.content == {"summary": "Real experience"}


async def test_set_status_missing_returns_none(session: AsyncSession) -> None:
    repo = ApplicationRepository(session)
    assert await repo.set_status(uuid4(), ApplicationStatus.APPROVED) is None
