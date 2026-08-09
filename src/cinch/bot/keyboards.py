"""Inline keyboards + callback-data encoding for Approve/Skip.

``callback_data`` is limited to 64 bytes by Telegram; ``<decision>:<uuid>`` is at
most ``7 + 36 = 43`` bytes, well within budget. :func:`parse_callback` is strict —
it raises ``ValueError`` on anything it did not emit, so a forged/garbled payload is
rejected rather than silently mishandled.
"""

from __future__ import annotations

from urllib.parse import quote_plus
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from cinch.services.workflow import ApprovalDecision

_SEP = ":"
_ACCEPT_ACTION = "accept"  # Phase 12 — offer-acceptance callback namespace

_LINKEDIN_JOBS = "https://www.linkedin.com/jobs/search/"
_INDEED_JOBS = "https://www.indeed.com/jobs"


def _apply_handoff_row(job_title: str, location: str | None) -> list[InlineKeyboardButton]:
    """URL buttons opening a pre-filled job SEARCH on LinkedIn / Indeed.

    Apply-ready handoff *without* scraping or automation: these are the public
    search URLs a user would type themselves. We can't deep-link the exact posting
    for a discovered job without scraping those sites, so we hand off a ready-made
    search for the same role+location and the user applies there directly.
    """
    kw = quote_plus(job_title)
    loc = quote_plus(location) if location else ""
    linkedin = f"{_LINKEDIN_JOBS}?keywords={kw}" + (f"&location={loc}" if loc else "")
    indeed = f"{_INDEED_JOBS}?q={kw}" + (f"&l={loc}" if loc else "")
    return [
        InlineKeyboardButton("🔎 Find on LinkedIn", url=linkedin),
        InlineKeyboardButton("🔎 Find on Indeed", url=indeed),
    ]


def approve_skip_markup(
    application_id: UUID, job_title: str, location: str | None = None
) -> InlineKeyboardMarkup:
    """Approve/Skip keyboard, plus a LinkedIn/Indeed apply-handoff row."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"{ApprovalDecision.APPROVE.value}{_SEP}{application_id}",
                ),
                InlineKeyboardButton(
                    "⏭️ Skip",
                    callback_data=f"{ApprovalDecision.SKIP.value}{_SEP}{application_id}",
                ),
            ],
            _apply_handoff_row(job_title, location),
        ]
    )


def parse_callback(data: str) -> tuple[ApprovalDecision, UUID]:
    """Parse ``<decision>:<uuid>`` callback data.

    Raises:
        ValueError: if the decision is unknown or the id is not a valid UUID.
    """
    action, sep, raw_id = data.partition(_SEP)
    if not sep:
        raise ValueError(f"malformed callback data: {data!r}")
    return ApprovalDecision(action), UUID(raw_id)


def accept_markup(application_id: UUID) -> InlineKeyboardMarkup:
    """Build the single-button Accept keyboard for one open offer."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Accept",
                    callback_data=f"{_ACCEPT_ACTION}{_SEP}{application_id}",
                )
            ]
        ]
    )


def parse_accept_callback(data: str) -> UUID | None:
    """Parse an ``accept:<uuid>`` callback, or return ``None`` if it isn't one.

    Returning ``None`` (rather than raising) lets the callback router cheaply
    distinguish an accept press from an approve/skip press before delegating the
    latter to :func:`parse_callback`.

    Raises:
        ValueError: the action is ``accept`` but the id is not a valid UUID
            (a forged/garbled payload — rejected, never silently mishandled).
    """
    action, sep, raw_id = data.partition(_SEP)
    if not sep or action != _ACCEPT_ACTION:
        return None
    return UUID(raw_id)
