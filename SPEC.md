# SPEC — Phase 12: Status lifecycle polish (`/accept` + GHOSTED sweep)

## Goal

Close the two obvious gaps left open after Phase 11's inbound-email webhook:

1. **`/accept`** — let the user mark an `OFFERED` application as `ACCEPTED` from
   Telegram. The status exists in the enum but nothing can reach it today.
2. **GHOSTED sweep** — a scheduled job that flags `SUBMITTED` applications that
   have been silent for ≥ N days (default 30) as `GHOSTED`, so a long-dead
   application stops masquerading as "still in play" on the dashboard. If a
   recruiter ever *does* reply, the email webhook un-ghosts it automatically.

## Non-goals

- No auto-accept. Accepting an offer is always an explicit human action.
- No "un-accept" / re-open flow (ACCEPTED is terminal for this phase).
- No configurable per-status ghost thresholds — one global threshold.
- No new dashboard interactions beyond a badge + count for `GHOSTED`.
- No email/calendar side effects on accept (no notifying the employer).

## Behaviour

### `/accept`
1. `/accept` lists the caller's `OFFERED` applications, each as its own message
   with a single **✅ Accept** inline button (mirrors the Approve/Skip card idiom).
   - 0 offers → `"You have no open offers to accept."`
   - ≥ 1 → one card per offer (job title + company + posting link).
2. Tapping **Accept** fires an `accept:<application_id>` callback.
3. The callback is authorized + applied by the service layer (never trusts the
   callback): owner check against the Telegram id, and an idempotent guard that
   only transitions from `OFFERED`. Re-tapping a stale button is a clean no-op.
4. On success: strip the button, answer `"🎉 Offer accepted."`, and the
   dashboard shows `accepted` on its next poll.

### GHOSTED sweep
1. A scheduler job (`run_ghosted_sweep`) runs on an interval, **off by default**,
   gated by `ghosted_sweep_enabled` (consistent with discovery/submission).
2. It selects applications in `SUBMITTED` whose `updated_at` is older than
   `ghosted_after_days` (default 30) and moves them to `GHOSTED`, recording a
   short PII-free note. `updated_at` auto-bumps (`onupdate=func.now()`) on any
   status change or inbound-email update, so it is the correct "quiet since" clock.
3. For each newly-ghosted application, DM the user a terminal nudge
   (`👻 No response — <title> at <company>`).
4. `GHOSTED` is added to the email-match candidate set, so a late recruiter reply
   re-advances it out of `GHOSTED` (interview/offer/rejection) — ghosting is a
   presumption, not a dead end.

## Design

- **Reuse the callback router, don't fork it.** Extend
  `bot/keyboards.py` with an `accept` action + `accept_markup(application_id)`,
  and route `accept:` through the existing `callback_handler`. The authorization
  + idempotency decision lives in the service layer, exactly like Approve/Skip —
  satisfying the "authorize every callback" constraint.
- **Service-owned transitions.** Add methods to `ApprovalService` (or a small
  sibling) so the bot layer stays thin and the transition rules are unit-tested
  without Telegram: `accept(telegram_user_id, application_id) -> AcceptOutcome`
  (`ACCEPTED` / `NOT_OFFERED` / `UNAUTHORIZED` / `NOT_FOUND`).
- **No migration.** `GHOSTED` is a new `ApplicationStatus` value; the `status`
  column is already `String(32)`. The sweep uses existing `updated_at`. Zero
  schema change — same posture Phase 11 took for its new statuses.
- **DI-friendly sweep.** `run_ghosted_sweep(db, settings, bot)` takes its deps as
  arguments (like `run_discovery_cycle`) so it can move to Celery later unchanged.
  A `GhostedSweepService` in `services/` holds the pure logic (query + transition
  + which apps to notify); the scheduler wires the Telegram notifier in.
- **Notifier reuse.** Add `send_ghosted_notice` / `format_ghosted_message` next to
  the existing email-update notifier, so `services/` never imports Telegram.

## Files

### New
- `src/cinch/services/lifecycle.py` — `GhostedSweepService` (pure sweep logic:
  find stale `SUBMITTED`, transition to `GHOSTED`, return the list to notify) and
  the `/accept` transition helper if not folded into `ApprovalService`.
- `tests/test_accept_command.py` — `/accept` list rendering (0 / 1 / many offers),
  the accept callback happy path, unauthorized caller, non-`OFFERED` no-op,
  double-tap idempotency.
- `tests/test_ghosted_sweep.py` — a `SUBMITTED` app older than the threshold is
  ghosted; a fresh one is not; a non-`SUBMITTED` old app is untouched; the
  service returns exactly the newly-ghosted apps to notify; disabled flag → no-op.

### Modified
- `src/cinch/domain/enums.py` — add `GHOSTED = "ghosted"`.
- `src/cinch/db/repositories.py` —
  `list_stale_submitted(before: datetime) -> list[Application]`,
  `mark_ghosted(application_id, *, note) -> Application | None`,
  `accept_offer(application_id) -> Application | None` (guards on `OFFERED`),
  and add `GHOSTED` to `list_candidates_for_email_match`'s allowed set.
- `src/cinch/services/workflow.py` — `accept()` + `AcceptOutcome` enum
  (owner auth + idempotent `OFFERED`-only transition).
- `src/cinch/bot/keyboards.py` — `accept` action, `accept_markup`, parse support.
- `src/cinch/bot/handlers.py` — `accept_command`; extend `callback_handler` to
  route the `accept` action.
- `src/cinch/bot/application.py` — register `CommandHandler("accept", …)`.
- `src/cinch/bot/messages.py` — `format_offer_card`, `format_ghosted_message`,
  accept ack text; add a `GHOSTED` headline entry.
- `src/cinch/bot/notify.py` — `send_ghosted_notice` + `send_offer_cards` (or reuse
  `send_message`), keeping Telegram out of `services/`.
- `src/cinch/api/scheduler.py` — `run_ghosted_sweep` + `start_ghosted_scheduler`,
  started from the lifespan only when `ghosted_sweep_enabled`.
- `src/cinch/api/app.py` — start the ghosted scheduler in the lifespan (guarded).
- `src/cinch/core/config.py` — `ghosted_sweep_enabled: bool = False`,
  `ghosted_after_days: int = 30`, `ghosted_sweep_interval_minutes: int = 1440`.
- `src/cinch/services/dashboard_stats.py` — add `GHOSTED` to `_STATUS_ORDER`.
- `src/cinch/api/dashboard/templates/_applications.html` — `ghosted` badge color.
- `.env.example` — document the three new `GHOSTED_*` settings.

## Safety properties (asserted by tests)

1. `/accept` callback from a non-owner Telegram id never mutates state
   (`UNAUTHORIZED`), and does not strip the button.
2. Accept only transitions from `OFFERED`; any other current status is a no-op
   (`NOT_OFFERED`) — a stale/duplicate tap can't corrupt a resolved application.
3. The sweep only touches `SUBMITTED` rows older than the threshold — never
   `APPROVED`, `INTERVIEW_*`, `OFFERED`, or already-terminal rows.
4. Sweep disabled (`ghosted_sweep_enabled=False`) → the scheduler is never
   started and `run_ghosted_sweep` is a no-op returning an empty summary.
5. A ghosted application remains an email-match candidate, so a later recruiter
   email re-advances it (proven by an email-webhook test over a `GHOSTED` row).
6. No Alembic migration is introduced (enum-only change on a `String` column);
   `alembic heads` stays at `0004`.

## Verification

- `ruff`, `ruff format --check`, `mypy --strict` all clean.
- `uv run pytest` — **219 passed, 87% coverage**.
- `alembic heads` stays at `0004` (no migration introduced).
- Manual smoke (post-deploy):
  - Drive an application to `OFFERED` (via the email webhook), run `/accept`,
    tap Accept → dashboard shows `accepted`.
  - Temporarily set `GHOSTED_AFTER_DAYS=0` + `GHOSTED_SWEEP_ENABLED=true` against
    a throwaway `SUBMITTED` app → it flips to `GHOSTED` and a DM arrives; then a
    forwarded interview email un-ghosts it.

## Out of scope (candidates for the next MVP-plus)

- Per-user secrets for a multi-tenant deploy.
- Native Gmail OAuth (drop the Zapier hop).
- Email sanity-filter (reject newsletters/job-alerts before the LLM call).
- A `/status <app>` command to show one application's full history.
- Configurable ghost thresholds per source or per status.
