# SPEC — Phase 9: Tailored résumé PDF to Telegram

## Goal

Every Approve/Skip card now carries the user's **tailored résumé as a `.pdf`
attachment**, so they can preview exactly what would be submitted before tapping
Approve. Solves the biggest transparency gap: today users see only rewritten
"highlights" in the card body but not the actual document that would go out.

## Non-goals

- Not changing the auto-submission pipeline (Phase 6 still submits the master
  résumé; a follow-up phase can swap in the tailored PDF there too).
- Not swapping in a Chromium/HTML renderer — this phase deliberately avoids
  adding ~200 MB and a system-package burden to the runtime image.
- No new commands or user-visible state changes.

## Design

- **Pure-Python renderer**: new `services/resume_pdf.py` uses **fpdf2** (MIT,
  pure Python, no system libs) to render a MasterResume to PDF bytes. Works
  on Render's free tier with no extra install steps.
- **Anti-fabrication by construction**: the renderer only emits content from
  the user's real master résumé. When a `TailoringResult` is supplied, bullets
  are substituted **only where** `bullet.source_text` exactly matches a master
  bullet AND `bullet.grounded is True`. Ungrounded or mismatched tailored
  bullets are ignored — the master bullet is rendered as-is. So the anti-
  fabrication guarantee that Phase 2's grounding validator gives is preserved
  end-to-end: nothing invented can slip into the PDF.
- **Fail-soft delivery**: `JobNotifier.notify` gains an **optional**
  `resume_pdf: bytes | None = None` kwarg. The discovery orchestrator renders
  the PDF and passes it; if rendering raises, we log and pass `None` — the
  Approve/Skip card still ships (losing an attachment is a smaller regression
  than losing the whole notification).
- **Latin-1 core font + punctuation fallback**: fpdf2's core Helvetica is
  Latin-1 only. A small `_PUNCT_MAP` transliterates common Unicode punctuation
  (em/en dashes, smart quotes, ellipsis, bullet) to ASCII; accented Latin-1
  characters (é, ñ, ü) pass through as-is; genuinely non-Latin codepoints
  (emoji, CJK) fall back to `?`. Sufficient for English/European résumés.

## Interfaces & files

**New:**
- `src/cinch/services/resume_pdf.py` — `render_master_resume_pdf(master, tailoring=None) -> bytes`
  plus the internal `_tailored_lookup`, `_latin1`, `_ResumePDF`, and section
  helpers.
- `tests/test_resume_pdf.py` — 9 tests: valid PDF magic, empty master, deterministic
  output, grounded lookup filter, substitution changes PDF, ungrounded /
  unmatched substitution leaves it identical, Latin-1 normaliser.
- `tests/test_notify.py` — 3 tests: send_application skips `send_document` when
  no PDF; attaches it (with `filename="resume.pdf"`) when provided; TelegramNotifier
  forwards the kwarg.

**Modified:**
- `src/cinch/bot/notify.py` — `send_application` + `TelegramNotifier.notify`
  accept optional `resume_pdf`; when present, `bot.send_document(...)` follows
  the card message.
- `src/cinch/services/discovery.py` — `JobNotifier` protocol gains the same
  optional kwarg. `_process_job` renders the PDF via new fail-soft helper
  `_render_resume_pdf_or_none(master, tailoring)` and passes it to `notifier.notify`.
- `pyproject.toml` — add `fpdf2>=2.7` (pure Python, ~1 MB with fonttools+pillow).
- Docs: README/CLAUDE line about the new attachment.

## Safety properties (asserted by tests)

1. Rendered PDF is valid (`%PDF-` magic, `%%EOF` in trailer).
2. Same master → same output bytes (ignoring the fpdf timestamp trailer).
3. `_tailored_lookup` includes only bullets with `grounded=True`.
4. A grounded substitution actually changes the output PDF.
5. An **ungrounded** substitution produces the SAME bytes as the baseline (proof
   nothing invented leaked through).
6. A tailored bullet whose `source_text` doesn't match any master bullet also
   produces the baseline PDF (safe fallback).
7. `send_application` without `resume_pdf` never calls `bot.send_document`.
8. With `resume_pdf`, `bot.send_document` is called once with `filename="resume.pdf"`.

## Verification

- `uv run ruff check .` / `ruff format --check .` / `uv run mypy` / `uv run pytest`
  — all green, coverage ≥ 80%.
- Manual smoke (post-deploy): trigger `/discover`; each Approve/Skip card is now
  followed by a `resume.pdf` file message you can tap to preview.

## Out of scope (future work)

- Bundling a Unicode TTF (DejaVu Sans, ~750 KB) for faithful non-Latin
  rendering — Latin-1 fallback is sufficient for English résumés.
- Refactoring Phase 6's `PlaywrightSubmitter` to reuse this pure-Python
  renderer (would drop the Chromium requirement for auto-submission too).
- Server-side PDF thumbnails / preview panels (Phase 10 dashboard territory).
