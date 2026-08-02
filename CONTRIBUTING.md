# Contributing to Cinch

Thanks for your interest in improving Cinch! This document explains how to set
up your environment, our branching model, and the checks your change must pass.

## Guiding principles

Cinch is a **human-in-the-loop** job application assistant. Two rules are
non-negotiable and must never be weakened by a contribution:

1. **Never fabricate resume content.** Tailoring means keyword alignment,
   reordering, and emphasis of *real* experience — never inventing employers,
   titles, dates, metrics, or skills.
2. **Nothing is submitted without explicit human approval.** No unattended bulk
   auto-apply. Do not scrape LinkedIn/Indeed; prefer official/licensed job APIs.

## Development setup

Cinch uses [`uv`](https://docs.astral.sh/uv/) for packaging and a `src/` layout.

```bash
# Install dependencies (runtime + dev tools) into a local virtualenv
uv sync --extra dev

# Run the API locally (http://localhost:8000)
uv run python -m cinch.api
# → GET /healthz and /readyz should both return 200
```

Copy `.env.example` to `.env` for local configuration. **Never commit `.env` or
any real secret.**

## Branching model — GitHub Flow

`main` is always deployable and protected. All work happens on short-lived
branches that are merged into `main` via pull request.

Branch naming:

| Prefix      | Use for                                             |
| ----------- | --------------------------------------------------- |
| `feature/`  | new functionality                                   |
| `fix/`      | bug fixes                                            |
| `chore/`    | tooling, deps, CI, scaffolding                       |
| `docs/`     | documentation-only changes                          |
| `hotfix/`   | urgent production fix branched from `main`          |

Example: `git checkout -b feature/adzuna-job-source`

Flow: branch off `main` → commit → open PR → CI green + at least one review →
squash-merge → the branch is auto-deleted.

## Commit messages — Conventional Commits

Use the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(optional scope): <description>
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `perf`.

Example: `feat(bot): add Approve/Skip inline keyboard`

## Quality gates (must pass before merge)

Run these locally; CI enforces the same:

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy                    # strict type checking
uv run pytest                  # tests + coverage (fails under 80%)
```

`pytest` enforces a minimum coverage of **80%** (`--cov-fail-under=80`); CI runs the
same matrix on Python 3.11–3.14.

Optionally install the pre-commit hooks so these run automatically:

```bash
uvx pre-commit install
uvx pre-commit run --all-files
```

## Pull requests

- Keep PRs focused and small where possible.
- Fill in the PR template checklist.
- Add tests for new behaviour; do not lower coverage.
- Never include secrets, credentials, or real personal data.

## Reporting security issues

Please do **not** open a public issue for vulnerabilities. See
[SECURITY.md](SECURITY.md) for private disclosure.
