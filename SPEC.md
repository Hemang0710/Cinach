# SPEC — Phase 8: PDF résumé ingestion

## Goal

Let a user upload their **actual PDF résumé** to the Telegram bot and have it saved
as their master résumé, without hand-crafting the JSON. Solves the biggest UX gap:
today users must translate their real résumé into Cinch's strict schema by hand,
and getting one field wrong means the upload is rejected.

## Non-goals

- No new tailoring / discovery / submission behaviour changes.
- Not a general-purpose parser. Optimised for reasonably-formatted PDF résumés.
- Not a PDF-in / PDF-out flow (that's Phase 9).

## Behaviour (bot flow)

1. User sends any `.pdf` file to the bot.
2. Bot: **"🔎 Parsing your résumé…"**
3. Text extracted with `pypdf`. If the PDF is image-only (no extractable text) →
   *"Couldn't read text from that PDF (image-only?). Please send a text-based PDF
   or your résumé as .json (see /setresume)."*
4. LLM (whatever provider is configured — Groq / Anthropic) structures the text
   into Cinch's exact `MasterResume` schema.
5. **Anti-fabrication guard** — every string field in the parsed résumé must appear
   (normalised substring) in the extracted PDF text. Fabricated content is
   rejected: `"That parse produced fields I couldn't verify in the PDF text — try
   the .json path instead."`
6. Saved as the user's master résumé (upsert; overwrites any existing).
7. Bot: **"✅ Saved master résumé — parsed X experience(s) and Y skill(s). Send
   /discover to pull matching jobs, or resend the PDF to overwrite."**

## Design (mirrors the existing tailoring pipeline)

- **Extraction stays a pure function**: `extract_text_from_pdf(bytes) -> str` in
  `services/pdf_ingest.py`, no I/O, unit-testable with tiny fixture PDFs.
- **Structuring is provider-agnostic**: `PDFIngestService` depends on
  `LLMProvider` (same interface tailoring uses). New system prompt in
  `services/prompts.py` — versioned like `SYSTEM_PROMPT` there. Instructs the LLM
  to **copy fields verbatim** from the input, never rewrite / paraphrase.
- **Grounding validator lives with the service**: after Pydantic validation,
  every scalar string field (`name`, `email`, summary, skills, experience bullets,
  education entries…) is normalised (lowercase + collapse whitespace + strip
  non-alphanumeric) and required to be a substring of the same-normalised PDF text.
  If any field fails, the whole ingest is rejected — never silently keep partial.
- **Handler is thin**: `document_handler` gains a second branch. `.json` → existing
  path. `.pdf` → `PDFIngestService.ingest` → `set_master`. Same 1 MB size cap.
  No pending-confirmation state to keep the bot layer stateless.

## New files

- `src/cinch/services/pdf_ingest.py` — `extract_text_from_pdf`, `PDFIngestError`,
  `PDFIngestService.ingest(pdf_bytes) -> MasterResume`, plus a `_ground_or_raise`
  helper that walks the parsed résumé and validates every string.
- `tests/test_pdf_ingest.py` — extraction on a real tiny PDF fixture; grounding
  passes on faithful output; grounding rejects fabricated skills/experience;
  handler routes `.pdf` correctly; empty/image-only PDF handled cleanly.

## Modified files

- `src/cinch/services/prompts.py` — add `PDF_INGEST_SYSTEM_PROMPT` (verbatim-copy
  rules) + `build_pdf_ingest_user_prompt(text)`. Bump/version separately.
- `src/cinch/bot/handlers.py` — `document_handler` routes on file extension:
  `.json` → existing; `.pdf` → `PDFIngestService`. Welcome text updated to mention
  "send your résumé as .json OR .pdf".
- `pyproject.toml` — add `pypdf>=5.0` (small pure-Python PDF extractor).
- `README.md` / `CLAUDE.md` — one-line mention of PDF upload support.

## Safety properties (asserted by tests)

1. `.pdf` upload with valid text → saved successfully.
2. `.pdf` upload with fabricated content (mocked LLM adds a skill not in PDF) →
   rejected, nothing saved.
3. Image-only / unreadable PDF → clean error message, no crash, nothing saved.
4. `.json` upload path unchanged.
5. Oversized upload (>1 MB) still rejected before download.

## Verification

- `uv run ruff check .` / `ruff format --check .` / `uv run mypy` / `uv run pytest`
  — all green, coverage ≥ 80%.
- New tests use mocked `LLMProvider` (no live API calls) and a tiny in-memory PDF
  built with `pypdf.PdfWriter` or a pre-recorded byte string.
- Manual smoke (post-deploy): send your actual résumé PDF to the bot → verify
  "Saved master résumé — parsed N experience(s)" appears → `/discover` works.

## Out of scope for this phase (future work)

- Confirmation UI (Approve/Reject buttons showing the parsed JSON before save) —
  keeping the flow minimal; users can re-upload to overwrite.
- OCR for image-only PDFs (would need a heavy dependency; better to tell the user).
- DOCX / other formats.
