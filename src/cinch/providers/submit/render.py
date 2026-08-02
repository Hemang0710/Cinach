"""Render a master resume to a self-contained, printable HTML document.

Pure and framework-free — no Playwright, no I/O — so it is fully unit-testable. The
Playwright adapter turns this HTML into a PDF via ``page.pdf()``. **Anti-fabrication
by construction:** only real content from the user's stored master resume is emitted,
and every dynamic value is HTML-escaped before it reaches the markup.
"""

from __future__ import annotations

from html import escape

from cinch.domain.resume import MasterResume

_STYLE = (
    "body{font-family:Arial,Helvetica,sans-serif;font-size:11pt;color:#111;margin:2.5em;}"
    "h1{font-size:20pt;margin:0 0 2px;}"
    "h2{font-size:12pt;border-bottom:1px solid #999;margin:16px 0 6px;text-transform:uppercase;}"
    ".contact{color:#333;margin-bottom:4px;}"
    ".role{font-weight:bold;}.dates{color:#555;font-weight:normal;}"
    "ul{margin:4px 0 10px;padding-left:18px;}"
)


def build_resume_html(master: MasterResume) -> str:
    """Render ``master`` as a single-column HTML resume (real content only)."""
    e = escape
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<style>{_STYLE}</style></head><body>",
    ]

    if master.name:
        parts.append(f"<h1>{e(master.name)}</h1>")
    contact = " · ".join(e(c) for c in (master.email, master.phone) if c)
    if contact:
        parts.append(f'<div class="contact">{contact}</div>')

    if master.summary:
        parts.append("<h2>Summary</h2>")
        parts.append(f"<p>{e(master.summary)}</p>")

    if master.skills:
        parts.append("<h2>Skills</h2>")
        parts.append(f"<p>{e(', '.join(master.skills))}</p>")

    if master.experiences:
        parts.append("<h2>Experience</h2>")
        for exp in master.experiences:
            dates = e(exp.start) + (f" &ndash; {e(exp.end)}" if exp.end else " &ndash; Present")
            parts.append(
                f'<div class="role">{e(exp.title)}, {e(exp.company)} '
                f'<span class="dates">({dates})</span></div>'
            )
            if exp.bullets:
                parts.append("<ul>")
                parts.extend(f"<li>{e(b)}</li>" for b in exp.bullets)
                parts.append("</ul>")

    if master.education:
        parts.append("<h2>Education</h2>")
        for edu in master.education:
            year = f" ({e(edu.year)})" if edu.year else ""
            parts.append(f"<div>{e(edu.degree)}, {e(edu.institution)}{year}</div>")

    parts.append("</body></html>")
    return "\n".join(parts)
