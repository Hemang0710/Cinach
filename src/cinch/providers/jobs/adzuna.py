"""Adzuna job source.

ToS posture (this is the ``[HUMAN REVIEW: ToS posture]`` surface):

- Adzuna is an **official, licensed** job API — Cinch never scrapes it or any other
  site. Access uses per-developer credentials (``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY``)
  obtained from https://developer.adzuna.com/ and supplied via environment only.
- We stay within Adzuna's rate limits: a small ``results_per_page`` and an infrequent
  discovery interval (see ``discovery_interval_minutes`` / ``discovery_results_per_user``).
- Users are always sent to the posting's official ``redirect_url``; results carry the
  "Jobs by Adzuna" attribution. Nothing is auto-submitted.
"""

from __future__ import annotations

from typing import Any

import httpx

from cinch.core.config import Settings
from cinch.domain.enums import JobSourceName
from cinch.providers.jobs.base import JobQuery, JobSourceError, RawJob

_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
_TIMEOUT = httpx.Timeout(10.0)


class AdzunaJobSource:
    """Fetches postings from the Adzuna Search API."""

    source_name = JobSourceName.ADZUNA

    def __init__(
        self,
        *,
        app_id: str,
        app_key: str,
        country: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_key = app_key
        self._country = country
        self._transport = transport  # DI hook for tests (httpx.MockTransport); None in prod

    @classmethod
    def from_settings(cls, settings: Settings) -> AdzunaJobSource:
        """Build from settings; raise if credentials are missing."""
        if not settings.adzuna_app_id or not settings.adzuna_app_key:
            raise JobSourceError("Adzuna credentials are not configured")
        return cls(
            app_id=settings.adzuna_app_id,
            app_key=settings.adzuna_app_key,
            country=settings.adzuna_country,
        )

    async def search(self, query: JobQuery) -> list[RawJob]:
        """Return postings matching ``query`` (page 1)."""
        params: dict[str, str | int] = {
            "app_id": self._app_id,
            "app_key": self._app_key,
            "results_per_page": query.results,
            "what": query.what,
            "content-type": "application/json",
        }
        if query.where:
            params["where"] = query.where

        url = f"{_BASE_URL}/{self._country}/search/1"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise JobSourceError(f"Adzuna request failed: {exc}") from exc

        return [self._to_raw_job(item) for item in payload.get("results", [])]

    @staticmethod
    def _to_raw_job(item: dict[str, Any]) -> RawJob:
        """Map one Adzuna result object to a :class:`RawJob`."""
        company = item.get("company") or {}
        location = item.get("location") or {}
        return RawJob(
            external_id=str(item["id"]),
            title=item.get("title", "Untitled role"),
            company=company.get("display_name", "Unknown company"),
            description=item.get("description", ""),
            url=item.get("redirect_url", ""),
            location=location.get("display_name"),
            source=JobSourceName.ADZUNA,
        )
