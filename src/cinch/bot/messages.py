"""Rendering of user-facing Telegram messages.

Presentation only — no business logic. All dynamic text is HTML-escaped before it
reaches Telegram's HTML parse mode, so a job title or bullet containing ``<`` / ``&``
cannot break the markup or inject tags.
"""

from __future__ import annotations

from html import escape

from cinch.domain.models import Job, TailoringResult


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
