"""Assisted-submission orchestration: submit approved applications, idempotently.

Framework-free (no Telegram/FastAPI/scheduler imports) so it is trivially testable
and could move to a Celery/Redis worker unchanged — mirroring
:mod:`cinch.services.discovery`. Notification is delivered through the
:class:`SubmissionNotifier` protocol, whose Telegram implementation lives in the bot.

**Safety model.** Each ``APPROVED`` application is *claimed* — committed out of
``APPROVED`` to a pessimistic ``FAILED`` ("interrupted") state — **before** any network
submission. Only after the submitter returns is the true terminal outcome recorded.
So a crash mid-submit leaves the application non-``APPROVED`` and it is never picked up
again: a real-world application is never submitted twice. ``FAILED`` is terminal — the
pipeline never auto-retries it (a retry could double-submit).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from cinch.core.logging import get_logger
from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    ResumeRepository,
    UserRepository,
)
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus
from cinch.domain.models import Application, Job, User
from cinch.domain.resume import MasterResume
from cinch.providers.submit.base import Applicant, SubmissionOutcome, Submitter
from cinch.providers.submit.render import build_resume_html

logger = get_logger(__name__)

_OUTCOME_TO_STATUS: dict[SubmissionOutcome, ApplicationStatus] = {
    SubmissionOutcome.SUBMITTED: ApplicationStatus.SUBMITTED,
    SubmissionOutcome.NEEDS_HUMAN: ApplicationStatus.NEEDS_HUMAN,
    SubmissionOutcome.FAILED: ApplicationStatus.FAILED,
}


class SubmissionNotifier(Protocol):
    """Tells the user the outcome of a submission attempt (Telegram, in production)."""

    async def notify_submission(
        self, *, chat_id: int, job: Job, outcome: SubmissionOutcome, detail: str
    ) -> None:
        """Send a submission outcome (submitted / needs-you-to-finish / failed)."""
        ...


@dataclass
class SubmissionSummary:
    """Counts from one submission cycle (for logging + tests)."""

    approved: int = 0  # applications found in APPROVED at the start of the cycle
    submitted: int = 0
    needs_human: int = 0
    failed: int = 0
    skipped: int = 0  # claim lost (already handled) or orphaned (user/job missing)


class SubmissionService:
    """Submits every currently-``APPROVED`` application, safely and idempotently."""

    def __init__(self, db: Database, *, submitter: Submitter, notifier: SubmissionNotifier) -> None:
        self._db = db
        self._submitter = submitter
        self._notifier = notifier

    async def run(self) -> SubmissionSummary:
        """Submit each approved application; return counts. Never raises per-app."""
        summary = SubmissionSummary()
        async with self._db.session() as session:
            approved = await ApplicationRepository(session).list_by_status(
                ApplicationStatus.APPROVED
            )
        summary.approved = len(approved)
        for application in approved:
            try:
                await self._process(application, summary)
            except Exception:
                # Already claimed (non-APPROVED) — safe to leave; log and continue.
                logger.exception("submission_app_failed", application_id=str(application.id))
                summary.failed += 1
        logger.info("submission_cycle_complete", **asdict(summary))
        return summary

    async def _process(self, application: Application, summary: SubmissionSummary) -> None:
        # Claim first (commits out of APPROVED) so a later crash can't double-submit.
        async with self._db.session() as session:
            claimed = await ApplicationRepository(session).claim_for_submission(application.id)
            if claimed is None:
                summary.skipped += 1
                return
            user = await UserRepository(session).get(application.user_id)
            job = await JobRepository(session).get(application.job_id)
            master = await self._load_master(session, application.user_id)

        if user is None or job is None:
            summary.skipped += 1  # orphaned; already claimed out of APPROVED
            return

        applicant = _applicant_from(master)
        if applicant is None or master is None:
            await self._finalize(
                application.id,
                SubmissionOutcome.NEEDS_HUMAN,
                "add your name, email and phone to your master resume to enable auto-apply",
                user,
                job,
                summary,
            )
            return

        result = await self._submitter.submit(
            apply_url=str(job.url),
            applicant=applicant,
            resume_html=build_resume_html(master),
        )
        await self._finalize(application.id, result.outcome, result.detail, user, job, summary)

    async def _load_master(self, session: AsyncSession, user_id: UUID) -> MasterResume | None:
        resume = await ResumeRepository(session).get_master(user_id)
        if resume is None:
            return None
        try:
            return MasterResume.model_validate(resume.content)
        except ValidationError:
            logger.warning("submission_bad_master_resume", user_id=str(user_id))
            return None

    async def _finalize(
        self,
        application_id: UUID,
        outcome: SubmissionOutcome,
        detail: str,
        user: User,
        job: Job,
        summary: SubmissionSummary,
    ) -> None:
        status = _OUTCOME_TO_STATUS[outcome]
        submitted_at = datetime.now(tz=UTC) if outcome is SubmissionOutcome.SUBMITTED else None
        async with self._db.session() as session:
            await ApplicationRepository(session).record_submission(
                application_id, status=status, detail=detail, submitted_at=submitted_at
            )
        try:
            await self._notifier.notify_submission(
                chat_id=user.telegram_chat_id, job=job, outcome=outcome, detail=detail
            )
        except Exception:
            # Outcome is already durably recorded; a failed notify must not re-submit.
            logger.exception("submission_notify_failed", application_id=str(application_id))

        if outcome is SubmissionOutcome.SUBMITTED:
            summary.submitted += 1
        elif outcome is SubmissionOutcome.NEEDS_HUMAN:
            summary.needs_human += 1
        else:
            summary.failed += 1


def _applicant_from(master: MasterResume | None) -> Applicant | None:
    """Build an :class:`Applicant` from a master resume, or ``None`` if unusable.

    Requires at least a name and email — without them no form can be filled, so the
    application is handed back to the user rather than submitted blind.
    """
    if master is None or not master.name or not master.email:
        return None
    return Applicant(name=master.name, email=master.email, phone=master.phone)
