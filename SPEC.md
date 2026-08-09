# SPEC — Phase 13: Email sanity-filter (pre-LLM noise gate)

## Goal

Stop obvious inbox noise — job-alert digests and marketing newsletters — from
reaching the Phase 11 LLM classifier. A cheap, deterministic pre-check runs
*before* `EmailClassifier` calls the LLM: if the email is clearly noise, the
webhook returns a no-op 200 without spending an LLM call, and there is zero
chance it false-advances an application.

## Why

Every inbound email currently triggers an LLM call (cost + latency), and a noisy
inbox (LinkedIn/Indeed job alerts, newsletters) is the common case. The filter
cuts that spend and removes a whole class of false-positive risk before it can
happen.

## Non-goals

- **Not** a replacement for the LLM classifier — it only removes emails that can
  *never* legitimately advance an application. Anything ambiguous falls through
  to the LLM unchanged (current behaviour).
- **No** DocuSign / e-signature filtering. Offer letters routinely travel via
  DocuSign, so dropping those risks missing a real offer — deliberately excluded
  (a considered deviation from the Phase-11 out-of-scope note, which lumped
  DocuSign in; see "Design decisions").
- No header-based filtering (`List-Unsubscribe`, SPF/DKIM) — Zapier only forwards
  `from/subject/body`, not raw headers.
- No per-user allow/deny lists, no learning/scoring model.

## Behaviour

1. `EmailClassifier.classify` runs the sanity check first (when
   `email_sanity_filter_enabled`, default **on**).
2. If the email matches a noise rule, classify returns a no-op result
   (`classification=other`, `new_status=None`, `matched_application=None`) with
   `reason="filtered: <rule>"` — **no LLM call is made**.
3. The webhook already treats that as `no_status_change` and returns 200, so
   Zapier sees `{"action":"no_status_change","classification":"other",
   "reason":"filtered: job_alert"}` and does not retry.
4. If no rule matches, behaviour is exactly as today — the LLM classifies.

## Noise rules (high-precision only)

The filter is conservative by design: a false negative (noise slips through) just
means one wasted LLM call; a false positive (a real interview/offer dropped) is a
silent miss. So rules fire only on strong signals for categories that never
advance an application:

- **`job_alert`** — subject or body matches job-board digest patterns, e.g.
  `job alert`, `jobs for you`, `new jobs matching`, `recommended jobs`,
  `N new jobs`, `we found … jobs`, `job recommendations`, `your job alert`.
- **`newsletter`** — bulk-marketing footer signature: an `unsubscribe` token
  **combined with** one of `manage (your )?preferences` / `view (this )?in (your )?browser`
  / `you (are )?receiv(ed|ing) this (email )?because`. (Either alone is too weak
  — legitimate mail sometimes carries a lone "unsubscribe".)
- **`bulk_sender`** — sender local-part is an unambiguous automated-broadcast
  mailbox **and** the subject is not interview/offer/rejection-ish:
  `newsletter@`, `digest@`, `marketing@`, `promotions@`, `mailer@`, `bounce(s)@`.
  (Note: bare `no-reply@` is **not** on this list — real Lever/Greenhouse
  interview invites use it. The subject guard also protects this rule.)

All matching is on lowercased text; a small module-level list of compiled regexes
keeps it readable and fast.

## Design

- **Pure, framework-free module** — `services/email_filter.py` exposes
  `is_noise_email(payload: EmailPayload) -> str | None` (the rule name that
  fired, or `None`). No I/O, trivially unit-testable, mirrors the
  `email_classifier` style.
- **Single hook** — `EmailClassifier.classify` calls it once at the top, gated on
  `settings.email_sanity_filter_enabled`, and returns the existing `_drop(...)`
  no-op on a hit. No new result shape, no webhook change.
- **Subject guard shared** — a `_looks_advancing(subject)` helper (interview /
  offer / reject / schedule keywords) protects the `bulk_sender` rule so an
  offer from `mailer@` still reaches the LLM.
- **Config toggle** — `email_sanity_filter_enabled: bool = True`. On by default
  because the rules are safe; the flag exists so it can be disabled instantly if
  a real email is ever mis-dropped.

## Files

### New
- `src/cinch/services/email_filter.py` — `is_noise_email`, the rule regexes,
  `_looks_advancing`.
- `tests/test_email_filter.py` — each rule fires on representative noise; real
  interview/offer/rejection/acknowledgement emails pass through; the subject
  guard rescues an offer from a bulk mailbox; lone "unsubscribe" is not filtered.

### Modified
- `src/cinch/services/email_classifier.py` — call the filter first in
  `classify`; short-circuit to `_drop(received_at, f"filtered: {rule}")`.
- `src/cinch/core/config.py` — `email_sanity_filter_enabled: bool = True`.
- `.env.example` — document the toggle in the email-webhook section.
- `tests/test_email_classifier.py` — assert a filtered email makes **no** LLM
  call (fake provider records zero calls) and returns the filtered no-op; assert
  a real interview email still calls the LLM and advances (guards against the
  filter over-reaching).

## Safety properties (asserted by tests)

1. A job-alert / newsletter email is dropped with `reason="filtered: …"` and the
   fake LLM provider records **zero** calls.
2. A genuine interview / offer / rejection email is **not** filtered — the LLM is
   called and the application advances exactly as in Phase 11.
3. An offer sent from a bulk mailbox (`mailer@`) whose subject says "offer" is
   **not** filtered (subject guard).
4. A lone `unsubscribe` in an otherwise normal email does **not** trigger the
   newsletter rule.
5. `email_sanity_filter_enabled=False` disables the gate entirely — every email
   reaches the LLM (back to Phase 11 behaviour).

## Verification

- `ruff`, `ruff format --check`, `mypy --strict` all clean.
- `uv run pytest` — all green, coverage ≥ 80%.
- No migration (no schema change).
- Manual smoke: forward a LinkedIn "jobs for you" digest through Zapier → webhook
  returns `no_status_change` with `reason="filtered: job_alert"` and the deploy's
  LLM usage does not tick up.

## Out of scope (candidates for the next MVP-plus)

- Native Gmail OAuth (drop the Zapier hop).
- Per-user secrets for a multi-tenant deploy.
- `/status <app>` history command / dashboard drill-down.
- Header-based filtering once a source forwards raw headers.
