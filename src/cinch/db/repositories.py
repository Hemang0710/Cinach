"""Repositories: the only place ORM rows are read/written.

Each repository takes an :class:`AsyncSession` (dependency injection) and returns
**domain** models, never ORM instances — so services stay decoupled from SQLAlchemy.
Idempotent ``get_or_create`` helpers use a SAVEPOINT so a concurrent duplicate
insert surfaces as a clean re-fetch rather than poisoning the transaction.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cinch.db.base import Base
from cinch.db.models import ApplicationORM, JobORM, ResumeORM, UserORM
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.domain.models import Application, Job, Resume, User

TOrm = TypeVar("TOrm", bound=Base)
TDomain = TypeVar("TDomain", bound=BaseModel)


class BaseRepository(Generic[TOrm, TDomain]):
    """Shared read helpers mapping an ORM model to its domain counterpart."""

    orm_model: type[TOrm]
    domain_model: type[TDomain]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_domain(self, orm: TOrm) -> TDomain:
        return self.domain_model.model_validate(orm)

    async def get(self, entity_id: UUID) -> TDomain | None:
        """Return the entity by primary key, or ``None`` if absent."""
        orm = await self._session.get(self.orm_model, entity_id)
        return self._to_domain(orm) if orm is not None else None

    async def list(self) -> list[TDomain]:
        """Return all entities (Phase 1 has no pagination needs yet)."""
        result = await self._session.scalars(select(self.orm_model))
        return [self._to_domain(orm) for orm in result.all()]


class UserRepository(BaseRepository[UserORM, User]):
    """Users keyed by their Telegram id."""

    orm_model = UserORM
    domain_model = User

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        """Return the user for a Telegram id, or ``None``."""
        orm = await self._session.scalar(
            select(UserORM).where(UserORM.telegram_user_id == telegram_user_id)
        )
        return self._to_domain(orm) if orm is not None else None

    async def get_or_create(self, telegram_user_id: int, telegram_chat_id: int) -> User:
        """Idempotently return (or create) the user for a Telegram id."""
        existing = await self.get_by_telegram_id(telegram_user_id)
        if existing is not None:
            return existing
        orm = UserORM(telegram_user_id=telegram_user_id, telegram_chat_id=telegram_chat_id)
        try:
            async with self._session.begin_nested():
                self._session.add(orm)
        except IntegrityError:
            refetched = await self.get_by_telegram_id(telegram_user_id)
            assert refetched is not None  # inserted concurrently
            return refetched
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def get_by_email_webhook_token(self, token: str) -> User | None:
        """Return the user owning ``token`` (Phase 14 email routing), or ``None``.

        The token is high-entropy (``secrets.token_urlsafe(32)``), so an indexed
        equality lookup is acceptable auth — like an API key. An empty token never
        matches (the column is nullable; we don't want ``NULL``-ish false hits).
        """
        if not token:
            return None
        orm = await self._session.scalar(
            select(UserORM).where(UserORM.email_webhook_token == token)
        )
        return self._to_domain(orm) if orm is not None else None

    async def rotate_email_webhook_token(self, user_id: UUID) -> str:
        """Generate, persist, and return a fresh email-webhook token for ``user_id``.

        Rotating invalidates any previous token (the column is unique). Raises
        ``ValueError`` if the user doesn't exist.
        """
        orm = await self._session.get(UserORM, user_id)
        if orm is None:
            raise ValueError(f"user {user_id} not found")
        orm.email_webhook_token = secrets.token_urlsafe(32)
        await self._session.flush()
        return orm.email_webhook_token


class ResumeRepository(BaseRepository[ResumeORM, Resume]):
    """A user's resumes, including the master (grounding) resume."""

    orm_model = ResumeORM
    domain_model = Resume

    async def create(
        self, user_id: UUID, content: dict[str, object], *, is_master: bool = False
    ) -> Resume:
        """Persist a new resume for a user."""
        orm = ResumeORM(user_id=user_id, content=content, is_master=is_master)
        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def get_master(self, user_id: UUID) -> Resume | None:
        """Return the user's master resume, or ``None`` if not set yet."""
        orm = await self._session.scalar(
            select(ResumeORM).where(ResumeORM.user_id == user_id, ResumeORM.is_master.is_(True))
        )
        return self._to_domain(orm) if orm is not None else None

    async def set_master(self, user_id: UUID, content: dict[str, object]) -> Resume:
        """Upsert the user's master resume — replace its content, or create it."""
        orm = await self._session.scalar(
            select(ResumeORM).where(ResumeORM.user_id == user_id, ResumeORM.is_master.is_(True))
        )
        if orm is None:
            orm = ResumeORM(user_id=user_id, content=content, is_master=True)
            self._session.add(orm)
        else:
            orm.content = content
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)


class JobRepository(BaseRepository[JobORM, Job]):
    """Discovered jobs, deduplicated by ``(source, external_id)``."""

    orm_model = JobORM
    domain_model = Job

    async def get_by_external(self, source: JobSourceName, external_id: str) -> Job | None:
        """Return a job by its source + external id, or ``None``."""
        orm = await self._session.scalar(
            select(JobORM).where(JobORM.source == source, JobORM.external_id == external_id)
        )
        return self._to_domain(orm) if orm is not None else None

    async def get_or_create(
        self,
        *,
        source: JobSourceName,
        external_id: str,
        title: str,
        company: str,
        description: str,
        url: str,
        location: str | None = None,
    ) -> Job:
        """Idempotently return (or insert) a discovered job.

        Re-discovering the same posting returns the existing row unchanged.
        """
        existing = await self.get_by_external(source, external_id)
        if existing is not None:
            return existing
        orm = JobORM(
            source=source,
            external_id=external_id,
            title=title,
            company=company,
            description=description,
            url=url,
            location=location,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(orm)
        except IntegrityError:
            refetched = await self.get_by_external(source, external_id)
            assert refetched is not None  # inserted concurrently
            return refetched
        await self._session.refresh(orm)
        return self._to_domain(orm)


class ApplicationRepository(BaseRepository[ApplicationORM, Application]):
    """Applications, one per ``(user_id, job_id)`` — the idempotency anchor."""

    orm_model = ApplicationORM
    domain_model = Application

    async def get_by_user_job(self, user_id: UUID, job_id: UUID) -> Application | None:
        """Return the application for a (user, job) pair, or ``None``."""
        orm = await self._session.scalar(
            select(ApplicationORM).where(
                ApplicationORM.user_id == user_id, ApplicationORM.job_id == job_id
            )
        )
        return self._to_domain(orm) if orm is not None else None

    async def get_or_create(
        self,
        *,
        user_id: UUID,
        job_id: UUID,
        status: ApplicationStatus = ApplicationStatus.DISCOVERED,
    ) -> Application:
        """Idempotently return (or create) the application for a (user, job) pair."""
        existing = await self.get_by_user_job(user_id, job_id)
        if existing is not None:
            return existing
        orm = ApplicationORM(user_id=user_id, job_id=job_id, status=status)
        try:
            async with self._session.begin_nested():
                self._session.add(orm)
        except IntegrityError:
            refetched = await self.get_by_user_job(user_id, job_id)
            assert refetched is not None  # inserted concurrently
            return refetched
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def set_status(
        self, application_id: UUID, status: ApplicationStatus
    ) -> Application | None:
        """Update an application's status; return the updated model or ``None``."""
        orm = await self._session.get(ApplicationORM, application_id)
        if orm is None:
            return None
        orm.status = status
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def list_by_status(self, status: ApplicationStatus) -> list[Application]:
        """Return every application currently in ``status`` (the submission work queue)."""
        result = await self._session.scalars(
            select(ApplicationORM).where(ApplicationORM.status == status)
        )
        return [self._to_domain(orm) for orm in result.all()]

    async def claim_for_submission(self, application_id: UUID) -> Application | None:
        """Atomically claim an ``APPROVED`` application for a submission attempt.

        Moves it to a pessimistic ``FAILED`` ("interrupted") state so that, once the
        caller commits, a crash mid-submit leaves it non-``APPROVED`` and it is never
        re-submitted. Returns the claimed application, or ``None`` if it was not (or is
        no longer) ``APPROVED`` — making the claim a safe, idempotent no-op the second time.
        """
        orm = await self._session.get(ApplicationORM, application_id)
        if orm is None or orm.status != ApplicationStatus.APPROVED:
            return None
        orm.status = ApplicationStatus.FAILED
        orm.submission_detail = "submission interrupted before completion"
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def record_submission(
        self,
        application_id: UUID,
        *,
        status: ApplicationStatus,
        detail: str | None = None,
        submitted_at: datetime | None = None,
    ) -> Application | None:
        """Persist a submission outcome: terminal status plus a PII-free note/timestamp.

        Called once per application by the submission pipeline, moving it out of
        ``APPROVED`` so it is never picked up (or submitted) again.
        """
        orm = await self._session.get(ApplicationORM, application_id)
        if orm is None:
            return None
        orm.status = status
        orm.submission_detail = detail
        orm.submitted_at = submitted_at
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def list_candidates_for_email_match(self, user_id: UUID) -> list[Application]:
        """Applications a real recruiter email could plausibly refer to for ``user_id``.

        Post-submit statuses only: an email can only be about an application the
        user has actually engaged with. Excludes DISCOVERED / TAILORED / SKIPPED /
        FAILED (nothing sent, so no reply possible) and terminal ACCEPTED /
        REJECTED (already resolved). GHOSTED is included so a late recruiter reply
        re-advances a presumed-dead application. Ordered newest-first so ties break
        toward the most recent engagement.
        """
        allowed = {
            ApplicationStatus.APPROVED,
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.NEEDS_HUMAN,
            ApplicationStatus.INTERVIEW_INVITED,
            ApplicationStatus.INTERVIEW_SCHEDULED,
            ApplicationStatus.OFFERED,
            ApplicationStatus.GHOSTED,
        }
        result = await self._session.scalars(
            select(ApplicationORM)
            .where(ApplicationORM.user_id == user_id, ApplicationORM.status.in_(allowed))
            .order_by(ApplicationORM.updated_at.desc())
        )
        return [self._to_domain(orm) for orm in result.all()]

    async def record_email_update(
        self,
        application_id: UUID,
        *,
        status: ApplicationStatus,
        summary: str,
        received_at: datetime,
    ) -> Application | None:
        """Advance an application's status from a classified email + record evidence.

        ``summary`` is the LLM's short PII-lean note for the dashboard; the full
        email body is never persisted. ``received_at`` is the email header time.
        """
        orm = await self._session.get(ApplicationORM, application_id)
        if orm is None:
            return None
        orm.status = status
        orm.last_email_summary = summary
        orm.last_email_at = received_at
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def accept_offer(self, application_id: UUID) -> Application | None:
        """Transition an ``OFFERED`` application to ``ACCEPTED`` (idempotent guard).

        Only advances from ``OFFERED`` — any other current status (including an
        already-``ACCEPTED`` row from a double-tap) returns ``None`` so the caller
        treats it as a clean no-op rather than corrupting a resolved application.
        """
        orm = await self._session.get(ApplicationORM, application_id)
        if orm is None or orm.status != ApplicationStatus.OFFERED:
            return None
        orm.status = ApplicationStatus.ACCEPTED
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)

    async def list_offered(self, user_id: UUID) -> list[Application]:
        """Return this user's open offers (``OFFERED``), newest-engagement first."""
        result = await self._session.scalars(
            select(ApplicationORM)
            .where(
                ApplicationORM.user_id == user_id,
                ApplicationORM.status == ApplicationStatus.OFFERED,
            )
            .order_by(ApplicationORM.updated_at.desc())
        )
        return [self._to_domain(orm) for orm in result.all()]

    async def list_stale_submitted(self, before: datetime) -> list[Application]:
        """Return ``SUBMITTED`` applications last touched before ``before``.

        ``updated_at`` (``onupdate=func.now()``) is the "quiet since" clock: any
        status change or inbound-email update bumps it, so an app that has been
        silent since submission is exactly one whose ``updated_at`` has not moved.
        Scoped to ``SUBMITTED`` only — never sweeps APPROVED / INTERVIEW_* / OFFERED.
        """
        result = await self._session.scalars(
            select(ApplicationORM).where(
                ApplicationORM.status == ApplicationStatus.SUBMITTED,
                ApplicationORM.updated_at < before,
            )
        )
        return [self._to_domain(orm) for orm in result.all()]

    async def mark_ghosted(self, application_id: UUID, *, note: str) -> Application | None:
        """Flag a stale ``SUBMITTED`` application as ``GHOSTED`` (idempotent guard).

        Only transitions from ``SUBMITTED`` so a status the sweep's snapshot missed
        (e.g. an email advanced it between the query and this write) is never
        clobbered. The note is stored in ``submission_detail`` for the dashboard.
        """
        orm = await self._session.get(ApplicationORM, application_id)
        if orm is None or orm.status != ApplicationStatus.SUBMITTED:
            return None
        orm.status = ApplicationStatus.GHOSTED
        orm.submission_detail = note
        await self._session.flush()
        await self._session.refresh(orm)
        return self._to_domain(orm)
