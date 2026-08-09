"""Deterministic pre-LLM noise gate for inbound emails (Phase 13).

Framework-free and pure: :func:`is_noise_email` looks only at the
:class:`~cinch.services.email_classifier.EmailPayload` fields Zapier forwards
(``from_email`` / ``subject`` / ``body_text``) and returns the name of the rule
that fired, or ``None`` when the email should proceed to the LLM classifier.

Design: **conservative, high-precision**. A false negative (noise slips through)
costs one wasted LLM call; a false positive (a real interview/offer dropped) is
a silent miss. So rules fire only on strong signals for categories that can never
legitimately advance an application — job-alert digests and marketing
newsletters. Anything ambiguous falls through unchanged.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cinch.services.email_classifier import EmailPayload

# Job-board digest / alert phrasing. These subjects/bodies never advance a
# specific application — they advertise *new* postings.
_JOB_ALERT_RE = re.compile(
    r"\b("
    r"job alert"
    r"|jobs for you"
    r"|new jobs? (matching|for you)"
    r"|jobs? matching your"
    r"|recommended jobs?"
    r"|job recommendations?"
    r"|\d+\s+new jobs?"
    r"|we found .{0,20}\bjobs?\b"
    r"|your (daily|weekly)? ?job alert"
    r"|new opportunities for you"
    r")\b",
    re.IGNORECASE,
)

# Bulk-marketing footer: an unsubscribe token is only decisive alongside another
# broadcast marker (a lone "unsubscribe" appears in legitimate mail too).
_UNSUBSCRIBE_RE = re.compile(r"\bunsubscribe\b", re.IGNORECASE)
_BULK_FOOTER_RE = re.compile(
    r"("
    r"manage (your )?preferences"
    r"|view (this )?(email )?in (your )?browser"
    r"|you('?re| are)? receiv(ing|ed) this (email )?because"
    r"|email preferences"
    r")",
    re.IGNORECASE,
)

# Unambiguous automated-broadcast mailboxes. Note: bare ``no-reply@`` is NOT here
# — real Lever/Greenhouse interview invites use it. The subject guard below
# further protects this rule.
_BULK_LOCALPART_RE = re.compile(
    r"^(newsletter|digest|marketing|promotions?|mailer|bounces?)([.+-]|$)",
    re.IGNORECASE,
)

# Subject keywords that mean "this might actually advance an application" — used
# to rescue an otherwise-bulk-looking sender from being filtered.
_ADVANCING_RE = re.compile(
    r"\b(interview|offer|reject|declin|unfortunately|schedul|availability|next step|"
    r"phone screen|hiring team|move forward)\b",
    re.IGNORECASE,
)


def _localpart(from_email: str) -> str:
    """Return the local-part (before ``@``) of an address, lowercased."""
    return (from_email or "").split("@", 1)[0].strip().lower()


def _looks_advancing(subject: str) -> bool:
    """True when the subject hints at a real hiring-stage update."""
    return bool(_ADVANCING_RE.search(subject or ""))


def is_noise_email(payload: EmailPayload) -> str | None:
    """Return the noise-rule name if ``payload`` is obvious noise, else ``None``.

    Rules (checked in order):

    - ``job_alert``  — subject or body is a job-board digest/alert.
    - ``newsletter`` — bulk-marketing footer (unsubscribe + a broadcast marker).
    - ``bulk_sender``— an automated-broadcast mailbox, and the subject does not
      look like a real hiring-stage update.
    """
    subject = payload.subject or ""
    body = payload.body_text or ""

    if _JOB_ALERT_RE.search(subject) or _JOB_ALERT_RE.search(body):
        return "job_alert"

    if _UNSUBSCRIBE_RE.search(body) and _BULK_FOOTER_RE.search(body):
        return "newsletter"

    if _BULK_LOCALPART_RE.match(_localpart(payload.from_email)) and not _looks_advancing(subject):
        return "bulk_sender"

    return None
