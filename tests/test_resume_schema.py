"""Tests for the MasterResume structured schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cinch.domain.resume import MasterResume

VALID_CONTENT: dict[str, object] = {
    "summary": "Backend engineer.",
    "skills": ["Python", "PostgreSQL"],
    "experiences": [
        {
            "company": "Acme",
            "title": "Engineer",
            "start": "2020",
            "end": None,
            "bullets": ["Built an API", "Optimized queries"],
        }
    ],
    "education": [{"institution": "State U", "degree": "BSc", "year": "2019"}],
}


def test_parses_valid_content() -> None:
    master = MasterResume.model_validate(VALID_CONTENT)
    assert master.all_bullets() == ["Built an API", "Optimized queries"]
    assert "Python" in master.grounding_text()
    assert master.experiences[0].end is None  # current role


def test_defaults_when_empty() -> None:
    master = MasterResume.model_validate({})
    assert master.summary == ""
    assert master.all_bullets() == []


def test_rejects_unexpected_field() -> None:
    with pytest.raises(ValidationError):
        MasterResume.model_validate({"unexpected": "nope"})


def test_rejects_wrong_type() -> None:
    with pytest.raises(ValidationError):
        MasterResume.model_validate({"skills": "should-be-a-list"})
