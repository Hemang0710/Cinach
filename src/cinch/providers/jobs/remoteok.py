"""RemoteOK job source (free, public JSON — no auth).

ToS posture: uses the documented public API at ``remoteok.com/api``. RemoteOK's
own docs ask consumers to include a User-Agent and honour reasonable request
rates. Cinch does both: discovery runs infrequently (``discovery_interval_minutes``,
default 60) and we page-1 only. Every posting is linked back to its RemoteOK
``url`` — Cinch never republishes.

RemoteOK does not accept keyword/location parameters on the free feed, so we
filter client-side against ``JobQuery.what`` (case-insensitive substring on
title + tags).
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import httpx

from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.base import JobQuery, JobSourceError, RawJob

_URL = "https://remoteok.com/api"
_TIMEOUT = httpx.Timeout(15.0)
_UA = "Cinch/0.x (+https://github.com/Hemang0710/Cinach)"
_TAG_RE = re.compile(r"<[^>]+>")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#-]*")


def _strip_html(text: str) -> str:
    """Rough HTML → plain text: strip tags + unescape entities + collapse whitespace."""
    stripped = _TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", unescape(stripped)).strip()


def _query_words(query: str) -> list[str]:
    """Meaningful lowercase words from a query, dropping trivial 1-2 char noise.

    ``"Full-Stack Engineer (Co-op)"`` → ``["full", "stack", "engineer", "co-op"]``.
    (Compound words with ``-`` are kept intact by the token regex.)
    """
    return [w.lower() for w in _WORD_RE.findall(query) if len(w) >= 3]


def _matches(text: str, words: list[str]) -> bool:
    """True if ANY search word appears (substring) in ``text`` (case-insensitive)."""
    lowered = text.lower()
    return any(w in lowered for w in words)


class RemoteOKJobSource:
    """Fetches postings from the RemoteOK free public feed."""

    source_name = JobSourceName.REMOTEOK

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # DI hook for tests (httpx.MockTransport); None in prod

    async def search(self, query: JobQuery) -> list[RawJob]:
        """Return up to ``query.results`` postings whose title/tags match ``query.what``."""
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, transport=self._transport, headers={"User-Agent": _UA}
            ) as client:
                response = await client.get(_URL)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise JobSourceError(f"RemoteOK request failed: {exc}") from exc

        # RemoteOK's first array element is a legal notice, not a job — skip it.
        items = [item for item in payload if isinstance(item, dict) and "id" in item]
        # Word-based filter: any meaningful word from the query in title/tags is a hit.
        # (A whole-phrase match would zero out on real titles — see fix/broaden PR.)
        words = _query_words(query.what)
        if not words:
            return []
        matches = [
            item
            for item in items
            if _matches(item.get("position") or "", words)
            or any(_matches(t or "", words) for t in item.get("tags") or [])
        ]
        return [self._to_raw_job(item) for item in matches[: query.results]]

    @staticmethod
    def _to_raw_job(item: dict[str, Any]) -> RawJob:
        """Map one RemoteOK item to a :class:`RawJob` (source-stamped)."""
        return RawJob(
            external_id=str(item["id"]),
            title=item.get("position") or "Untitled role",
            company=item.get("company") or "Unknown company",
            description=_strip_html(item.get("description") or ""),
            url=item.get("url") or item.get("apply_url") or "",
            location=item.get("location"),
            source=JobSourceName.REMOTEOK,
        )
