"""Data assembly for the dashboard view (Phase 10, framework-free).

One call gives the router everything it needs to render the page: a summary of
counts by status, and a small denormalised row per application (with the joined
job title/company/URL). Kept in ``services/`` so the router stays thin and the
data shape is unit-testable without a live web request.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cinch.db.models import ApplicationORM, JobORM
from cinch.domain.enums import ApplicationStatus, JobSourceName

# Order the summary tiles left-to-right through the lifecycle.
_STATUS_ORDER: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.DISCOVERED,
    ApplicationStatus.PENDING_APPROVAL,
    ApplicationStatus.APPROVED,
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.NEEDS_HUMAN,
    ApplicationStatus.INTERVIEW_INVITED,
    ApplicationStatus.INTERVIEW_SCHEDULED,
    ApplicationStatus.OFFERED,
    ApplicationStatus.ACCEPTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.GHOSTED,
    ApplicationStatus.SKIPPED,
    ApplicationStatus.FAILED,
)


@dataclass(frozen=True)
class DashboardRow:
    """One row in the applications table on the dashboard."""

    application_id: UUID
    status: ApplicationStatus
    job_title: str
    company: str
    location: str | None
    url: str
    source: JobSourceName
    created_at: datetime
    submitted_at: datetime | None
    submission_detail: str | None
    # Inbound-email evidence (Phase 11) surfaced so an interview/offer/rejection
    # shows *why* it advanced and when — the core of offer tracking.
    last_email_at: datetime | None
    last_email_summary: str | None


@dataclass(frozen=True)
class DashboardStats:
    """Everything the dashboard template needs for one user, in one shot."""

    total: int
    by_status: list[tuple[ApplicationStatus, int]]  # ordered per ``_STATUS_ORDER``
    rows: list[DashboardRow] = field(default_factory=list)


async def compute_dashboard_stats(
    session: AsyncSession, user_id: UUID, *, row_limit: int = 30
) -> DashboardStats:
    """Return counts + the ``row_limit`` most-recent applications for ``user_id``.

    A single SQL query joins ``applications`` to ``jobs``; counting happens in
    Python (small N per user; keeps the DB layer simple).
    """
    query = (
        select(ApplicationORM, JobORM)
        .join(JobORM, ApplicationORM.job_id == JobORM.id)
        .where(ApplicationORM.user_id == user_id)
        .order_by(ApplicationORM.created_at.desc())
    )
    result = await session.execute(query)
    pairs = list(result.tuples().all())

    # The status/source columns are ``String`` (not SQLAlchemy ``Enum``), so the ORM
    # hands back plain ``str`` — coerce to the enum here so ``DashboardRow`` really
    # holds what its annotations promise and the template's ``.value`` resolves
    # (otherwise the status/source badges render blank).
    counts: Counter[ApplicationStatus] = Counter(ApplicationStatus(app.status) for app, _ in pairs)
    by_status = [(status, counts.get(status, 0)) for status in _STATUS_ORDER]
    rows = [
        DashboardRow(
            application_id=app.id,
            status=ApplicationStatus(app.status),
            job_title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            source=JobSourceName(job.source),
            created_at=app.created_at,
            submitted_at=app.submitted_at,
            submission_detail=app.submission_detail,
            last_email_at=app.last_email_at,
            last_email_summary=app.last_email_summary,
        )
        for app, job in pairs[:row_limit]
    ]
    return DashboardStats(total=len(pairs), by_status=by_status, rows=rows)
