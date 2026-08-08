"""SQLAlchemy 2.0 ORM models (the persistence representation).

Kept separate from :mod:`cinch.domain.models`: these carry storage concerns
(columns, FKs, constraints), the domain models carry business meaning. Repositories
translate between the two so services never import from here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cinch.db.base import Base, TimestampMixin, uuid_pk
from cinch.db.types import EncryptedJSON
from cinch.domain.enums import ApplicationStatus, JobSourceName


class UserORM(TimestampMixin, Base):
    """Persisted Telegram user."""

    __tablename__ = "users"

    id: Mapped[UUID] = uuid_pk()
    # Telegram ids are 64-bit — use BigInteger, not the default 32-bit Integer, or
    # large ids (e.g. 6_984_602_416) overflow on PostgreSQL. Unique so a Telegram
    # account maps to exactly one user.
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    resumes: Mapped[list[ResumeORM]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    applications: Mapped[list[ApplicationORM]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ResumeORM(TimestampMixin, Base):
    """Persisted resume. ``content`` holds structured resume JSON.

    PII BOUNDARY: ``content`` contains personal data. It is stored through
    :class:`~cinch.db.types.EncryptedJSON`, which Fernet-encrypts the payload at rest
    when ``ENCRYPTION_KEY`` is set (plaintext fallback for local dev). The column's
    underlying type stays JSON, so no schema migration is required.
    """

    __tablename__ = "resumes"

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_master: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content: Mapped[dict[str, object]] = mapped_column(EncryptedJSON, nullable=False)

    user: Mapped[UserORM] = relationship(back_populates="resumes")


class JobORM(TimestampMixin, Base):
    """Persisted job posting discovered from an official source."""

    __tablename__ = "jobs"
    __table_args__ = (
        # A posting is unique per (source, external id); makes discovery idempotent.
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external_id"),
    )

    id: Mapped[UUID] = uuid_pk()
    source: Mapped[JobSourceName] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(512), nullable=False)
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str] = mapped_column(nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApplicationORM(TimestampMixin, Base):
    """Persisted application linking a user to a job through the workflow."""

    __tablename__ = "applications"
    __table_args__ = (
        # One application per (user, job): the basis for idempotent approve/apply.
        UniqueConstraint("user_id", "job_id", name="uq_applications_user_id_job_id"),
    )

    id: Mapped[UUID] = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        String(32), default=ApplicationStatus.DISCOVERED, nullable=False
    )
    tailored_resume_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    # Submission outcome (Phase 6). Nullable: unset until the pipeline attempts a submit.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_detail: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Inbound-email tracking (Phase 11). Populated by the Zapier/Make email webhook
    # after LLM classification matched an email to this application.
    last_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_email_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    user: Mapped[UserORM] = relationship(back_populates="applications")
