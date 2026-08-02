# Cinch

[![CI](https://github.com/Hemang0710/Cinach/actions/workflows/ci.yml/badge.svg)](https://github.com/Hemang0710/Cinach/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Hemang0710/Cinach/actions/workflows/codeql.yml/badge.svg)](https://github.com/Hemang0710/Cinach/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Checked with mypy](https://img.shields.io/badge/mypy-strict-2a6db2.svg)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**Cinch** is an open-source, **human-in-the-loop** job application assistant. It
discovers roles from official job APIs, uses an LLM to tailor your master resume
to each posting — *rephrasing your real experience, never fabricating it* — and
sends the job plus the tailored resume straight to your Telegram with **Approve**
and **Skip** buttons. Nothing is submitted until you tap Approve.

Built to be safer than bulk auto-appliers, kinder to your accounts, and to
produce better applications than spraying hundreds of generic ones.

## Why Cinch

- **Human-in-the-loop by design** — no unattended bulk auto-apply. You approve
  every application from your phone.
- **Never fabricates** — tailoring is keyword alignment, reordering, and
  emphasis of your *real* experience. A validation step flags any bullet not
  grounded in your master resume.
- **Plays fair** — uses official/licensed job APIs (Adzuna first) behind a
  pluggable interface, not scraping.
- **Provider-agnostic LLM** — Anthropic / OpenAI / Google behind one interface.

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
# Install dependencies
uv sync --extra dev

# Configure (copy the template, then fill in your values — never commit .env)
cp .env.example .env

# Run the API
uv run python -m cinch.api
# → http://localhost:8000/healthz and /readyz return 200
```

Run the full test + quality suite:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Or bring up the local stack (app + postgres + redis):

```bash
docker compose up --build
```

## Architecture

Clean separation of concerns under `src/cinch/`:

| Package      | Responsibility                                                    |
| ------------ | ----------------------------------------------------------------- |
| `api/`       | FastAPI app, Telegram webhook (secret-token verified), health     |
| `bot/`       | Telegram handlers, inline keyboards, callback routing (thin)      |
| `services/`  | Orchestration + domain logic (tailoring, matching, workflow)      |
| `providers/` | Pluggable adapters: `LLMProvider`, `JobSource`, `Submitter`       |
| `domain/`    | Pydantic/dataclass models + status enums                          |
| `db/`        | SQLAlchemy 2.0 async models, repositories, Alembic migrations     |
| `core/`      | config (`pydantic-settings`), logging, security, rate limiting    |

## Roadmap

Cinch is built in reviewable phases (see [PROMPT.md](PROMPT.md)):

- **Phase 0** — Scaffolding (repo structure, tooling, CI). ✅
- **Phase 1** — Domain models + database. ✅
- **Phase 2** — LLM tailoring + anti-fabrication validator. ✅
- **Phase 3** — Telegram bot (webhook, onboarding, Approve/Skip). ✅
- **Phase 4** — Job discovery + orchestration (Adzuna, scheduler). ✅
- **Phase 5** — Hardening + docs (PII encryption, Sentry, health, coverage). ✅
- **Phase 6** *(optional)* — Playwright assisted submission (opt-in, off by default). ✅

## Configuration

All configuration is via environment variables (see [.env.example](.env.example));
never commit a real `.env`. Key settings:

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `DATABASE_URL` | SQLAlchemy async URL (SQLite locally, Postgres in prod) | SQLite file |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` | Bot auth + webhook verification | — |
| `TELEGRAM_WEBHOOK_URL` | Public HTTPS base; when set, the webhook self-registers | — |
| `LLM_PROVIDER` / `ANTHROPIC_API_KEY` / `LLM_MODEL` | Tailoring LLM | anthropic / `claude-opus-4-8` |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` / `ADZUNA_COUNTRY` | Job source (official API) | — / — / `us` |
| `DISCOVERY_ENABLED` / `DISCOVERY_INTERVAL_MINUTES` | Discovery scheduler (off by default) | `false` / `60` |
| `ENCRYPTION_KEY` | Fernet key encrypting resume PII at rest (plaintext if unset) | — |
| `SENTRY_DSN` | Error monitoring (off if unset) | — |
| `SUBMISSION_ENABLED` / `SUBMISSION_INTERVAL_MINUTES` | Assisted submission (opt-in; see below) | `false` / `5` |

## Observability

- **Structured logs** — JSON logs (structlog) in production; every request carries a
  correlation `X-Request-ID`, and a redaction step masks secrets/PII so they never
  reach a log line.
- **Error monitoring** — Sentry initialises only when `SENTRY_DSN` is set, PII-safe
  (`send_default_pii=False` plus request-body scrubbing).
- **Health probes** — `GET /healthz` (liveness) and `GET /readyz` (readiness — verifies
  the database is reachable, `503` when it isn't).
- **PII at rest** — resume content is encrypted with Fernet when `ENCRYPTION_KEY` is set.

## Job sources & terms of service

Cinch discovers roles only through **official, licensed job APIs** — never by
scraping. The first adapter is [Adzuna](https://developer.adzuna.com/):

- **Credentials** are per-developer (`ADZUNA_APP_ID` / `ADZUNA_APP_KEY`), supplied
  via environment only and never committed.
- **Rate limits are respected** — discovery runs on an infrequent interval
  (`DISCOVERY_INTERVAL_MINUTES`, default 60) with a small per-user result cap
  (`DISCOVERY_RESULTS_PER_USER`, default 5), and a single non-overlapping scheduler job.
- **Attribution + linking** — every posting sent to you links to Adzuna's official
  `redirect_url` ("Jobs by Adzuna"); Cinch never republishes listings.
- **Off by default** — the discovery scheduler only runs when `DISCOVERY_ENABLED=true`.
  Enabling it is a deliberate operational choice.

Swapping in another licensed source is a matter of implementing the `JobSource`
interface; the orchestration layer is source-agnostic.

## Assisted submission (experimental, opt-in)

Phase 6 adds **optional** Playwright-based assisted submission. It is **off by default**
and, when enabled, only ever submits applications you have **already Approved** on
Telegram — there is no unattended bulk auto-apply.

> ⚠️ **Terms-of-Service risk.** Automatically submitting applications may violate a job
> site's Terms of Service and could put your accounts at risk. Enabling this is a
> deliberate operational choice you make **at your own risk**. Cinch never bypasses logins
> or CAPTCHAs — those are handed back to you with the apply link.

When `SUBMISSION_ENABLED=true`:

- The submitted resume is your **real master resume**, rendered to a PDF — nothing is
  fabricated (no LLM runs at submit time).
- The submitter auto-fills and submits only a form it can confidently recognize. Anything
  needing a login, a CAPTCHA, or an unrecognized form comes back to you as **"needs you"**
  with the direct apply link.
- An application is never submitted twice.

Enable it (needs the `submit` extra and a browser binary):

```bash
uv sync --extra submit
playwright install chromium
```

Then set `SUBMISSION_ENABLED=true` (see [.env.example](.env.example) for all submission
settings). Add the master-resume contact fields (`name`, `email`, `phone`) so forms can be
filled — without them, applications are handed back to you rather than submitted blind.

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for the
development setup, branching model (GitHub Flow), and quality gates. By
participating you agree to our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Found a vulnerability? Please report it privately — see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Hemang P
