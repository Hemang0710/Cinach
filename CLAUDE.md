# CLAUDE.md

Guidance for AI coding agents (and humans) working in this repository.

## What Cinch is

An open-source, **human-in-the-loop** job application assistant:

1. **Resume tailoring** — an LLM rewrites/reorders a user's *master* resume to
   match a job description. It **rephrases real experience only** — never invents
   employers, titles, dates, metrics, or skills.
2. **Job discovery + Telegram approval** — discovers jobs from official APIs,
   tailors the resume, and sends the user the job + tailored resume with
   **Approve / Skip** inline buttons. **Nothing is submitted until the user
   approves.**

## Non-negotiable constraints

- Human-in-the-loop is mandatory. No unattended bulk auto-apply.
- Do NOT scrape LinkedIn/Indeed. Prefer official/licensed job APIs (Adzuna
  first) behind a pluggable `JobSource` interface.
- Never fabricate resume content; a validation step must flag any tailored
  bullet not grounded in the master resume.
- Never commit secrets. Config via environment / `pydantic-settings`.
- Provider-agnostic LLM layer (Anthropic / Groq / OpenAI / Google) behind one interface.

## Architecture (`src/cinch/`)

| Package      | Responsibility                                                    |
| ------------ | ----------------------------------------------------------------- |
| `api/`       | FastAPI app, webhook route (secret-token verified), health probes |
| `bot/`       | Telegram handlers, inline keyboards, callback routing (thin)      |
| `services/`  | Orchestration + domain logic; no framework imports leak in        |
| `providers/` | Adapters: `LLMProvider`, `JobSource`, optional `Submitter`        |
| `domain/`    | Pydantic/dataclass models + status enums                          |
| `db/`        | SQLAlchemy models, repositories, session factory, Alembic         |
| `core/`      | config (`pydantic-settings`), logging, security, rate limiting    |

Use dependency injection (pass sessions/providers in). Bot/API layers are
stateless so they scale horizontally.

## Commands

```bash
uv sync --extra dev            # install deps
uv sync --extra submit         # optional: Phase 6 submission (then: playwright install chromium)
uv run python -m cinch.api     # run the API (http://localhost:8000)
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy                    # strict type check
uv run pytest                  # tests + coverage
```

## Phased build plan

Build **one phase per session**, then STOP for human review. See
[PROMPT.md](PROMPT.md) for the full plan.

- **Phase 0** — Scaffolding (this repo's current state). ✅
- **Phase 1** — Domain + DB (models, repositories, Alembic migration).
- **Phase 2** — LLM tailoring + anti-fabrication validator.
- **Phase 3** — Telegram bot (webhook, onboarding, Approve/Skip, auth).
- **Phase 4** — Job discovery + orchestration (Adzuna, scheduler, idempotency).
- **Phase 5** — Hardening + docs.
- **Phase 6** (optional) — Playwright assisted submission. ✅ Off by default; only
  auto-submits **user-Approved** applications and never bypasses logins/CAPTCHAs.

## Conventions

- Type-hint everything; pass `mypy --strict` and `ruff` with zero errors.
- Validate all external input with Pydantic.
- Conventional Commits; GitHub Flow branching (see [CONTRIBUTING.md](CONTRIBUTING.md)).
