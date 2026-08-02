"""In-memory :class:`Submitter` for tests — scripted outcomes, no browser.

Mirrors ``providers/jobs/fake.py`` and ``providers/llm/fake.py``: deterministic,
records the calls it received, and never touches the network or a real Chromium.
"""

from __future__ import annotations

from collections import deque

from cinch.providers.submit.base import Applicant, SubmissionOutcome, SubmissionResult


class FakeSubmitter:
    """Return pre-scripted :class:`SubmissionResult`\\ s and record each call.

    ``results`` are consumed in order; once exhausted, ``default`` is returned (so a
    test can drive many applications through a single outcome without listing each).
    """

    def __init__(
        self,
        results: list[SubmissionResult] | None = None,
        *,
        default: SubmissionResult | None = None,
    ) -> None:
        self._results: deque[SubmissionResult] = deque(results or [])
        self._default = default or SubmissionResult(SubmissionOutcome.SUBMITTED, "submitted")
        self.calls: list[tuple[str, Applicant, str]] = []

    async def submit(
        self, *, apply_url: str, applicant: Applicant, resume_html: str
    ) -> SubmissionResult:
        """Record the call and return the next scripted (or default) result."""
        self.calls.append((apply_url, applicant, resume_html))
        if self._results:
            return self._results.popleft()
        return self._default
