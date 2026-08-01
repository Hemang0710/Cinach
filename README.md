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
- **Phase 1** — Domain models + database.
- **Phase 2** — LLM tailoring + anti-fabrication validator.
- **Phase 3** — Telegram bot (webhook, onboarding, Approve/Skip).
- **Phase 4** — Job discovery + orchestration (Adzuna, scheduler).
- **Phase 5** — Hardening + docs.
- **Phase 6** *(optional)* — Playwright assisted submission.

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for the
development setup, branching model (GitHub Flow), and quality gates. By
participating you agree to our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Found a vulnerability? Please report it privately — see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Hemang P
