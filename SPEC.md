# SPEC — Phase 6: Playwright assisted submission

## Goal

After a user taps **Approve** on a discovered job, an **optional**, off-by-default
pipeline uses Playwright to **auto-submit the application when it can do so safely**,
and otherwise hands the application back to the user on Telegram with the apply link.

This stays within the project's human-in-the-loop constraint: submission only ever acts
on applications the user has **already individually Approved**. There is no unattended
bulk auto-apply. It is enabled only by `SUBMISSION_ENABLED=true` (default `false`) and
requires the optional `submit` extra plus `playwright install chromium`.

## Behaviour

- The **submitted resume is the user's real master resume**, rendered to a PDF by
  Chromium's own `page.pdf()`. No LLM runs at submit time, so nothing is fabricated.
- The submitter **never bypasses a login or CAPTCHA**, and submits only a form it can
  confidently recognize (contact fields + a file upload + a submit control). Anything
  else — including a missing/invalid master resume or missing name/email — becomes
  `NEEDS_HUMAN`: the bot sends the user the apply link to finish manually.
- **No double-submit.** Each `APPROVED` application is *claimed* (committed out of
  `APPROVED` to a pessimistic `FAILED`/"interrupted" state) **before** any network
  submission, then set to its true terminal state afterwards. A crash mid-submit leaves
  it non-`APPROVED`, so it is never picked up again. `FAILED` is terminal and never
  auto-retried.

## Interfaces & files

New provider package `providers/submit/` (Playwright-free except the adapter):

- `base.py` — `Submitter` Protocol; `SubmissionOutcome` (`SUBMITTED`/`NEEDS_HUMAN`/
  `FAILED`); `SubmissionResult`, `Applicant` dataclasses; `SubmitterError`;
  `get_submitter(settings)` (lazy-imports the adapter; raises `SubmitterError` without
  the extra).
- `render.py` — pure `build_resume_html(master)` (real content only, HTML-escaped).
- `playwright.py` — `PlaywrightSubmitter` (lazy `playwright.async_api`; render PDF,
  safety-gate, best-effort fill + submit; PII-free logging). Integration-only; omitted
  from coverage.
- `fake.py` — `FakeSubmitter` (scripted outcomes for tests).

Service & wiring (mirrors the discovery pipeline):

- `services/submission.py` — `SubmissionService` + `SubmissionNotifier` Protocol +
  `SubmissionSummary`. Takes a `Database` (per-app sessions for the claim/record commits).
- `api/scheduler.py` — `run_submission_cycle` (gated on `submission_enabled`) +
  `start_submission_scheduler` (one non-overlapping interval job).
- `api/app.py` — starts the submission scheduler in the lifespan when enabled + a bot exists.
- `bot/notify.py` + `bot/messages.py` — `TelegramSubmissionNotifier` +
  `format_submission_message` (submitted ✅ / needs-you 🔗 / failed ⚠️).

Domain / persistence:

- `domain/enums.py` — `ApplicationStatus.NEEDS_HUMAN`.
- `domain/resume.py` — `name` / `email` / `phone` on `MasterResume`.
- `db/models.py` + `domain/models.py` — `submitted_at`, `submission_detail` on the application.
- `db/repositories.py` — `list_by_status`, `claim_for_submission`, `record_submission`.
- `migrations/versions/0002_submission_fields.py` — adds the two nullable columns.

Config (all default-safe): `SUBMISSION_ENABLED=false`, `SUBMISSION_INTERVAL_MINUTES=5`,
`SUBMISSION_HEADLESS=true`, `SUBMISSION_TIMEOUT_SECONDS=60`; `submit` pip extra.

## Out of scope

- Per-ATS custom adapters (Greenhouse/Lever/Workday specifics) — the generic form
  heuristic + `NEEDS_HUMAN` handoff is the v1; new adapters implement `Submitter`.
- Solving CAPTCHAs or automating logins (deliberately never done).
- Persisting the exact tailored highlights as the submitted document (the master resume
  is submitted; tailored emphasis is a possible future layer).
- Auto-retrying `FAILED` submissions.

## Verification

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`
  all green; coverage ≥ 80%.
- `test_migrations.py` proves `0002` matches the ORM with no drift.
- `test_submission.py` proves: successful submit, no-double-submit, NEEDS_HUMAN handoffs
  (missing/invalid contact + submitter-reported), FAILED-is-terminal, crash containment,
  notify-failure isolation, claim-once, and the disabled-scheduler no-op.
- Manual (optional): `uv sync --extra submit && playwright install chromium`,
  `SUBMISSION_ENABLED=true` in staging, `/demo` → Approve → observe the outcome message.
