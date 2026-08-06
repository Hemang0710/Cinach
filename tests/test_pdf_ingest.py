"""PDFIngestService: extraction + LLM structuring + anti-fabrication grounding."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from cinch.core.config import Settings
from cinch.providers.llm.fake import FakeLLMProvider
from cinch.services.pdf_ingest import (
    PDFIngestError,
    PDFIngestService,
    extract_text_from_pdf,
)

# Sample master résumé present in the fake PDF text we synthesise below. Every
# string field the LLM emits MUST be found in the text (normalised) or the
# grounding validator rejects the whole ingest.
_TEXT = (
    "Jane Doe\n"
    "jane@example.com  +1-555-0100\n\n"
    "SUMMARY\nBackend engineer with 5 years experience.\n\n"
    "SKILLS\nPython, SQLAlchemy, FastAPI\n\n"
    "EXPERIENCE\n"
    "Acme Corp — Backend Engineer (2020 - 2024)\n"
    "- Built async services\n"
    "- Scaled backend to 10k rps\n\n"
    "EDUCATION\n"
    "State University — BSc Computer Science (2020)\n"
)

# What a faithful LLM would return — every field appears verbatim (or normalised) in _TEXT.
_FAITHFUL_JSON = """{
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1-555-0100",
    "summary": "Backend engineer with 5 years experience.",
    "skills": ["Python", "SQLAlchemy", "FastAPI"],
    "experiences": [
      {
        "company": "Acme Corp",
        "title": "Backend Engineer",
        "start": "2020",
        "end": "2024",
        "bullets": ["Built async services", "Scaled backend to 10k rps"]
      }
    ],
    "education": [
      {"institution": "State University", "degree": "BSc Computer Science", "year": "2020"}
    ]
}"""


def _pdf_bytes_with_text(text: str) -> bytes:
    """Build a minimal single-page PDF whose extracted text contains ``text``.

    We use PdfWriter.add_blank_page and inject text via the low-level content stream —
    but the simpler approach is to embed text as document metadata is not enough for
    pypdf's text extractor. Instead we assemble a tiny PDF by hand for the tests that
    need actual text extraction. For unit tests of grounding we can also bypass
    extraction by patching ``extract_text_from_pdf`` — used below.
    """
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_extract_text_rejects_non_pdf_bytes() -> None:
    with pytest.raises(PDFIngestError, match="readable PDF"):
        extract_text_from_pdf(b"not-a-pdf")


def test_extract_text_rejects_image_only_pdf() -> None:
    # A single blank page yields no extractable text.
    with pytest.raises(PDFIngestError, match="couldn't read"):
        extract_text_from_pdf(_pdf_bytes_with_text(""))


async def test_ingest_saves_faithful_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass PDF extraction so the test focuses on the LLM → grounding path.
    monkeypatch.setattr("cinch.services.pdf_ingest.extract_text_from_pdf", lambda _b: _TEXT)
    service = PDFIngestService(FakeLLMProvider([_FAITHFUL_JSON]), Settings(_env_file=None))
    master = await service.ingest(b"pdf-bytes")
    assert master.name == "Jane Doe"
    assert master.email == "jane@example.com"
    assert master.skills == ["Python", "SQLAlchemy", "FastAPI"]
    assert len(master.experiences) == 1
    assert master.experiences[0].bullets == ["Built async services", "Scaled backend to 10k rps"]


async def test_ingest_rejects_fabricated_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cinch.services.pdf_ingest.extract_text_from_pdf", lambda _b: _TEXT)
    fabricated = _FAITHFUL_JSON.replace(
        '["Python", "SQLAlchemy", "FastAPI"]',
        '["Python", "SQLAlchemy", "FastAPI", "Kubernetes"]',  # Kubernetes is NOT in _TEXT
    )
    service = PDFIngestService(FakeLLMProvider([fabricated]), Settings(_env_file=None))
    with pytest.raises(PDFIngestError, match=r"Kubernetes|isn't in the PDF"):
        await service.ingest(b"pdf-bytes")


async def test_ingest_rejects_fabricated_bullet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cinch.services.pdf_ingest.extract_text_from_pdf", lambda _b: _TEXT)
    fabricated = _FAITHFUL_JSON.replace(
        '"Built async services"',
        '"Led a team of 12 engineers and cut infra cost 30%"',  # made up
    )
    service = PDFIngestService(FakeLLMProvider([fabricated]), Settings(_env_file=None))
    with pytest.raises(PDFIngestError, match=r"isn't in the PDF"):
        await service.ingest(b"pdf-bytes")


async def test_ingest_rejects_bad_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cinch.services.pdf_ingest.extract_text_from_pdf", lambda _b: _TEXT)
    service = PDFIngestService(FakeLLMProvider(["not JSON at all"]), Settings(_env_file=None))
    with pytest.raises(PDFIngestError, match="Couldn't structure"):
        await service.ingest(b"pdf-bytes")


async def test_ingest_rejects_llm_output_with_extra_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MasterResume forbids unknown keys — schema mismatches surface as ingest errors."""
    monkeypatch.setattr("cinch.services.pdf_ingest.extract_text_from_pdf", lambda _b: _TEXT)
    with_extras = _FAITHFUL_JSON.replace(
        '"name": "Jane Doe"', '"name": "Jane Doe", "_meta": {"purpose": "master"}'
    )
    service = PDFIngestService(FakeLLMProvider([with_extras]), Settings(_env_file=None))
    with pytest.raises(PDFIngestError, match="structure"):
        await service.ingest(b"pdf-bytes")


def test_normalisation_defeats_trivial_formatting_diffs() -> None:
    """Grounding uses normalised comparison so "Full-Stack" and "full stack" match."""
    from cinch.services.pdf_ingest import _normalise

    assert _normalise("Full-Stack Engineer") == _normalise("full stack engineer")
    assert _normalise("Python, SQLAlchemy") == _normalise("python sqlalchemy")
