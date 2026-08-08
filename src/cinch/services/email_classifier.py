"""Classify inbound recruiter emails and match them to an application.

Framework-free (no FastAPI/Telegram imports) so the entire logic is unit-testable
with a mocked ``LLMProvider`` and an in-memory database. Two responsibilities:

1. **Classify** the email into one of a small set of buckets via the LLM
   (``EMAIL_CLASSIFY_SYSTEM_PROMPT`` in :mod:`.prompts`).
2. **Match** the email to an existing application on this user's account, using
   the sender-domain / LLM-extracted company hint against candidate applications.

Every failure mode is a returned :class:`EmailClassificationResult` — never a raise.
The webhook route uses that shape to decide what to reply and whether to update
the DB. Anti-fabrication: the classifier never mutates state itself; it returns
a proposal that the webhook applies (or discards).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from enum import StrEnum

from pydantic import BaseModel, ValidationError

from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.domain.enums import ApplicationStatus
from cinch.domain.models import Application
from cinch.providers.llm.base import LLMError, LLMProvider
from cinch.services import prompts

logger = get_logger(__name__)


class EmailClassification(StrEnum):
    """LLM output bucket for a single email."""

    INTERVIEW_INVITED = "interview_invited"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    OFFER = "offer"
    REJECTION = "rejection"
    ACKNOWLEDGEMENT = "acknowledgement"
    OTHER = "other"


# Mapping from an email bucket to the status the application should move to.
# ACKNOWLEDGEMENT and OTHER intentionally omitted — they don't change state.
_CLASSIFICATION_TO_STATUS: dict[EmailClassification, ApplicationStatus] = {
    EmailClassification.INTERVIEW_INVITED: ApplicationStatus.INTERVIEW_INVITED,
    EmailClassification.INTERVIEW_SCHEDULED: ApplicationStatus.INTERVIEW_SCHEDULED,
    EmailClassification.OFFER: ApplicationStatus.OFFERED,
    EmailClassification.REJECTION: ApplicationStatus.REJECTED,
}


class EmailPayload(BaseModel):
    """Shape the webhook accepts (loose — Zapier sends what you configure)."""

    from_email: str
    from_name: str | None = None
    subject: str = ""
    body_text: str = ""
    received_at: datetime | None = None


class _LLMResponse(BaseModel):
    """Structured LLM output for the classifier."""

    classification: EmailClassification
    company_hint: str | None = None
    summary: str = ""


@dataclass(frozen=True)
class EmailClassificationResult:
    """Outcome of one email — a proposal the webhook applies (or logs and drops)."""

    classification: EmailClassification
    company_hint: str | None
    summary: str
    matched_application: Application | None
    new_status: ApplicationStatus | None
    received_at: datetime
    # Human-readable note explaining WHY nothing happened when nothing did.
    reason: str


def _extract_json_object(text: str) -> str:
    """Return the outermost ``{...}`` JSON object from a raw LLM response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in LLM response")
    return text[start : end + 1]


def _sender_company_hint(from_email: str) -> str | None:
    """Domain-based fallback when the LLM doesn't return a company hint.

    ``jobs@acme.com`` -> ``"acme"`` — good enough as a matching seed for many
    boutique-ATS and direct recruiter sends. Skips common webmail / no-reply
    domains where the domain says nothing about the employer.
    """
    match = re.search(r"@([\w.-]+)", from_email or "")
    if not match:
        return None
    domain = match.group(1).lower()
    root = domain.rsplit(".", 1)[0].rsplit(".", 1)[-1]
    if root in {"gmail", "yahoo", "outlook", "hotmail", "icloud", "protonmail", "aol"}:
        return None
    return root


def _normalise(text: str) -> str:
    """Lowercase + strip non-alphanumeric so 'Acme Corp.' and 'acme-corp' compare equal."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _best_match(
    company_hint: str, candidates: list[Application], jobs_by_id: dict[str, str]
) -> Application | None:
    """Return the candidate whose job.company is most similar to ``company_hint``.

    Uses ``SequenceMatcher`` on normalised strings; only accepts matches with a
    ratio ≥ 0.6 so unrelated emails don't accidentally attach to a random
    application. Ordered newest-first by the repository, so exact ties break to
    the most recent engagement.
    """
    needle = _normalise(company_hint)
    if not needle:
        return None
    best_ratio = 0.0
    best: Application | None = None
    for app in candidates:
        company = jobs_by_id.get(str(app.job_id), "")
        ratio = SequenceMatcher(None, needle, _normalise(company)).ratio()
        # Substring-on-either-side is a strong signal for short brand names.
        if needle in _normalise(company) or _normalise(company) in needle:
            ratio = max(ratio, 0.9)
        if ratio > best_ratio:
            best_ratio, best = ratio, app
    return best if best_ratio >= 0.6 else None


class EmailClassifier:
    """Classify one email + propose an application update. No DB mutation here."""

    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    async def classify(
        self,
        payload: EmailPayload,
        *,
        candidates: list[Application],
        jobs_by_id: dict[str, str],
    ) -> EmailClassificationResult:
        """Classify ``payload`` and best-match against the user's ``candidates``.

        ``jobs_by_id`` maps ``str(application.job_id)`` → ``job.company`` so we
        avoid a repository callback here (keeps the service framework-free).
        """
        received_at = payload.received_at or datetime.now(tz=UTC)
        raw = await self._call_llm(payload)
        parsed = self._parse(raw)
        if parsed is None:
            return _drop(received_at, "LLM output could not be parsed")

        company = parsed.company_hint or _sender_company_hint(payload.from_email) or ""
        matched = _best_match(company, candidates, jobs_by_id) if company else None
        new_status = _CLASSIFICATION_TO_STATUS.get(parsed.classification)

        if parsed.classification in {
            EmailClassification.ACKNOWLEDGEMENT,
            EmailClassification.OTHER,
        }:
            reason = f"informational ({parsed.classification.value}) — no status change"
            return _outcome(parsed, received_at, matched, None, reason=reason)
        if matched is None:
            return _outcome(
                parsed,
                received_at,
                None,
                None,
                reason=f"no application matched company_hint={company!r}",
            )
        assert new_status is not None  # every non-informational bucket maps to a status
        return _outcome(parsed, received_at, matched, new_status, reason="matched")

    async def _call_llm(self, payload: EmailPayload) -> str | None:
        """Call the LLM, returning raw text or ``None`` on any provider failure."""
        try:
            return await self._provider.complete(
                system=prompts.EMAIL_CLASSIFY_SYSTEM_PROMPT,
                user=prompts.build_email_classify_user_prompt(
                    from_email=payload.from_email,
                    from_name=payload.from_name,
                    subject=payload.subject,
                    body_text=payload.body_text,
                ),
                max_tokens=self._settings.llm_max_tokens,
            )
        except LLMError:
            logger.exception("email_classifier_llm_failed")
            return None

    def _parse(self, raw: str | None) -> _LLMResponse | None:
        """Extract + validate the JSON envelope; return ``None`` on any error."""
        if raw is None:
            return None
        try:
            return _LLMResponse.model_validate(json.loads(_extract_json_object(raw)))
        except (ValueError, json.JSONDecodeError, ValidationError):
            logger.warning("email_classifier_parse_failed")
            return None


def _drop(received_at: datetime, reason: str) -> EmailClassificationResult:
    """Build a no-op result — nothing matched, nothing to persist."""
    return EmailClassificationResult(
        classification=EmailClassification.OTHER,
        company_hint=None,
        summary="",
        matched_application=None,
        new_status=None,
        received_at=received_at,
        reason=reason,
    )


def _outcome(
    parsed: _LLMResponse,
    received_at: datetime,
    matched: Application | None,
    new_status: ApplicationStatus | None,
    *,
    reason: str,
) -> EmailClassificationResult:
    return EmailClassificationResult(
        classification=parsed.classification,
        company_hint=parsed.company_hint,
        summary=parsed.summary,
        matched_application=matched,
        new_status=new_status,
        received_at=received_at,
        reason=reason,
    )
