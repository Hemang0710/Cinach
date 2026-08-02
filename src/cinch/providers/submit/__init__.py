"""Assisted-submission providers (Phase 6, optional).

Importing this package is always safe — it pulls in only the Playwright-free
interface. The browser adapter is loaded on demand by :func:`get_submitter`.
"""

from __future__ import annotations

from cinch.providers.submit.base import (
    Applicant,
    SubmissionOutcome,
    SubmissionResult,
    Submitter,
    SubmitterError,
    get_submitter,
)
from cinch.providers.submit.render import build_resume_html

__all__ = [
    "Applicant",
    "SubmissionOutcome",
    "SubmissionResult",
    "Submitter",
    "SubmitterError",
    "build_resume_html",
    "get_submitter",
]
