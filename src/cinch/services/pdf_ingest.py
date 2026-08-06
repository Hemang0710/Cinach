"""Ingest a PDF résumé and return a :class:`~cinch.domain.resume.MasterResume`.

Users upload their real PDF résumé; ``pypdf`` extracts the raw text; the LLM
provider structures it into Cinch's strict schema — with a **hard, deterministic
anti-fabrication guard** that verifies every field of the returned résumé exists
(as a normalised substring) in the original PDF text. Fabricated fields are never
silently kept — the whole ingest is rejected instead.

Framework-agnostic: depends on ``LLMProvider`` and domain models, not on any SDK,
FastAPI, or Telegram code — mirroring :mod:`cinch.services.tailoring`.
"""

from __future__ import annotations

import io
import json
import re
from typing import cast

from pydantic import ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.domain.resume import EducationEntry, ExperienceEntry, MasterResume
from cinch.providers.llm.base import LLMProvider
from cinch.services import prompts

logger = get_logger(__name__)


class PDFIngestError(RuntimeError):
    """Raised when a PDF cannot be turned into a valid, grounded master résumé.

    Message text is user-facing — it is shown to the caller in the bot. Keep it
    short and PII-free.
    """


# Collapse whitespace + strip anything that isn't a letter or digit, so trivial
# formatting differences ("Full-Stack" vs "full stack") don't defeat the grounding
# check. Matching then reduces to a simple substring test on the normalised form.
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    return _NORMALISE_RE.sub("", text.lower())


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Return concatenated text from every page of ``pdf_bytes``.

    Raises:
        PDFIngestError: If the bytes aren't a readable PDF, or if extraction
            yielded no text at all (an image-only résumé — user needs OCR or JSON).
    """
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except (PdfReadError, ValueError) as exc:
        raise PDFIngestError("That file isn't a readable PDF.") from exc

    parts = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise PDFIngestError(
            "I couldn't read any text from that PDF (image-only?). "
            "Send a text-based PDF or your résumé as .json (see /setresume)."
        )
    return text


class _ParsedResumeJSON(dict[str, object]):
    """Type alias — the raw dict returned by the LLM before Pydantic validation."""


class PDFIngestService:
    """Structures raw PDF text into a grounded :class:`MasterResume`."""

    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    async def ingest(self, pdf_bytes: bytes) -> MasterResume:
        """Extract → structure → validate → ground. Never returns fabrication.

        Raises:
            PDFIngestError: user-facing message for any failure mode.
        """
        text = extract_text_from_pdf(pdf_bytes)

        raw = await self._provider.complete(
            system=prompts.PDF_INGEST_SYSTEM_PROMPT,
            user=prompts.build_pdf_ingest_user_prompt(text),
            max_tokens=self._settings.llm_max_tokens,
        )

        try:
            payload = _extract_json_object(raw)
            master = MasterResume.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.info("pdf_ingest_bad_llm_output")  # no content logged (PII)
            raise PDFIngestError(
                "Couldn't structure that PDF into the résumé schema. "
                "Try the .json upload path (see /setresume)."
            ) from exc

        _ground_or_raise(master, text)
        return master


def _extract_json_object(raw: str) -> dict[str, object]:
    """Pull the outermost ``{...}`` from a raw LLM response and JSON-parse it."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("no JSON object in LLM output", raw, 0)
    return cast(dict[str, object], json.loads(raw[start : end + 1]))


def _ground_or_raise(master: MasterResume, source_text: str) -> None:
    """Every scalar string in ``master`` must appear (normalised) in ``source_text``.

    Anything that doesn't grounds means the LLM invented (or badly reformatted) a
    field — reject the whole ingest rather than silently keep it. Fails fast on
    the first ungrounded field so the error message is actionable.
    """
    haystack = _normalise(source_text)

    def _check(field_name: str, value: str | None) -> None:
        if not value:
            return
        if _normalise(value) not in haystack:
            raise PDFIngestError(
                f"Parsed field {field_name!r} isn't in the PDF text — refusing to save "
                "invented content. Try /setresume with the .json path instead."
            )

    _check("name", master.name)
    _check("email", master.email)
    _check("phone", master.phone)
    _check("summary", master.summary)
    for i, skill in enumerate(master.skills):
        _check(f"skills[{i}]", skill)
    for i, exp in enumerate(master.experiences):
        _check_experience(f"experiences[{i}]", exp, haystack)
    for i, edu in enumerate(master.education):
        _check_education(f"education[{i}]", edu, haystack)


def _check_in(label: str, value: str | None, haystack: str) -> None:
    if value and _normalise(value) not in haystack:
        raise PDFIngestError(
            f"Parsed field {label!r} isn't in the PDF text — refusing to save invented "
            "content. Try /setresume with the .json path instead."
        )


def _check_experience(prefix: str, exp: ExperienceEntry, haystack: str) -> None:
    _check_in(f"{prefix}.company", exp.company, haystack)
    _check_in(f"{prefix}.title", exp.title, haystack)
    for j, bullet in enumerate(exp.bullets):
        _check_in(f"{prefix}.bullets[{j}]", bullet, haystack)


def _check_education(prefix: str, edu: EducationEntry, haystack: str) -> None:
    _check_in(f"{prefix}.institution", edu.institution, haystack)
    _check_in(f"{prefix}.degree", edu.degree, haystack)
