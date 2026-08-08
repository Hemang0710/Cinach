"""Phase 12 — GHOSTED sweep.

A SUBMITTED application silent past the threshold is flagged GHOSTED; anything
fresher, or in a different status, is left alone. ``now`` is injected so the
"quiet since" window is deterministic without sleeping. The disabled flag makes
the scheduler entrypoint a guaranteed no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

from cinch.core.config import Settings
from cinch.db.repositories import ApplicationRepository, JobRepository, UserRepository
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.domain.models import Job
from cinch.services.lifecycle import GhostedSweepService

OWNER_TG_ID = 7
CHAT_ID = 70
QUIET_DAYS = 30


class _RecordingNotifier:
    """Captures ghosted notifications for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, UUID, int]] = []

    async def notify_ghosted(self, *, chat_id: int, job: Job, quiet_days: int) -> None:
        self.calls.append((chat_id, job.id, quiet_days))


async def _seed(db: Database, *, external_id: str, status: ApplicationStatus) -> UUID:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(OWNER_TG_ID, CHAT_ID)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id=external_id,
            title="T",
            company="C",
            description="D",
            url=f"https://example.com/{external_id}",
        )
        app = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job.id, status=status
        )
    return app.id


async def _status(db: Database, application_id: UUID) -> ApplicationStatus:
    async with db.session() as session:
        app = await ApplicationRepository(session).get(application_id)
    assert app is not None
    return app.status


# A "now" far enough in the future that any just-inserted row is past the window.
def _future_now() -> datetime:
    return datetime.now(tz=UTC) + timedelta(days=QUIET_DAYS + 10)


async def test_stale_submitted_is_ghosted_and_notified(db: Database) -> None:
    app_id = await _seed(db, external_id="s-1", status=ApplicationStatus.SUBMITTED)
    notifier = _RecordingNotifier()

    async with db.session() as session:
        service = GhostedSweepService(session, notifier=notifier, quiet_days=QUIET_DAYS)
        summary = await service.run(now=_future_now())

    assert summary.scanned == 1
    assert summary.ghosted == 1
    assert summary.notified == 1
    assert await _status(db, app_id) is ApplicationStatus.GHOSTED
    assert len(notifier.calls) == 1
    assert notifier.calls[0][0] == CHAT_ID
    assert notifier.calls[0][2] == QUIET_DAYS


async def test_fresh_submitted_is_left_alone(db: Database) -> None:
    app_id = await _seed(db, external_id="s-2", status=ApplicationStatus.SUBMITTED)
    notifier = _RecordingNotifier()

    async with db.session() as session:
        service = GhostedSweepService(session, notifier=notifier, quiet_days=QUIET_DAYS)
        # `now` is the real present → the window start is 30 days ago → not stale.
        summary = await service.run(now=datetime.now(tz=UTC))

    assert summary.scanned == 0
    assert summary.ghosted == 0
    assert await _status(db, app_id) is ApplicationStatus.SUBMITTED
    assert notifier.calls == []


async def test_non_submitted_old_application_is_untouched(db: Database) -> None:
    # An old application that is NOT submitted (e.g. interview invited) must never
    # be swept — ghosting is only for silent SUBMITTED rows.
    app_id = await _seed(db, external_id="i-1", status=ApplicationStatus.INTERVIEW_INVITED)
    notifier = _RecordingNotifier()

    async with db.session() as session:
        service = GhostedSweepService(session, notifier=notifier, quiet_days=QUIET_DAYS)
        summary = await service.run(now=_future_now())

    assert summary.scanned == 0
    assert summary.ghosted == 0
    assert await _status(db, app_id) is ApplicationStatus.INTERVIEW_INVITED


async def test_ghosted_stays_email_match_candidate(db: Database) -> None:
    # Property: a late recruiter email can re-open a ghosted application, so the
    # candidate set for email matching must include GHOSTED.
    app_id = await _seed(db, external_id="s-3", status=ApplicationStatus.SUBMITTED)
    notifier = _RecordingNotifier()
    async with db.session() as session:
        service = GhostedSweepService(session, notifier=notifier, quiet_days=QUIET_DAYS)
        await service.run(now=_future_now())

    async with db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
        assert user is not None
        candidates = await ApplicationRepository(session).list_candidates_for_email_match(user.id)
    assert app_id in {c.id for c in candidates}


async def test_disabled_sweep_is_a_noop(db: Database) -> None:
    from cinch.api.scheduler import run_ghosted_sweep

    app_id = await _seed(db, external_id="s-4", status=ApplicationStatus.SUBMITTED)
    settings = Settings(_env_file=None, ghosted_sweep_enabled=False)

    summary = await run_ghosted_sweep(db, settings, MagicMock())

    assert summary.scanned == 0
    assert summary.ghosted == 0
    # Even a would-be-stale row is untouched because the sweep never ran.
    assert await _status(db, app_id) is ApplicationStatus.SUBMITTED
