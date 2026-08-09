"""Rendering of user-facing Telegram messages.

Presentation only — no business logic. All dynamic text is HTML-escaped before it
reaches Telegram's HTML parse mode, so a job title or bullet containing ``<`` / ``&``
cannot break the markup or inject tags.
"""

from __future__ import annotations

from html import escape

from cinch.domain.enums import ApplicationStatus
from cinch.domain.models import Job, TailoringResult
from cinch.providers.submit.base import SubmissionOutcome


def format_application_message(job: Job, tailoring: TailoringResult) -> str:
    """Render a job + its tailored resume highlights as an HTML message body."""
    lines = [f"<b>{escape(job.title)}</b> — {escape(job.company)}"]
    if job.location:
        lines.append(escape(job.location))
    lines.append(f'<a href="{escape(str(job.url))}">View posting</a>')
    lines.append("")
    lines.append("<b>Tailored resume highlights</b>")
    for bullet in tailoring.bullets:
        lines.append(f"• {escape(bullet.text)}")
    if not tailoring.is_grounded:
        lines.append("")
        lines.append("⚠️ Some suggestions were withheld: not grounded in your master resume.")
    lines.append("")
    lines.append("Approve to record your intent to apply, or Skip to pass.")
    return "\n".join(lines)


def decision_ack(*, approved: bool) -> str:
    """Short confirmation shown after a decision is recorded."""
    return "✅ Approved — recorded." if approved else "⏭️ Skipped."


def format_submission_message(job: Job, outcome: SubmissionOutcome, detail: str) -> str:
    """Render the outcome of an assisted-submission attempt as an HTML message body."""
    title, company = escape(job.title), escape(job.company)
    link = f'<a href="{escape(str(job.url))}">Open the posting</a>'
    if outcome is SubmissionOutcome.SUBMITTED:
        return (
            f"✅ <b>Applied</b> — {title} at {company}.\n"
            f"I submitted your application on your behalf.\n{link}"
        )
    if outcome is SubmissionOutcome.NEEDS_HUMAN:
        return (
            f"🔗 <b>Needs you</b> — {title} at {company}.\n"
            f"I couldn't safely auto-apply ({escape(detail)}). Please finish it yourself:\n{link}"
        )
    return (
        f"⚠️ <b>Couldn't apply</b> — {title} at {company} ({escape(detail)}).\n"
        f"You can still apply directly:\n{link}"
    )


_STATUS_HEADLINE: dict[ApplicationStatus, str] = {
    ApplicationStatus.INTERVIEW_INVITED: "🎯 <b>Interview invited</b>",
    ApplicationStatus.INTERVIEW_SCHEDULED: "📅 <b>Interview scheduled</b>",
    ApplicationStatus.OFFERED: "🎉 <b>Offer</b>",
    ApplicationStatus.REJECTED: "🚫 <b>Rejection</b>",
    ApplicationStatus.GHOSTED: "👻 <b>No response</b>",
}


def format_email_update_message(job: Job, status: ApplicationStatus, summary: str) -> str:
    """Render a Telegram notification for a status change driven by an inbound email."""
    headline = _STATUS_HEADLINE.get(status, f"<b>Status: {escape(status.value)}</b>")
    title, company = escape(job.title), escape(job.company)
    lines = [f"{headline} — {title} at {company}."]
    if summary:
        lines.append(escape(summary))
    return "\n".join(lines)


def format_offer_card(job: Job) -> str:
    """Render one open-offer card (shown by ``/accept`` with an Accept button)."""
    title, company = escape(job.title), escape(job.company)
    lines = [f"🎉 <b>Offer</b> — {title} at {company}."]
    if job.location:
        lines.append(escape(job.location))
    lines.append(f'<a href="{escape(str(job.url))}">View posting</a>')
    lines.append("")
    lines.append("Tap Accept to mark this offer accepted.")
    return "\n".join(lines)


def accept_ack() -> str:
    """Short confirmation shown after an offer is accepted."""
    return "🎉 Offer accepted."


def format_ghosted_message(job: Job, *, quiet_days: int) -> str:
    """Render the terminal nudge sent when the sweep flags an application GHOSTED."""
    title, company = escape(job.title), escape(job.company)
    return (
        f"👻 <b>No response</b> — {title} at {company}.\n"
        f"No reply in {quiet_days}+ days, so I've marked this as ghosted. "
        f"If they do reach out, forwarding the email will re-open it."
    )
