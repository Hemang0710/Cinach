"""Deterministic anti-fabrication validator.

Given a :class:`MasterResume`, checks each tailored bullet against the real resume
and hard-fails any bullet that:

1. cites a ``source_text`` not present in the master resume, or
2. introduces a number/metric not in the master (fabricated statistic), or
3. introduces a proper noun (employer/title/technology) not in the master.

This runs offline with no LLM, so it is fully unit-testable and is the enforced
gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cinch.domain.resume import MasterResume

# Digit sequences (percentages, counts, money, decimals). Commas are stripped so
# "1,000" and "1000" compare equal.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_TOKEN_SPLIT_RE = re.compile(r"[^0-9a-z]+")
_WORD_RE = re.compile(r"\b[\w][\w'&+.-]*\b")

# Capitalised words that can appear mid-sentence without being proper nouns.
_COMMON_MIDSENTENCE = {"i"}


@dataclass(frozen=True)
class GroundingCheck:
    """Result of checking one tailored bullet."""

    grounded: bool
    reasons: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _numbers(text: str) -> set[str]:
    return {m.group().lstrip("0") or "0" for m in _NUMBER_RE.finditer(text.replace(",", ""))}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT_RE.split(text.lower()) if t}


class GroundingValidator:
    """Checks tailored bullets against a master resume's real content."""

    def __init__(self, master: MasterResume) -> None:
        self._source_bullets = [_normalize(b) for b in master.all_bullets() if b.strip()]
        corpus = master.grounding_text()
        self._corpus_numbers = _numbers(corpus)
        self._corpus_tokens = _tokens(corpus)

    def _source_matches(self, source_text: str) -> bool:
        norm = _normalize(source_text)
        if not norm:
            return False
        # Exact match, or the cited text is contained in a real bullet (tolerates
        # trivial truncation) — but never the reverse (a real bullet inside a
        # longer fabricated citation must not pass).
        return any(norm == bullet or norm in bullet for bullet in self._source_bullets)

    def _fabricated_numbers(self, tailored: str) -> set[str]:
        return _numbers(tailored) - self._corpus_numbers

    def _fabricated_proper_nouns(self, tailored: str) -> set[str]:
        found: set[str] = set()
        words = _WORD_RE.findall(tailored)
        for index, word in enumerate(words):
            core = word.strip(".,")
            if not core or not any(ch.isalpha() for ch in core):
                continue
            is_acronym = core.isupper() and len(core) >= 2
            has_internal_caps = any(ch.isupper() for ch in core[1:])
            is_capitalized = core[0].isupper()
            looks_proper = is_acronym or has_internal_caps or (is_capitalized and index > 0)
            if not looks_proper:
                continue
            lowered = core.lower()
            if lowered in self._corpus_tokens or lowered in _COMMON_MIDSENTENCE:
                continue
            found.add(core)
        return found

    def check(self, *, tailored_text: str, source_text: str) -> GroundingCheck:
        """Validate a single tailored bullet against the master resume."""
        reasons: list[str] = []
        if not self._source_matches(source_text):
            reasons.append("source_text is not present in the master resume")
        fabricated_numbers = self._fabricated_numbers(tailored_text)
        if fabricated_numbers:
            reasons.append(
                f"introduces numbers not in the master resume: {sorted(fabricated_numbers)}"
            )
        fabricated_nouns = self._fabricated_proper_nouns(tailored_text)
        if fabricated_nouns:
            reasons.append(
                f"introduces proper nouns not in the master resume: {sorted(fabricated_nouns)}"
            )
        return GroundingCheck(grounded=not reasons, reasons=reasons)
