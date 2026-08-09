"""Application-lifecycle housekeeping: the GHOSTED sweep (Phase 12).

Framework-free (no Telegram/FastAPI/scheduler imports), mirroring
:mod:`cinch.services.discovery`, so the sweep is unit-testable with an in-memory
DB and a fake notifier, and could move to a Celery/Redis worker unchanged.

A ``SUBMITTED`` application whose ``updated_at`` has not moved for
``quiet_days`` is presumed ghosted and flagged ``GHOSTED``. This is a
presumption, not a dead end: ``GHOSTED`` stays an email-match candidate, so a
late recruiter reply re-advances it (see
:meth:`ApplicationRepository.list_candidates_for_email_match`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from cinch.core.logging import get_logger
from cinch.db.repositories import ApplicationRepository, JobRepository, UserRepository
from cinch.domain.models import Job

logger = get_logger(__name__)


class GhostNotifier(Protocol):
    """Delivers a "no response" nudge for a newly-ghosted application."""

    async def notify_ghosted(self, *, chat_id: int, job: Job, quiet_days: int) -> None:
        """Send the terminal ghosted notice (Telegram, in production)."""
        ...


@dataclass
class GhostedSweepSummary:
    """Counts from one sweep (for logging + tests)."""

    scanned: int = 0  # stale SUBMITTED rows the snapshot found
    ghosted: int = 0  # rows actually transitioned (still SUBMITTED at write time)
    notified: int = 0  # ghosted rows for which a DM was sent


class GhostedSweepService:
    """Flags long-silent ``SUBMITTED`` applications as ``GHOSTED`` and notifies."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        notifier: GhostNotifier,
        quiet_days: int,
    ) -> None:
        self._applications = ApplicationRepository(session)
        self._jobs = JobRepository(session)
        self._users = UserRepository(session)
        self._notifier = notifier
        self._quiet_days = quiet_days

    async def run(self, *, now: datetime | None = None) -> GhostedSweepSummary:
        """Sweep once. ``now`` is injectable for deterministic tests."""
        now = now or datetime.now(tz=UTC)
        before = now - timedelta(days=self._quiet_days)
        stale = await self._applications.list_stale_submitted(before)
        summary = GhostedSweepSummary(scanned=len(stale))

        note = f"no response in {self._quiet_days}+ days"
        for application in stale:
            ghosted = await self._applications.mark_ghosted(application.id, note=note)
            if ghosted is None:
                # Status moved between the snapshot and the write (e.g. an email
                # advanced it) — leave it alone.
                continue
            summary.ghosted += 1

            job = await self._jobs.get(ghosted.job_id)
            user = await self._users.get(ghosted.user_id)
            if job is None or user is None:
                continue
            try:
                await self._notifier.notify_ghosted(
                    chat_id=user.telegram_chat_id, job=job, quiet_days=self._quiet_days
                )
                summary.notified += 1
            except Exception:
                # A DM failure must not abort the sweep or roll back the transition.
                logger.exception("ghosted_notify_failed", application_id=str(ghosted.id))

        logger.info(
            "ghosted_sweep_complete",
            scanned=summary.scanned,
            ghosted=summary.ghosted,
            notified=summary.notified,
        )
        return summary
