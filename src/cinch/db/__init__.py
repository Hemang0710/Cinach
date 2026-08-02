"""Persistence: SQLAlchemy models, repositories, async session factory, Alembic.

The ORM layer lives here and nowhere else; services depend on repositories, which
return domain models. Alembic migrations own the production schema.
"""

from __future__ import annotations

from cinch.db.base import Base, TimestampMixin, uuid_pk
from cinch.db.models import ApplicationORM, JobORM, ResumeORM, UserORM
from cinch.db.repositories import (
    ApplicationRepository,
    BaseRepository,
    JobRepository,
    ResumeRepository,
    UserRepository,
)
from cinch.db.session import Database

__all__ = [
    "ApplicationORM",
    "ApplicationRepository",
    "Base",
    "BaseRepository",
    "Database",
    "JobORM",
    "JobRepository",
    "ResumeORM",
    "ResumeRepository",
    "TimestampMixin",
    "UserORM",
    "UserRepository",
    "uuid_pk",
]
