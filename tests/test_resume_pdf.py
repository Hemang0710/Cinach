"""Pure-Python résumé PDF renderer: produces valid PDFs; substitution is safe."""

from __future__ import annotations

from uuid import uuid4

from cinch.domain.models import TailoredBullet, TailoringResult
from cinch.domain.resume import EducationEntry, ExperienceEntry, MasterResume
from cinch.services.resume_pdf import (
    _latin1,
    _tailored_lookup,
    render_master_resume_pdf,
)

_MASTER = MasterResume(
    name="Jane Doe",
    email="jane@example.com",
    phone="+1-555-0100",
    summary="Backend engineer with 5 years experience.",
    skills=["Python", "SQLAlchemy", "FastAPI"],
    experiences=[
        ExperienceEntry(
            company="Acme Corp",
            title="Backend Engineer",
            start="2020",
            end="2024",
            bullets=["Built async services", "Scaled backend to 10k rps"],
        ),
        ExperienceEntry(
            company="Beta",
            title="Junior Dev",
            start="2018",
            end=None,
            bullets=["Wrote tests"],
        ),
    ],
    education=[
        EducationEntry(institution="State University", degree="BSc CS", year="2018"),
    ],
)


def _is_pdf(data: bytes) -> bool:
    """Every real PDF starts with the %PDF- magic and ends near %%EOF."""
    return data.startswith(b"%PDF-") and b"%%EOF" in data[-32:]


def test_renders_valid_pdf_bytes() -> None:
    pdf = render_master_resume_pdf(_MASTER)
    assert _is_pdf(pdf)
    # A résumé this size (name + summary + 3 skills + 3 bullets + 1 degree) should
    # produce meaningfully more than an empty page.
    assert len(pdf) > 1500


def test_render_handles_empty_master() -> None:
    # Every section is optional — an empty résumé must still render a valid PDF.
    pdf = render_master_resume_pdf(MasterResume())
    assert _is_pdf(pdf)


def test_render_is_deterministic_ignoring_metadata() -> None:
    """Same input → same output (a truthy invariant that catches accidental randomness)."""
    a = render_master_resume_pdf(_MASTER)
    b = render_master_resume_pdf(_MASTER)
    # fpdf2 embeds a creation-timestamp in the trailer; strip the last 200 bytes
    # (metadata + xref offsets) and compare the bulk of the content streams.
    assert a[:-200] == b[:-200]


def test_tailored_lookup_only_includes_grounded() -> None:
    tailoring = TailoringResult(
        job_id=uuid4(),
        resume_id=uuid4(),
        bullets=[
            TailoredBullet(text="A", source_text="src-a", grounded=True),
            TailoredBullet(text="B", source_text="src-b", grounded=False),
        ],
    )
    # Anti-fabrication: ungrounded rewrites are excluded from the swap map.
    assert _tailored_lookup(tailoring) == {"src-a": "A"}
    assert _tailored_lookup(None) == {}


def test_tailored_substitution_changes_the_rendered_pdf() -> None:
    """A grounded swap for an existing master bullet must change the PDF output."""
    baseline = render_master_resume_pdf(_MASTER)
    tailoring = TailoringResult(
        job_id=uuid4(),
        resume_id=uuid4(),
        bullets=[
            TailoredBullet(
                text="Delivered async Python services at high throughput",  # longer
                source_text="Built async services",
                grounded=True,
            ),
        ],
    )
    substituted = render_master_resume_pdf(_MASTER, tailoring)
    assert _is_pdf(substituted)
    assert substituted != baseline  # substitution actually altered the output


def test_ungrounded_substitution_produces_identical_output_to_baseline() -> None:
    """Anti-fabrication: ungrounded bullets never reach the PDF, so no change vs baseline."""
    baseline = render_master_resume_pdf(_MASTER)
    tailoring = TailoringResult(
        job_id=uuid4(),
        resume_id=uuid4(),
        bullets=[
            TailoredBullet(
                text="Led a team of 12 engineers and cut infra cost 40%",  # invented
                source_text="Built async services",
                grounded=False,  # <-- flagged as unsupported
            ),
        ],
    )
    result = render_master_resume_pdf(_MASTER, tailoring)
    # Ignore trailer metadata differences (timestamps can shift by a second).
    assert result[:-200] == baseline[:-200]


def test_unmatched_source_text_produces_identical_output_to_baseline() -> None:
    """If source_text doesn't match a master bullet, no substitution."""
    baseline = render_master_resume_pdf(_MASTER)
    tailoring = TailoringResult(
        job_id=uuid4(),
        resume_id=uuid4(),
        bullets=[
            TailoredBullet(
                text="Something new",
                source_text="A bullet the master resume never contained",
                grounded=True,
            ),
        ],
    )
    result = render_master_resume_pdf(_MASTER, tailoring)
    assert result[:-200] == baseline[:-200]


def test_latin1_normaliser_handles_accents_and_special_chars() -> None:
    # Accented Latin-1 chars pass through as-is (they're valid Latin-1 codepoints).
    assert _latin1("café") == "café"
    assert _latin1("François") == "François"
    # Common Unicode punctuation is transliterated to ASCII.
    assert _latin1("hello — world") == "hello - world"
    assert _latin1("it's “neat”") == 'it\'s "neat"'
    # Truly non-Latin-1 codepoints (emoji) fall back to '?'.
    assert "?" in _latin1("hello 🌍")
    assert _latin1("") == ""
    assert _latin1("plain ascii") == "plain ascii"
