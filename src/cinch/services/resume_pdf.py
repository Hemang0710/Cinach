"""Render a master résumé to a PDF byte string with **fpdf2** (pure Python).

Pure and framework-free — no Playwright, no I/O, no system libs — so this works on
every deployment target including Render's free tier, without shipping Chromium.

**Anti-fabrication by construction:** only content from the user's stored master
résumé is emitted. When a :class:`TailoringResult` is supplied, its bullets are
substituted **only where** ``bullet.source_text`` exactly matches a master bullet
AND the bullet is ``grounded``. Ungrounded / mismatched tailored bullets are
ignored — the master bullet is rendered as-is — so nothing invented can slip in.
"""

from __future__ import annotations

from fpdf import FPDF

from cinch.domain.models import TailoredBullet, TailoringResult
from cinch.domain.resume import ExperienceEntry, MasterResume

# Common Unicode punctuation → ASCII fallback (so em-dashes / smart quotes don't
# become "?" when the whole résumé is encoded to Latin-1 for the core PDF font).
_PUNCT_MAP = str.maketrans(
    {
        "—": "-",  # em dash
        "–": "-",  # en dash  # noqa: RUF001
        "‘": "'",  # left single quotation mark  # noqa: RUF001
        "’": "'",  # right single quotation mark  # noqa: RUF001
        "“": '"',  # left double quotation mark
        "”": '"',  # right double quotation mark
        "…": "...",  # ellipsis
        "•": "*",  # bullet
    }
)


def _latin1(text: str) -> str:
    """Best-effort Latin-1 for fpdf2's core Helvetica font.

    Latin-1 accented letters (é, ñ, ü, …) are preserved as-is. Common Unicode
    punctuation is transliterated to ASCII. Everything else (emoji, CJK) falls back
    to ``?``. Sufficient for English/European résumés; a bundled Unicode TTF would
    be needed for faithful non-Latin rendering.
    """
    if not text:
        return ""
    return text.translate(_PUNCT_MAP).encode("latin-1", "replace").decode("latin-1")


def _tailored_lookup(tailoring: TailoringResult | None) -> dict[str, str]:
    """Map ``source_text -> tailored text`` for every grounded tailored bullet.

    Ungrounded bullets are excluded so an LLM rewrite that failed the grounding
    check never reaches the rendered PDF, even if the caller passed it in.
    """
    if tailoring is None:
        return {}
    return {b.source_text: b.text for b in tailoring.bullets if _use_tailored(b)}


def _use_tailored(bullet: TailoredBullet) -> bool:
    """A tailored bullet is only safe to substitute when the grounding check passed."""
    return bullet.grounded


# Units below are millimetres — fpdf2's default, and where its layout math is best
# tested. Letter is 216 x 279 mm; 18 mm margins leave ~180 mm of usable width.
_MARGIN = 18


class _ResumePDF(FPDF):
    """Small FPDF subclass with margins tuned for a single-page résumé (mm units)."""

    def __init__(self) -> None:
        super().__init__(format="Letter")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(left=_MARGIN, top=_MARGIN, right=_MARGIN)


def render_master_resume_pdf(
    master: MasterResume, tailoring: TailoringResult | None = None
) -> bytes:
    """Render ``master`` (optionally with tailored bullets substituted) as PDF bytes."""
    swap = _tailored_lookup(tailoring)
    pdf = _ResumePDF()
    pdf.add_page()
    # A font MUST be set before the first cell so fpdf2 can measure line breaks.
    pdf.set_font("Helvetica", "", 10)

    _header(pdf, master)
    if master.summary:
        _section(pdf, "Summary")
        _paragraph(pdf, master.summary)
    if master.skills:
        _section(pdf, "Skills")
        _paragraph(pdf, ", ".join(master.skills))
    if master.experiences:
        _section(pdf, "Experience")
        for exp in master.experiences:
            _experience(pdf, exp, swap)
    if master.education:
        _section(pdf, "Education")
        for edu in master.education:
            _paragraph(
                pdf,
                f"{edu.degree}, {edu.institution}" + (f" ({edu.year})" if edu.year else ""),
            )

    return bytes(pdf.output())


def _content_width(pdf: FPDF) -> float:
    """The horizontal space between the left and right margins, in the pdf's units."""
    return float(pdf.w - pdf.l_margin - pdf.r_margin)


def _header(pdf: _ResumePDF, master: MasterResume) -> None:
    w = _content_width(pdf)
    if master.name:
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(w, 9, _latin1(master.name), new_x="LMARGIN", new_y="NEXT")
    contact_bits = [master.email, master.phone]
    contact = " | ".join(_latin1(c) for c in contact_bits if c)
    if contact:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(w, 5, contact, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)


def _section(pdf: _ResumePDF, title: str) -> None:
    w = _content_width(pdf)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_draw_color(160, 160, 160)
    pdf.cell(w, 6, _latin1(title.upper()), new_x="LMARGIN", new_y="NEXT", border="B")
    pdf.ln(1)


def _paragraph(pdf: _ResumePDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 10)
    # new_x=LMARGIN resets the cursor to the left margin; without it fpdf2 leaves
    # it at the right of the last line, so the next cell renders off-page.
    pdf.multi_cell(_content_width(pdf), 5, _latin1(text), new_x="LMARGIN", new_y="NEXT")


def _experience(pdf: _ResumePDF, exp: ExperienceEntry, swap: dict[str, str]) -> None:
    """Render one experience entry with bullets (tailored where a grounded swap exists)."""
    w = _content_width(pdf)
    dates = f"{exp.start} - {exp.end}" if exp.end else f"{exp.start} - Present"

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(w, 5, _latin1(f"{exp.title}, {exp.company}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(w, 4, _latin1(dates), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    if exp.bullets:
        pdf.set_font("Helvetica", "", 10)
        for bullet in exp.bullets:
            display = swap.get(bullet, bullet)
            # new_x=LMARGIN is essential: the default leaves the cursor at the line's
            # right edge, so bullet 2+ would render off-page and get truncated.
            pdf.multi_cell(w, 5, _latin1(f"* {display}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
