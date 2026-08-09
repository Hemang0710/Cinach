"""Resume tailoring service — orchestrates prompt → LLM → parse → ground.

Framework-agnostic: depends on the ``LLMProvider`` interface and domain models, not
on any SDK or web framework. The service NEVER silently keeps fabricated bullets —
any bullet that fails grounding is recorded in ``TailoringResult.ungrounded`` so the
caller (Phase 3) can reject or surface it.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from cinch.core.config import Settings
from cinch.domain.models import Job, Resume, TailoredBullet, TailoringResult
from cinch.domain.resume import MasterResume
from cinch.providers.llm.base import LLMProvider
from cinch.services import prompts
from cinch.services.grounding import GroundingValidator


class TailoringError(RuntimeError):
    """Raised when tailoring cannot produce a valid result (bad input or LLM output)."""


class _LLMBullet(BaseModel):
    source_text: str
    tailored_text: str


class _LLMResponse(BaseModel):
    bullets: list[_LLMBullet]


def _extract_json_object(text: str) -> str:
    """Return the outermost ``{...}`` JSON object from a raw LLM response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise TailoringError("LLM response contained no JSON object")
    return text[start : end + 1]


class TailoringService:
    """Tailors a master resume to a job, with anti-fabrication grounding."""

    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    async def tailor(self, *, resume: Resume, job: Job) -> TailoringResult:
        """Produce a :class:`TailoringResult` for ``resume`` against ``job``.

        Raises:
            TailoringError: if the resume content is malformed or the LLM output
                cannot be parsed into the expected shape.
            LLMError: if the underlying provider call fails.
        """
        try:
            master = MasterResume.model_validate(resume.content)
        except ValidationError as exc:
            raise TailoringError(f"Invalid master resume content: {exc}") from exc

        system = prompts.SYSTEM_PROMPT
        user = prompts.build_user_prompt(master, job)
        raw = await self._provider.complete(
            system=system, user=user, max_tokens=self._settings.llm_max_tokens
        )

        try:
            payload = json.loads(_extract_json_object(raw))
            parsed = _LLMResponse.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise TailoringError(f"Could not parse LLM tailoring output: {exc}") from exc

        validator = GroundingValidator(master)
        bullets: list[TailoredBullet] = []
        ungrounded: list[str] = []
        for item in parsed.bullets:
            check = validator.check(tailored_text=item.tailored_text, source_text=item.source_text)
            grounded = check.grounded
            bullets.append(
                TailoredBullet(
                    text=item.tailored_text,
                    source_text=item.source_text,
                    grounded=grounded,
                )
            )
            if not grounded:
                ungrounded.append(item.tailored_text)

        return TailoringResult(
            job_id=job.id,
            resume_id=resume.id,
            bullets=bullets,
            ungrounded=ungrounded,
        )
