"""ApprovalService — the authorization + idempotency core of Approve/Skip.

Runs against the throwaway SQLite database (``session`` fixture in conftest).
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from cinch.db.repositories import ApplicationRepository, JobRepository, UserRepository
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.domain.models import Application
from cinch.services.workflow import ApprovalDecision, ApprovalService, DecisionOutcome

OWNER_TG_ID = 42
OTHER_TG_ID = 999


async def _seed_pending(session: AsyncSession, *, owner_tg_id: int = OWNER_TG_ID) -> Application:
    """Create an owner + job + a PENDING_APPROVAL application, and return it."""
    user = await UserRepository(session).get_or_create(owner_tg_id, telegram_chat_id=99)
    job = await JobRepository(session).get_or_create(
        source=JobSourceName.ADZUNA,
        external_id=f"job-{owner_tg_id}",
        title="Staff Engineer",
        company="Acme",
        description="Build reliable systems.",
        url="https://example.com/jobs/1",
    )
    return await ApplicationRepository(session).get_or_create(
        user_id=user.id, job_id=job.id, status=ApplicationStatus.PENDING_APPROVAL
    )


async def _status(session: AsyncSession, application_id: object) -> ApplicationStatus:
    app = await ApplicationRepository(session).get(application_id)  # type: ignore[arg-type]
    assert app is not None
    return app.status


async def test_approve_sets_status(session: AsyncSession) -> None:
    app = await _seed_pending(session)
    outcome = await ApprovalService(session).decide(
        telegram_user_id=OWNER_TG_ID, application_id=app.id, decision=ApprovalDecision.APPROVE
    )
    assert outcome is DecisionOutcome.APPROVED
    assert await _status(session, app.id) is ApplicationStatus.APPROVED


async def test_skip_sets_status(session: AsyncSession) -> None:
    app = await _seed_pending(session)
    outcome = await ApprovalService(session).decide(
        telegram_user_id=OWNER_TG_ID, application_id=app.id, decision=ApprovalDecision.SKIP
    )
    assert outcome is DecisionOutcome.SKIPPED
    assert await _status(session, app.id) is ApplicationStatus.SKIPPED


async def test_second_decision_is_idempotent_noop(session: AsyncSession) -> None:
    app = await _seed_pending(session)
    service = ApprovalService(session)
    await service.decide(
        telegram_user_id=OWNER_TG_ID, application_id=app.id, decision=ApprovalDecision.APPROVE
    )
    # A second press — even the opposite decision — must not overwrite the recorded one.
    outcome = await service.decide(
        telegram_user_id=OWNER_TG_ID, application_id=app.id, decision=ApprovalDecision.SKIP
    )
    assert outcome is DecisionOutcome.ALREADY_HANDLED
    assert await _status(session, app.id) is ApplicationStatus.APPROVED


async def test_non_owner_is_unauthorized_and_status_unchanged(session: AsyncSession) -> None:
    app = await _seed_pending(session)
    outcome = await ApprovalService(session).decide(
        telegram_user_id=OTHER_TG_ID, application_id=app.id, decision=ApprovalDecision.APPROVE
    )
    assert outcome is DecisionOutcome.UNAUTHORIZED
    assert await _status(session, app.id) is ApplicationStatus.PENDING_APPROVAL


async def test_unknown_application_is_not_found(session: AsyncSession) -> None:
    outcome = await ApprovalService(session).decide(
        telegram_user_id=OWNER_TG_ID, application_id=uuid4(), decision=ApprovalDecision.APPROVE
    )
    assert outcome is DecisionOutcome.NOT_FOUND
