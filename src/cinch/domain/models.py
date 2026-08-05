"""Framework-agnostic domain models.

Pure Pydantic v2 models with **no** SQLAlchemy or FastAPI imports — services depend
on these, not on ORM rows. Repositories in ``cinch.db`` build these from persisted
rows (``from_attributes=True``) so the persistence layer never leaks upward.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from cinch.domain.enums import ApplicationStatus, JobSourceName


class DomainModel(BaseModel):
    """Base for all domain models.

    ``from_attributes`` lets repositories construct a model directly from an ORM
    instance (``Model.model_validate(orm_row)``). ``frozen`` keeps domain values
    immutable — state changes go through repositories, not in-place mutation.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")


class User(DomainModel):
    """A Telegram user of the assistant."""

    id: UUID
    telegram_user_id: int
    telegram_chat_id: int
    created_at: datetime
    updated_at: datetime


class Resume(DomainModel):
    """A user's resume.

    The master resume (``is_master=True``) is the single grounding source for
    tailoring: every tailored bullet must trace back to content stored here.
    ``content`` is structured JSON (sections -> entries -> bullets); its exact
    schema is refined in Phase 2 when the tailoring service consumes it.
    """

    id: UUID
    user_id: UUID
    is_master: bool
    content: dict[str, object]
    created_at: datetime
    updated_at: datetime


class Job(DomainModel):
    """A job posting discovered from an official source."""

    id: UUID
    source: JobSourceName
    external_id: str
    title: str
    company: str
    location: str | None = None
    description: str
    url: HttpUrl
    discovered_at: datetime
    created_at: datetime
    updated_at: datetime


class Application(DomainModel):
    """A user's application to a job, tracked through the approval workflow.

    ``(user_id, job_id)`` is unique: a user has at most one application per job,
    which is what makes approving/creating the same job twice a no-op.
    """

    id: UUID
    user_id: UUID
    job_id: UUID
    status: ApplicationStatus
    tailored_resume_id: UUID | None = None
    # Populated by the Phase 6 submission pipeline; ``None`` until an attempt is made.
    submitted_at: datetime | None = None
    submission_detail: str | None = None  # outcome note / handoff URL / error (no PII)
    created_at: datetime
    updated_at: datetime


class TailoredBullet(DomainModel):
    """A single rewritten bullet plus the master-resume text it is grounded in.

    ``source_text`` is the original bullet from the master resume; ``grounded``
    records whether the anti-fabrication validator (Phase 2) could trace the
    rewrite back to real experience.
    """

    text: str
    source_text: str
    grounded: bool


class TailoringResult(DomainModel):
    """Output of the tailoring service (Phase 2) — a domain value, not a table.

    Defined now so the shared vocabulary is stable. It carries the tailored
    bullets and any content the grounding check flagged as unsupported.
    """

    job_id: UUID
    resume_id: UUID
    bullets: list[TailoredBullet] = Field(default_factory=list)
    ungrounded: list[str] = Field(default_factory=list)

    @property
    def is_grounded(self) -> bool:
        """True when nothing was flagged as fabricated/unsupported."""
        return not self.ungrounded
