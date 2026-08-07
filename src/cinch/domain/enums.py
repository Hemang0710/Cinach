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
    ``APPROVED`` or ``SKIPPED``. An approved application is picked up by the optional
    submission pipeline (Phase 6), which drives it to ``SUBMITTED``, ``NEEDS_HUMAN``
    (handed back for the user to finish — login/CAPTCHA/unknown form), or ``FAILED``.
    """

    DISCOVERED = "discovered"
    TAILORED = "tailored"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SKIPPED = "skipped"
    SUBMITTED = "submitted"
    NEEDS_HUMAN = "needs_human"  # auto-submit unsafe/unsupported — user finishes manually
    FAILED = "failed"


class JobSourceName(StrEnum):
    """Identifier for the origin of a discovered job.

    Only official / licensed APIs are permitted (never scraped sources). New
    adapters register their name here as they are added behind ``JobSource``.
    """

    ADZUNA = "adzuna"
    REMOTEOK = "remoteok"
    ARBEITNOW = "arbeitnow"
