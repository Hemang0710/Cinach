"""compute_dashboard_stats — counts by status + ordered recent rows."""

from __future__ import annotations

from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    UserRepository,
)
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.services.dashboard_stats import compute_dashboard_stats


async def test_stats_empty_when_no_applications(db: Database) -> None:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(1, 1)
    async with db.session() as session:
        stats = await compute_dashboard_stats(session, user.id)
    assert stats.total == 0
    assert stats.rows == []
    # All eight status tiles are present (zero counts).
    assert all(count == 0 for _, count in stats.by_status)


async def test_stats_counts_by_status_and_returns_rows(db: Database) -> None:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(1, 1)
        # Two jobs, two applications: one PENDING_APPROVAL, one SUBMITTED.
        job_a = await JobRepository(session).get_or_create(
            source=JobSourceName.REMOTEOK,
            external_id="a",
            title="Backend Engineer",
            company="Acme",
            description="d",
            url="https://ex.com/a",
        )
        job_b = await JobRepository(session).get_or_create(
            source=JobSourceName.ARBEITNOW,
            external_id="b",
            title="Frontend Engineer",
            company="Beta",
            description="d",
            url="https://ex.com/b",
        )
        app_a = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job_a.id, status=ApplicationStatus.PENDING_APPROVAL
        )
        app_b = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job_b.id, status=ApplicationStatus.SUBMITTED
        )

    async with db.session() as session:
        stats = await compute_dashboard_stats(session, user.id)

    assert stats.total == 2
    by_status = dict(stats.by_status)
    assert by_status[ApplicationStatus.PENDING_APPROVAL] == 1
    assert by_status[ApplicationStatus.SUBMITTED] == 1
    row_ids = {row.application_id for row in stats.rows}
    assert row_ids == {app_a.id, app_b.id}
    # Rows carry the joined job info + source for the source badge.
    sources = {row.source for row in stats.rows}
    assert sources == {JobSourceName.REMOTEOK, JobSourceName.ARBEITNOW}


async def test_stats_isolates_users(db: Database) -> None:
    """One user must never see another user's applications."""
    async with db.session() as session:
        me = await UserRepository(session).get_or_create(1, 1)
        someone_else = await UserRepository(session).get_or_create(2, 2)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id="x",
            title="T",
            company="C",
            description="d",
            url="https://ex.com/x",
        )
        await ApplicationRepository(session).get_or_create(
            user_id=someone_else.id, job_id=job.id, status=ApplicationStatus.APPROVED
        )

    async with db.session() as session:
        my_stats = await compute_dashboard_stats(session, me.id)
    assert my_stats.total == 0
    assert my_stats.rows == []


async def test_stats_respects_row_limit(db: Database) -> None:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(1, 1)
        for i in range(5):
            job = await JobRepository(session).get_or_create(
                source=JobSourceName.ADZUNA,
                external_id=f"job-{i}",
                title=f"Role {i}",
                company="Co",
                description="d",
                url=f"https://ex.com/{i}",
            )
            await ApplicationRepository(session).get_or_create(user_id=user.id, job_id=job.id)

    async with db.session() as session:
        stats = await compute_dashboard_stats(session, user.id, row_limit=2)
    assert stats.total == 5  # count is over all applications
    assert len(stats.rows) == 2  # rows are capped
