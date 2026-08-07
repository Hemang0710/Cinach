"""Arbeitnow job source (free, public JSON — no auth).

ToS posture: uses the documented public feed at
``https://www.arbeitnow.com/api/job-board-api``. Free, unauthenticated, and
described by Arbeitnow as intended for consumers building on top of their board.
Cinch honours their rate expectations via the infrequent discovery scheduler and
always links back to the posting's ``url``.

The feed doesn't accept keyword/location parameters, so we filter client-side
against ``JobQuery.what`` (case-insensitive substring on title + tags).
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import httpx

from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.base import JobQuery, JobSourceError, RawJob

_URL = "https://www.arbeitnow.com/api/job-board-api"
_TIMEOUT = httpx.Timeout(15.0)
_UA = "Cinch/0.x (+https://github.com/Hemang0710/Cinach)"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Rough HTML → plain text: strip tags + unescape entities + collapse whitespace."""
    stripped = _TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", unescape(stripped)).strip()


class ArbeitnowJobSource:
    """Fetches postings from the Arbeitnow public job-board API."""

    source_name = JobSourceName.ARBEITNOW

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
            raise JobSourceError(f"Arbeitnow request failed: {exc}") from exc

        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        needle = query.what.lower()
        matches = [
            item
            for item in items
            if isinstance(item, dict)
            and (
                needle in (item.get("title") or "").lower()
                or any(needle in (t or "").lower() for t in item.get("tags") or [])
            )
        ]
        return [self._to_raw_job(item) for item in matches[: query.results]]

    @staticmethod
    def _to_raw_job(item: dict[str, Any]) -> RawJob:
        """Map one Arbeitnow item to a :class:`RawJob` (source-stamped)."""
        # Slug is a stable per-posting identifier on Arbeitnow.
        external_id = str(item.get("slug") or item.get("url") or "")
        return RawJob(
            external_id=external_id,
            title=item.get("title") or "Untitled role",
            company=item.get("company_name") or "Unknown company",
            description=_strip_html(item.get("description") or ""),
            url=item.get("url") or "",
            location=item.get("location"),
            source=JobSourceName.ARBEITNOW,
        )
