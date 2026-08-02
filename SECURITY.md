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
- **Redact PII from logs.** The structlog pipeline masks sensitive keys
  (tokens, keys, `content`, `resume`, …) as defence-in-depth; only non-sensitive
  identifiers such as `telegram_user_id` are logged.
- **Encrypt PII at rest.** Resume content is encrypted with Fernet (AES-128-CBC +
  HMAC) via an application-level column type when `ENCRYPTION_KEY` is set. Without
  a key, content is stored plaintext and a startup warning is logged — **set
  `ENCRYPTION_KEY` in any deployment handling real resumes.**
- **Verify the Telegram webhook** using the `X-Telegram-Bot-Api-Secret-Token`
  header with a constant-time comparison, and authorize every callback against
  the owning user.

### Encryption key management

- Generate a key with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  and supply it as `ENCRYPTION_KEY` via your secret store (never commit it).
- **Rotation caveat:** rows encrypted with an old key cannot be read after the key
  changes. Key rotation requires a re-encryption migration (decrypt with the old
  key, re-encrypt with the new) — not yet automated.
- Sentry runs with `send_default_pii=False` and scrubs request bodies, so PII and
  secrets are not shipped to the error backend.

## Assisted submission (Phase 6)

Optional Playwright-based submission is **off by default** (`SUBMISSION_ENABLED=false`)
and is not installed unless the `submit` extra is selected. When operators enable it:

- It only ever submits applications the user has **already Approved** on Telegram — there
  is no unattended bulk auto-apply.
- It **never bypasses logins or CAPTCHAs**; those are handed back to the user with the
  apply link.
- The submitted document is the user's **real master resume** (no LLM at submit time, so
  nothing is fabricated), and the browser adapter logs no URLs or resume content.
- **Terms-of-Service risk is the operator's responsibility.** Auto-submitting to job
  sites may violate their ToS; enabling submission is a deliberate, at-your-own-risk choice.

## Scope

This policy covers the Cinch codebase. Vulnerabilities in third-party
dependencies should be reported upstream; we track them via Dependabot.
