"""build_resume_html: real content only, correct sections, HTML-escaped."""

from __future__ import annotations

from cinch.domain.resume import MasterResume
from cinch.providers.submit.render import build_resume_html

_FULL: dict[str, object] = {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1-555-0100",
    "summary": "Backend engineer with 5y experience.",
    "skills": ["Python", "SQLAlchemy"],
    "experiences": [
        {
            "company": "Acme",
            "title": "Backend Engineer",
            "start": "2020",
            "end": "2024",
            "bullets": ["Built async services", "Scaled to 10k rps"],
        },
        {"company": "Beta", "title": "Junior Dev", "start": "2018", "bullets": ["Wrote tests"]},
    ],
    "education": [{"institution": "State University", "degree": "BSc CS", "year": "2018"}],
}


def test_render_includes_contact_and_real_content() -> None:
    html = build_resume_html(MasterResume.model_validate(_FULL))
    for expected in (
        "Jane Doe",
        "jane@example.com",
        "+1-555-0100",
        "Backend Engineer",
        "Built async services",
        "Python",
        "State University",
    ):
        assert expected in html
    # The role with no end date is marked as current, not fabricated with a date.
    assert "Present" in html


def test_render_emits_only_real_bullets_no_fabrication() -> None:
    html = build_resume_html(MasterResume.model_validate(_FULL))
    # Exactly the three provided bullets — nothing invented.
    assert html.count("<li>") == 3


def test_render_escapes_html() -> None:
    master = MasterResume(
        name="<script>alert(1)</script>",
        email="a@b.com",
        summary="1 < 2 & 3",
        skills=["<b>bold</b>"],
    )
    html = build_resume_html(master)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "1 &lt; 2 &amp; 3" in html
    assert "&lt;b&gt;bold" in html


def test_render_omits_absent_sections() -> None:
    html = build_resume_html(MasterResume(name="A. Person", email="a@b.com"))
    assert "Experience" not in html
    assert "Education" not in html
    assert "Skills" not in html
    assert "A. Person" in html
