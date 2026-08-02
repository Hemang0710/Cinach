"""Structured master-resume schema.

The master resume is the single grounding source for tailoring: every tailored
bullet must trace back to content defined here. ``Resume.content`` (stored as JSON
in the DB) is parsed into a :class:`MasterResume` via ``MasterResume.model_validate``.

Pure Pydantic — no ORM/framework imports.
"""

from __future__ import annotations

from pydantic import Field

from cinch.domain.models import DomainModel


class ExperienceEntry(DomainModel):
    """A single role in the work-experience section."""

    company: str
    title: str
    start: str
    end: str | None = None  # None => current role
    bullets: list[str] = Field(default_factory=list)


class EducationEntry(DomainModel):
    """A single education entry."""

    institution: str
    degree: str
    year: str | None = None


class MasterResume(DomainModel):
    """The user's canonical resume — the grounding corpus for tailoring.

    Only real experience lives here. The tailoring service rewrites/reorders these
    bullets to match a job; the grounding validator checks every rewrite against
    this content.
    """

    # Contact fields — what an application form needs. Optional (backward-compatible).
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)

    def all_bullets(self) -> list[str]:
        """Every experience bullet across all roles (the rewrite candidates)."""
        return [bullet for exp in self.experiences for bullet in exp.bullets]

    def grounding_text(self) -> str:
        """All real resume text concatenated — the corpus grounding checks against."""
        parts: list[str] = [self.summary, *self.skills]
        for exp in self.experiences:
            parts += [exp.company, exp.title, *exp.bullets]
        for edu in self.education:
            parts += [edu.institution, edu.degree]
        return "\n".join(p for p in parts if p)
