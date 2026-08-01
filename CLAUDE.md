# CLAUDE.md — Job Application Assistant

Open-source, human-in-the-loop job-application assistant: LLM resume tailoring +
a Telegram bot that sends jobs with Approve/Skip buttons. Nothing is submitted
without explicit user approval.

## Commands
- Install:      `uv sync`
- Run API:      `uv run uvicorn app.api.main:app --reload`
- Tests:        `uv run pytest`  (single test: `uv run pytest path::test_name`)
- Lint/format:  `uv run ruff check --fix .` and `uv run ruff format .`
- Types:        `uv run mypy src/`
- Migrations:   `uv run alembic upgrade head` / `uv run alembic revision --autogenerate -m "msg"`

## Architecture (keep layers separate)
- `bot/` Telegram handlers/keyboards — thin, no business logic.
- `api/` FastAPI webhook (verifies secret token) + health endpoints.
- `services/` orchestration + domain logic — NO framework imports.
- `providers/` pluggable adapters: `LLMProvider`, `JobSource`, optional `Submitter`.
- `domain/` models (User, Resume, Job, Application) + status enums.
- `db/` SQLAlchemy 2.0 async models, repositories, session factory, Alembic.
- `core/` config (pydantic-settings), logging, security, rate limiting.
Business logic receives dependencies via injection; no global singletons.

## Do / Don't
- DO rephrase REAL resume content only. NEVER invent employers, titles, dates,
  metrics, or skills. Every tailored bullet must be grounded in the master resume.
- DO keep humans in the loop: discover → tailor → ask → user approves → act.
- DON'T build unattended bulk auto-apply. DON'T scrape LinkedIn/Indeed; use
  official APIs behind `JobSource`.
- DON'T commit secrets. Config via env/pydantic-settings only. `.env` is local.
- DON'T add a dependency without a clear reason.

## Security rules (YOU MUST)
- Verify `X-Telegram-Bot-Api-Secret-Token` on every webhook request with a
  constant-time compare; return 403 on mismatch.
- Authorize every callback_query against the owning user_id.
- Validate all external input with Pydantic; reject unexpected shapes.
- Rate-limit + backoff outbound Telegram sends. Redact PII from logs.
- Idempotent writes: approving/applying the same job twice is a no-op.

## Testing expectations
- Every service/provider has unit tests with mocked LLM + HTTP (no live calls).
- Async tests for the webhook. A test MUST prove fabricated resume content is
  rejected. Target ≥80% coverage on `services/`.
- Run ruff, mypy, and pytest before declaring work done; show the output.

## Workflow
- Explore → plan → code → verify. Use plan mode for multi-file changes.
- After a phase, use a fresh subagent to review the diff for security/correctness.
- Prefer running single tests during iteration. Commit with descriptive messages.
- Ask before: schema/migration changes, new external services, anything touching
  secrets or ToS. These need human review.