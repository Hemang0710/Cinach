# Security Policy

## Supported versions

Cinch is in early development (0.x). Security fixes are applied to the latest
`main` only until a stable release line is established.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅        |
| < 0.1   | ❌        |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report privately via GitHub Security Advisories:

1. Go to the repository's **Security** tab → **Report a vulnerability**.
2. Provide a description, reproduction steps, and impact assessment.

We aim to acknowledge reports within 72 hours and to provide a remediation
timeline after triage.

## Handling of secrets and PII

Cinch processes personal data (resumes) and holds credentials (Telegram bot
token, LLM API keys). Contributors and operators must:

- **Never commit secrets.** All configuration is loaded from environment
  variables via `pydantic-settings`; see `.env.example`. A secret-scanning
  pre-commit hook and CI check guard against accidental commits.
- **Redact PII from logs.** Do not log raw resume content or personal data.
- **Encrypt PII at rest** where feasible.
- **Verify the Telegram webhook** using the `X-Telegram-Bot-Api-Secret-Token`
  header with a constant-time comparison, and authorize every callback against
  the owning user.

## Scope

This policy covers the Cinch codebase. Vulnerabilities in third-party
dependencies should be reported upstream; we track them via Dependabot.
