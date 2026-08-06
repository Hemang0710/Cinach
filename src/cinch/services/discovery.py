"""Job discovery orchestration: discover → tailor → notify, idempotently.

Framework-free (no Telegram/FastAPI/scheduler imports) so it is trivially testable
and could move to a Celery/Redis worker unchanged. Notification is delivered through
the :class:`JobNotifier` protocol, whose concrete Telegram implementation lives in the
bot layer.

Idempotency: jobs dedupe by ``(source, external_id)`` and an application is created at
most once per ``(user, job)``. A job is (re)tailored/notified only while its
application is still ``DISCOVERED`` — once it reaches ``PENDING_APPROVAL`` (delivered)
or any decided state, later cycles skip it. Leaving a freshly-created application at
``DISCOVERED`` until notification succeeds gives at-least-once delivery with retry on
the next cycle, without ever double-notifying.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    ResumeRepository,
    UserRepository,
)
from cinch.domain.enums import ApplicationStatus
from cinch.domain.models import Job, Resume, TailoringResult, User
from cinch.domain.resume import MasterResume
from cinch.providers.jobs.base import JobQuery, JobSource, JobSourceError, RawJob
from cinch.services.tailoring import TailoringService

logger = get_logger(__name__)


class JobNotifier(Protocol):
    """Delivers a tailored application to a user (Telegram, in production)."""

    async def notify(
        self,
        *,
        chat_id: int,
        job: Job,
        tailoring: TailoringResult,
        application_id: UUID,
        resume_pdf: bytes | None = None,
    ) -> None:
        """Send the job + tailored resume with Approve/Skip controls.

        ``resume_pdf`` (Phase 9) is an optional rendered résumé PDF the notifier may
        attach so the user can preview exactly what would be submitted. ``None``
        means the caller couldn't render one — the card is still delivered.
        """
        ...


@dataclass
class DiscoverySummary:
    """Counts from one discovery cycle (for logging + tests)."""

    users: int = 0
    discovered: int = 0
    notified: int = 0
    skipped_existing: int = 0
    skipped_no_resume: int = 0


def query_from_resume(master: MasterResume, *, where: str | None, results: int) -> JobQuery | None:
    """Derive a per-user search query from the master resume.

    Uses the most recent experience title as the search term, falling back to the
    first listed skill. Returns ``None`` when there is nothing to search on.
    """
    what: str | None = None
    if master.experiences:
        what = master.experiences[0].title  # most recent role assumed first
    elif master.skills:
        what = master.skills[0]
    if not what:
        return None
    return JobQuery(what=what, where=where, results=results)


class DiscoveryService:
    """Runs one discovery cycle across all users with a master resume."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        job_source: JobSource,
        tailoring: TailoringService,
        notifier: JobNotifier,
        settings: Settings,
    ) -> None:
        self._session = session
        self._job_source = job_source
        self._tailoring = tailoring
        self._notifier = notifier
        self._settings = settings
        self._users = UserRepository(session)
        self._resumes = ResumeRepository(session)
        self._jobs = JobRepository(session)
        self._applications = ApplicationRepository(session)

    async def run(self) -> DiscoverySummary:
        """Discover → tailor → notify for every eligible user; return counts."""
        summary = DiscoverySummary()
        for user in await self._users.list():
            summary.users += 1
            await self._run_for_user(user, summary)
        logger.info("discovery_cycle_complete", **asdict(summary))
        return summary

    async def _run_for_user(self, user: User, summary: DiscoverySummary) -> None:
        resume = await self._resumes.get_master(user.id)
        if resume is None:
            summary.skipped_no_resume += 1
            return
        try:
            master = MasterResume.model_validate(resume.content)
        except ValidationError:
            logger.warning("discovery_bad_master_resume", user_id=str(user.id))
            summary.skipped_no_resume += 1
            return

        query = query_from_resume(
            master,
            where=self._settings.adzuna_where,
            results=self._settings.discovery_results_per_user,
        )
        if query is None:
            summary.skipped_no_resume += 1
            return

        try:
            raw_jobs = await self._job_source.search(query)
        except JobSourceError:
            logger.exception("discovery_search_failed", user_id=str(user.id))
            return

        for raw in raw_jobs:
            summary.discovered += 1
            try:
                await self._process_job(user, resume, master, raw, summary)
            except Exception:
                logger.exception("discovery_job_failed", external_id=raw.external_id)

    async def _process_job(
        self,
        user: User,
        resume: Resume,
        master: MasterResume,
        raw: RawJob,
        summary: DiscoverySummary,
    ) -> None:
        job = await self._jobs.get_or_create(
            source=self._job_source.source_name,
            external_id=raw.external_id,
            title=raw.title,
            company=raw.company,
            description=raw.description,
            url=raw.url,
            location=raw.location,
        )

        existing = await self._applications.get_by_user_job(user.id, job.id)
        if existing is not None and existing.status is not ApplicationStatus.DISCOVERED:
            # Already delivered (PENDING_APPROVAL) or decided — never notify twice.
            summary.skipped_existing += 1
            return

        application = await self._applications.get_or_create(
            user_id=user.id, job_id=job.id, status=ApplicationStatus.DISCOVERED
        )
        tailoring = await self._tailoring.tailor(resume=resume, job=job)
        resume_pdf = _render_resume_pdf_or_none(master, tailoring)
        await self._notifier.notify(
            chat_id=user.telegram_chat_id,
            job=job,
            tailoring=tailoring,
            application_id=application.id,
            resume_pdf=resume_pdf,
        )
        # Mark delivered only after a successful send, so a failure retries next cycle.
        await self._applications.set_status(application.id, ApplicationStatus.PENDING_APPROVAL)
        summary.notified += 1


def _render_resume_pdf_or_none(master: MasterResume, tailoring: TailoringResult) -> bytes | None:
    """Render the tailored résumé to PDF; return ``None`` (fail-soft) on any error.

    The Approve/Skip card must still ship even if PDF rendering fails — losing the
    attachment is a much smaller regression than losing the whole notification.
    """
    from cinch.services.resume_pdf import render_master_resume_pdf

    try:
        return render_master_resume_pdf(master, tailoring)
    except Exception:
        logger.exception("resume_pdf_render_failed")
        return None
