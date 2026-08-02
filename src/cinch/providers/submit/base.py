"""Assisted-submission provider interface (Phase 6, optional).

A :class:`Submitter` takes one **user-approved** application — the job's apply URL,
the applicant's contact details, and a rendered resume as HTML — and *attempts* to
submit it. It auto-submits only when it can do so safely; anything that would require
signing in, solving a CAPTCHA, or filling an unrecognized form is handed back to the
user (:attr:`SubmissionOutcome.NEEDS_HUMAN`).

This module has **no** Playwright import, so the whole codebase imports and tests
without the optional ``submit`` extra. The concrete Playwright adapter is lazily
loaded by :func:`get_submitter`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from cinch.core.config import Settings


class SubmitterError(Exception):
    """Raised when a submission backend cannot be constructed."""


class SubmissionOutcome(StrEnum):
    """Terminal result of a single submission attempt."""

    SUBMITTED = "submitted"  # form filled + submitted, a success signal was observed
    NEEDS_HUMAN = "needs_human"  # login / CAPTCHA / unknown form / missing data — handed back
    FAILED = "failed"  # unexpected error or timeout


@dataclass(frozen=True)
class Applicant:
    """Contact details used to fill an application form (from the master resume)."""

    name: str
    email: str
    phone: str | None = None


@dataclass(frozen=True)
class SubmissionResult:
    """Outcome of an attempt plus a short, PII-free note surfaced to the user."""

    outcome: SubmissionOutcome
    detail: str  # e.g. "submitted", "sign-in required" — never resume content


class Submitter(Protocol):
    """Attempts to submit one approved application.

    Implementations MUST be safe by default: never bypass a login or CAPTCHA, and
    never submit a form they cannot confidently recognize — return ``NEEDS_HUMAN``.
    """

    async def submit(
        self, *, apply_url: str, applicant: Applicant, resume_html: str
    ) -> SubmissionResult:
        """Attempt submission; return a terminal :class:`SubmissionResult`."""
        ...


def get_submitter(settings: Settings) -> Submitter:
    """Construct the configured submitter, lazily importing the Playwright adapter.

    Raises:
        SubmitterError: if the optional ``submit`` extra (Playwright) is not installed.
    """
    import importlib.util

    if importlib.util.find_spec("playwright") is None:
        raise SubmitterError(
            "Assisted submission requires the optional 'submit' extra. Install it with "
            "`uv sync --extra submit && playwright install chromium`."
        )
    from cinch.providers.submit.playwright import PlaywrightSubmitter

    return PlaywrightSubmitter(settings)
