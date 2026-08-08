"""Application approval workflow.

The security-critical core of the human-in-the-loop loop, deliberately kept free of
any Telegram/framework imports so it can be unit-tested in isolation. The bot layer
translates a callback into a :meth:`ApprovalService.decide` call and renders the
:class:`DecisionOutcome`; every authorization and idempotency rule lives here.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from cinch.db.repositories import ApplicationRepository, UserRepository
from cinch.domain.enums import ApplicationStatus


class ApprovalDecision(StrEnum):
    """The user's choice on a job application."""

    APPROVE = "approve"
    SKIP = "skip"


class DecisionOutcome(StrEnum):
    """Result of applying a decision — what the bot should tell the user."""

    APPROVED = "approved"
    SKIPPED = "skipped"
    ALREADY_HANDLED = "already_handled"  # idempotent no-op (already decided)
    NOT_FOUND = "not_found"  # unknown application id
    UNAUTHORIZED = "unauthorized"  # caller does not own the application


class AcceptOutcome(StrEnum):
    """Result of an ``/accept`` action — what the bot should tell the user."""

    ACCEPTED = "accepted"
    NOT_OFFERED = "not_offered"  # idempotent no-op (not in OFFERED — nothing to accept)
    NOT_FOUND = "not_found"  # unknown application id
    UNAUTHORIZED = "unauthorized"  # caller does not own the application


# Statuses that mean a decision has already been recorded — re-deciding is a no-op.
_TERMINAL: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.APPROVED, ApplicationStatus.SKIPPED, ApplicationStatus.SUBMITTED}
)

_TARGET: dict[ApprovalDecision, ApplicationStatus] = {
    ApprovalDecision.APPROVE: ApplicationStatus.APPROVED,
    ApprovalDecision.SKIP: ApplicationStatus.SKIPPED,
}


class ApprovalService:
    """Applies Approve/Skip decisions with per-user authorization + idempotency."""

    def __init__(self, session: AsyncSession) -> None:
        self._applications = ApplicationRepository(session)
        self._users = UserRepository(session)

    async def decide(
        self,
        *,
        telegram_user_id: int,
        application_id: UUID,
        decision: ApprovalDecision,
    ) -> DecisionOutcome:
        """Record a decision on an application.

        Enforced in order:

        1. the application must exist (else :data:`DecisionOutcome.NOT_FOUND`);
        2. the caller's Telegram id must match the application's owning user — a
           callback from anyone else is :data:`DecisionOutcome.UNAUTHORIZED` and
           leaves the status untouched;
        3. a decision already recorded is :data:`DecisionOutcome.ALREADY_HANDLED`
           (pressing the same button twice is a no-op).
        """
        application = await self._applications.get(application_id)
        if application is None:
            return DecisionOutcome.NOT_FOUND

        owner = await self._users.get(application.user_id)
        if owner is None or owner.telegram_user_id != telegram_user_id:
            return DecisionOutcome.UNAUTHORIZED

        if application.status in _TERMINAL:
            return DecisionOutcome.ALREADY_HANDLED

        await self._applications.set_status(application_id, _TARGET[decision])
        return (
            DecisionOutcome.APPROVED
            if decision is ApprovalDecision.APPROVE
            else DecisionOutcome.SKIPPED
        )

    async def accept(self, *, telegram_user_id: int, application_id: UUID) -> AcceptOutcome:
        """Accept an offer, moving an ``OFFERED`` application to ``ACCEPTED``.

        Same authorization + idempotency discipline as :meth:`decide`:

        1. the application must exist (else :data:`AcceptOutcome.NOT_FOUND`);
        2. the caller's Telegram id must own it (else :data:`AcceptOutcome.UNAUTHORIZED`,
           status untouched);
        3. only an ``OFFERED`` application can be accepted — any other status
           (including a double-tapped ``ACCEPTED``) is :data:`AcceptOutcome.NOT_OFFERED`.
        """
        application = await self._applications.get(application_id)
        if application is None:
            return AcceptOutcome.NOT_FOUND

        owner = await self._users.get(application.user_id)
        if owner is None or owner.telegram_user_id != telegram_user_id:
            return AcceptOutcome.UNAUTHORIZED

        accepted = await self._applications.accept_offer(application_id)
        return AcceptOutcome.ACCEPTED if accepted is not None else AcceptOutcome.NOT_OFFERED
