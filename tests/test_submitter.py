"""Submitter interface: FakeSubmitter scripting + get_submitter factory guard."""

from __future__ import annotations

import importlib.util

import pytest

from cinch.core.config import Settings
from cinch.providers.submit import (
    Applicant,
    SubmissionOutcome,
    SubmissionResult,
    SubmitterError,
    get_submitter,
)
from cinch.providers.submit.fake import FakeSubmitter

_APPLICANT = Applicant(name="Jane Doe", email="jane@example.com", phone="+1-555-0100")


async def test_fake_submitter_returns_scripted_then_default() -> None:
    scripted = SubmissionResult(SubmissionOutcome.NEEDS_HUMAN, "sign-in required")
    fake = FakeSubmitter([scripted], default=SubmissionResult(SubmissionOutcome.SUBMITTED, "ok"))

    first = await fake.submit(apply_url="https://x/1", applicant=_APPLICANT, resume_html="<html>")
    second = await fake.submit(apply_url="https://x/2", applicant=_APPLICANT, resume_html="<html>")

    assert first is scripted
    assert second.outcome is SubmissionOutcome.SUBMITTED
    assert [call[0] for call in fake.calls] == ["https://x/1", "https://x/2"]


async def test_fake_submitter_default_is_submitted() -> None:
    fake = FakeSubmitter()
    result = await fake.submit(apply_url="u", applicant=_APPLICANT, resume_html="<html>")
    assert result.outcome is SubmissionOutcome.SUBMITTED


def test_get_submitter_without_extra_raises() -> None:
    """Without the optional 'submit' extra, the factory fails loudly (not silently)."""
    if importlib.util.find_spec("playwright") is not None:
        pytest.skip("the 'submit' extra is installed in this environment")
    with pytest.raises(SubmitterError, match="submit"):
        get_submitter(Settings(_env_file=None))
