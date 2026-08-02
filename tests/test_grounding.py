"""Anti-fabrication grounding tests — the core safety proof for Phase 2.

Proves the deterministic validator accepts faithful rephrasing and REJECTS
fabricated metrics, fabricated employers/titles, and citations that don't trace
back to the master resume.
"""

from __future__ import annotations

import pytest

from cinch.domain.resume import ExperienceEntry, MasterResume
from cinch.services.grounding import GroundingValidator


@pytest.fixture
def master() -> MasterResume:
    return MasterResume(
        summary="Backend engineer.",
        skills=["Python", "PostgreSQL"],
        experiences=[
            ExperienceEntry(
                company="Acme Corp",
                title="Software Engineer",
                start="2020",
                end="2023",
                bullets=[
                    "Built a payments API handling 500 requests per second",
                    "Reduced deployment time by 30%",
                    "Optimized database queries",
                ],
            )
        ],
    )


def test_faithful_rephrase_is_grounded(master: MasterResume) -> None:
    check = GroundingValidator(master).check(
        tailored_text="Developed a payments API serving 500 requests per second",
        source_text="Built a payments API handling 500 requests per second",
    )
    assert check.grounded is True
    assert check.reasons == []


def test_job_keyword_supported_by_real_skill_is_grounded(master: MasterResume) -> None:
    # "PostgreSQL" is a real skill, so aligning wording to it is allowed.
    check = GroundingValidator(master).check(
        tailored_text="Optimized PostgreSQL queries",
        source_text="Optimized database queries",
    )
    assert check.grounded is True


def test_fabricated_metric_is_rejected(master: MasterResume) -> None:
    check = GroundingValidator(master).check(
        tailored_text="Built a payments API and cut costs by 40%",
        source_text="Built a payments API handling 500 requests per second",
    )
    assert check.grounded is False
    assert any("numbers not in the master" in r for r in check.reasons)


def test_fabricated_employer_is_rejected(master: MasterResume) -> None:
    check = GroundingValidator(master).check(
        tailored_text="Built a payments API at Google",
        source_text="Built a payments API handling 500 requests per second",
    )
    assert check.grounded is False
    assert any("proper nouns not in the master" in r for r in check.reasons)


def test_source_not_in_master_is_rejected(master: MasterResume) -> None:
    check = GroundingValidator(master).check(
        tailored_text="Led a team of engineers",
        source_text="Managed a team of ten engineers",  # never in the master
    )
    assert check.grounded is False
    assert any("source_text is not present" in r for r in check.reasons)


def test_empty_source_is_rejected(master: MasterResume) -> None:
    check = GroundingValidator(master).check(tailored_text="Did great work", source_text="")
    assert check.grounded is False
