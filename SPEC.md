# SPEC — Phase 14: Multi-user support (allowlist + per-user email routing)

## Goal

Turn Cinch from a single-owner deploy into a genuine (small-scale) multi-tenant
one, closing the two places that still assume one user:

1. **Access control** — `/start` currently registers *anyone* who messages the
   bot, so a public bot lets the whole internet spend the operator's LLM + job-API
   quota. Add an **allowlist** (`ALLOWED_TELEGRAM_IDS`) gating registration.
2. **Per-user email routing** — the inbound-email webhook picks the *oldest*
   user (`_pick_user`). Replace that with a **per-user webhook token**: each user
   issues their own token via `/emailhook`, their Zapier sends it, and Cinch
   resolves token → user and matches only within that user's applications.

Everything else is already tenant-safe: discovery iterates all users and notifies
each user's own chat; the dashboard magic-link is scoped to `user_id`; `/accept`,
the GHOSTED sweep, and all repositories key off `user_id`.

## Non-goals

- No self-service admin UI for managing the allowlist (it's config/env).
- No per-user LLM/job-source **quotas or billing** — allowlist is the only gate.
- No org/team hierarchy or roles; every allowed user is an equal tenant.
- No migration of a running deploy's existing Zapier automatically — the operator
  re-runs `/emailhook` once and pastes the new token into their webhook header
  (documented in the PR summary).
- No change to the dashboard, discovery, or submission flows (already per-user).

## Behaviour

### Allowlist
1. New setting `allowed_telegram_ids: str = ""` — comma-separated Telegram user
   ids. **Empty ⇒ open** (backward-compatible; a fresh deploy still works). When
   set, only listed ids may register.
2. `Settings.is_telegram_id_allowed(uid)` → `True` when the list is empty, else
   `uid in` the parsed set. A malformed entry is ignored (logged once at parse).
3. Registration entry points (`/start`, resume upload `document_handler`) call the
   gate first; a disallowed user gets a polite `"⛔ This bot is private…"` reply
   and **no** `UserORM` row is created. Callbacks/commands for *existing* users are
   unaffected (they already have a row).

### Per-user email webhook token
1. New nullable, unique column `users.email_webhook_token` (String(64)).
2. `/emailhook` (allowlisted, existing users only) generates the token on first
   use (or rotates on repeat with a confirmation note) and DMs the user the exact
   Zapier setup: the webhook URL and the `X-Cinch-Webhook-Secret: <token>` header.
   Token = `secrets.token_urlsafe(32)`; rotating invalidates the old one.
3. `POST /webhook/email` auth changes: the `X-Cinch-Webhook-Secret` header now
   carries the **per-user token**. The route looks it up (`get_by_email_webhook_token`):
   - missing/empty header → **401**
   - token resolves to no user → **401** (no information leak)
   - resolves → that user becomes the match scope (replaces `_pick_user`).
4. The global `interview_webhook_secret` is **retired** from routing. The route is
   "configured" as long as the DB is available; a request with an unknown token is
   a clean 401, not a 503.

## Design

- **Config** — `allowed_telegram_ids` + a cached `allowed_telegram_id_set`
  property and `is_telegram_id_allowed()`. Parsing is tolerant (strip, skip blanks,
  ignore non-ints with a warning).
- **DB / migration** — add `email_webhook_token` to `UserORM` (unique, indexed,
  nullable) and mirror it on the `User` domain model. New Alembic migration
  `0005_email_webhook_token` (batch `add_column` + unique index), mirroring 0004.
  The `test_migration_matches_models_no_structural_drift` guard forces this.
- **Repository** — `UserRepository.get_by_email_webhook_token(token)` and
  `rotate_email_webhook_token(user_id) -> str` (generates, persists, returns the
  raw token). High-entropy token ⇒ a plain indexed-equality lookup is acceptable
  auth (like an API key); no constant-time compare needed for a 43-char secret.
- **Bot** — a thin `_authorized(update, settings)` helper used by `/start` and
  `document_handler`; a new `emailhook_command` in `handlers.py`, registered in
  `bot/application.py`, with copy in `bot/messages.py`. The token is only ever sent
  in a Telegram DM (private chat), never logged.
- **Webhook** — replace `_check_secret` + `_pick_user` with token resolution.
  Keep the "no matched application ⇒ 200 no-op" contract so quiet emails don't
  provoke Zapier retries; only *auth* failures are 401.

## Files

- `src/cinch/core/config.py` — `allowed_telegram_ids` + allowlist helpers.
- `src/cinch/domain/models.py` — `User.email_webhook_token`.
- `src/cinch/db/models.py` — `UserORM.email_webhook_token` (unique/index/nullable).
- `migrations/versions/0005_email_webhook_token.py` — new migration.
- `src/cinch/db/repositories.py` — token lookup + rotate.
- `src/cinch/bot/handlers.py` — allowlist gate + `/emailhook`.
- `src/cinch/bot/application.py` — register `/emailhook`.
- `src/cinch/bot/messages.py` — `/emailhook` + not-authorized copy.
- `src/cinch/api/email_webhook.py` — token-based routing (drop `_pick_user`).
- `.env.example` — `ALLOWED_TELEGRAM_IDS`, revised email-webhook notes.
- Tests: `tests/test_email_webhook.py` (rework auth), `tests/test_bot_handlers.py`
  (allowlist + `/emailhook`), plus repository coverage.

## End-to-end verification

1. `uv run ruff check . && uv run mypy && uv run pytest` all green; migration
   drift test passes with `0005` present.
2. Manual: set `ALLOWED_TELEGRAM_IDS` to your id; a second Telegram account gets
   `⛔ private`. `/emailhook` DMs a token; POST `/webhook/email` with that token in
   `X-Cinch-Webhook-Secret` routes to *your* applications; a random token → 401.
