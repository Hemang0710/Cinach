# SPEC — Phase 10: Live dashboard (MVP)

## Goal

One live URL (`https://<host>/dashboard`) that shows the user their applications,
statuses, and per-status counts in real-time — the single view the user asked for
in their original ("one web page which is live") request. Auth is a signed
magic-link DM'd by the Telegram bot's `/dashboard` command.

## Non-goals for this MVP

- No filters / search / date-range pickers (deferred).
- No timeline / activity feed view (deferred).
- No per-source health panel (deferred).
- No status-editing actions from the page — bot remains the source of writes.
- No multi-user tenanting UI — the dashboard scopes strictly to the caller's user_id.

## Behaviour

1. User sends `/dashboard` to the bot.
2. Bot verifies the caller is a registered user, generates a signed magic-link
   token (10-min TTL), DMs the URL: `{TELEGRAM_WEBHOOK_URL}/dashboard/login?token=<t>`.
3. User taps the link.
4. `GET /dashboard/login?token=<t>` verifies signature + expiry, sets an HttpOnly
   session cookie (7-day TTL, `Secure` in production, `SameSite=lax`), 303-redirects
   to `/dashboard`.
5. `GET /dashboard` renders the main page — dark theme, Tailwind CDN, HTMX polling.
6. HTMX fragments (`/dashboard/fragments/summary`, `/dashboard/fragments/applications`)
   refresh every 15s so the page reflects new discoveries / approvals without a reload.
7. `GET /dashboard/logout` clears the session cookie.

## Design

- **No new deps beyond `jinja2`.** Tailwind + HTMX loaded via `<script>` tags —
  no bundler, no build step, works on Render's free tier as-is.
- **Auth uses stdlib `hmac`+`hashlib`+`secrets`** (no `itsdangerous`, no JWT lib).
  The signing key is **derived from `TELEGRAM_WEBHOOK_SECRET`** via SHA-256 with a
  purpose string, so no new env var. Constant-time comparison on the HMAC check.
- **Router mounts unconditionally** (no gating on `telegram_bot_token`). `/login`
  itself checks for the secret and returns a 503 error page if unset, keeping the
  routes deterministic in tests.
- **Data assembly lives in a framework-free service**
  (`services/dashboard_stats.py`) so the router stays thin and the query is
  unit-testable without a live web request.

## Files

### New
- `src/cinch/api/dashboard/__init__.py`
- `src/cinch/api/dashboard/auth.py` — token signing / verification, exception type.
- `src/cinch/api/dashboard/router.py` — 5 routes + `issue_magic_link` helper.
- `src/cinch/api/dashboard/templates/` — `base.html`, `dashboard.html`,
  `_summary.html`, `_applications.html`, `login_error.html`.
- `src/cinch/services/dashboard_stats.py` — `compute_dashboard_stats(session, user_id)`.
- `tests/test_dashboard_auth.py` — 6 tests (roundtrip, expiry, tampering, wrong
  secret, malformed).
- `tests/test_dashboard_stats.py` — 4 tests (empty, counts+rows, user isolation,
  row limit).
- `tests/test_dashboard_routes.py` — 9 tests (login flow, cookie gating, fragment
  endpoints, logout, magic-link helper).

### Modified
- `src/cinch/api/app.py` — sets `app.state.settings`; mounts the dashboard router.
- `src/cinch/bot/handlers.py` — new `dashboard_command`.
- `src/cinch/bot/application.py` — registers `/dashboard` handler.
- `pyproject.toml` — adds `jinja2>=3.1` + wheel force-include for templates.
- README updated with a "Dashboard" section.

## Safety properties (asserted by tests)

1. Token signed for user A cannot be verified as user B (payload tamper → signature mismatch).
2. Expired tokens rejected with a clear "expired" message.
3. Wrong signing secret rejected.
4. `/dashboard` without a session cookie returns 401 (no PII leak in the error page).
5. Dashboard queries strictly filter by `user_id` — no cross-tenant leaks
   (verified with two users in `test_stats_isolates_users`).
6. `/dashboard` command fails gracefully with a "not configured" message if
   `TELEGRAM_WEBHOOK_SECRET` or `TELEGRAM_WEBHOOK_URL` is unset — never emits a
   half-formed link.

## Verification

- `ruff` / `ruff format --check` / `mypy --strict` all clean.
- `uv run pytest` — **182 passed, 88% coverage** (up from 160).
- Manual smoke (post-deploy): `/dashboard` in bot → tap link → dashboard renders,
  counts + rows visible, HTMX polling refreshes without a reload.

## Out of scope (planned for a follow-up MVP-plus PR)

- Timeline view (application state changes over time).
- Per-source health panel (last-fetched timestamp + errors per JobSource).
- Filters (status, source, date range).
- Row-level actions (mark rejected / offered) — Phase 11 territory.
- CSV export.
