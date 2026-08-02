"""Status and identifier enums shared across the domain.

``StrEnum`` mirrors the precedent set by :class:`cinch.core.config.LLMProviderName`:
values serialise to plain strings (JSON, DB columns) while staying type-safe.
"""

from __future__ import annotations

from enum import StrEnum


class ApplicationStatus(StrEnum):
    """Lifecycle of a job application in the human-in-the-loop workflow.

    Flow: a job is ``DISCOVERED``, then ``TAILORED`` once the resume is rewritten,
    then ``PENDING_APPROVAL`` while the user decides. The user's choice moves it to
    ``APPROVED`` or ``SKIPPED``; an approved application becomes ``SUBMITTED`` (or
    ``FAILED`` if submission errors out).
    """

    DISCOVERED = "discovered"
    TAILORED = "tailored"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SKIPPED = "skipped"
    SUBMITTED = "submitted"
    FAILED = "failed"


class JobSourceName(StrEnum):
    """Identifier for the origin of a discovered job.

    Only official / licensed APIs are permitted (never scraped sources). New
    adapters register their name here as they are added behind ``JobSource``.
    """

    ADZUNA = "adzuna"
