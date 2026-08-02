"""Domain models: User, Resume, Job, Application, TailoringResult, and status enums.

Framework-agnostic Pydantic models. Services depend on these; no ORM/framework
imports leak in here.
"""

from __future__ import annotations

from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.domain.models import (
    Application,
    DomainModel,
    Job,
    Resume,
    TailoredBullet,
    TailoringResult,
    User,
)

__all__ = [
    "Application",
    "ApplicationStatus",
    "DomainModel",
    "Job",
    "JobSourceName",
    "Resume",
    "TailoredBullet",
    "TailoringResult",
    "User",
]
