# SPEC — Phase 11: Interview status via Zapier/Make webhook

## Goal

Applications advance automatically when the user gets an inbound email from a
recruiter (invite, offer, rejection). No Gmail OAuth code in Cinch — the user
sets up a free **Zapier or Make** automation ("when Gmail matches X, POST to
Cinch") and Cinch's webhook classifies + updates the status. Fresh state shows
up on the Phase 10 dashboard within one HTMX poll (≤ 15s).

## Non-goals

- No direct Gmail API integration (deliberately deferred — Zapier is enough MVP).
- No spam/quality-signal filtering (Zapier's own filter step does the pre-filtering).
- No user-visible reply generation. Classification only.
- Not multi-tenant — one shared secret per Cinch deploy.

## Behaviour

1. User configures Zapier: **Gmail trigger** (subject/from filter) →
   **Webhooks by Zapier: POST**
   - URL: `https://<your-cinch>/webhook/email`
   - Header: `X-Cinch-Webhook-Secret: <same as INTERVIEW_WEBHOOK_SECRET>`
   - JSON body: `{from_email, from_name, subject, body_text, received_at}`
2. Cinch receives the POST, constant-time-compares the secret header.
3. Loads the single owner user's post-submit applications as classification
   candidates (`APPROVED`, `SUBMITTED`, `NEEDS_HUMAN`, `INTERVIEW_*`, `OFFERED`).
4. Calls the configured LLM (Groq/Anthropic) with a strict system prompt: emit
   ONE of six buckets + a short summary + optional `company_hint`. No prose, JSON only.
5. Matches the LLM's `company_hint` (or a sender-domain fallback for
   `jobs@acme.com` sends) against candidate applications with a
   ``SequenceMatcher`` ratio ≥ 0.6 (plus substring rescue for short brands).
6. If the bucket is `interview_invited` / `interview_scheduled` / `offer` /
   `rejection` **AND** a match was found → advances the application's status,
   records the LLM summary + received_at, DMs the user on Telegram.
7. Informational buckets (`acknowledgement`, `other`) never change state, even
   with a match — auto-replies shouldn't false-advance a real application.
8. Always returns HTTP 200 with a small JSON summary; only auth / config errors
   return 4xx / 5xx (so Zapier doesn't retry noisy no-ops as failures).

## Design

- **Framework-free classifier** — `services/email_classifier.py` takes the
  ``LLMProvider`` + candidate applications and returns a
  ``EmailClassificationResult`` proposal. The webhook route decides whether to
  apply. Anti-fabrication analogue to the tailoring pipeline: the classifier
  can never mutate state itself.
- **LLM safety** — prompt forbids quoting the email body / exposing PII in the
  summary; body is truncated to 4000 chars in the prompt so a marketing blast
  can't blow the token budget; parsing failures degrade to a no-op, never crash.
- **Reused ``LLMProvider``** — same provider factory as tailoring / PDF ingest.
  Free-tier Groq is enough.
- **New enum values, no schema change to `status` column** — it's already
  `String(32)`. Migration 0004 adds two nullable columns (`last_email_at`,
  `last_email_summary`) so the dashboard can show evidence.
- **Sender-domain fallback** — when the LLM returns `null` for `company_hint`,
  the route parses the sender domain (`jobs@acme.com` → `"acme"`), skipping
  webmail domains (`gmail`, `yahoo`, …) where the domain says nothing.

## Files

### New
- `src/cinch/api/email_webhook.py` — `POST /webhook/email` router,
  auth + orchestration + notify.
- `src/cinch/services/email_classifier.py` — `EmailClassifier`,
  `EmailPayload`, `EmailClassificationResult`, matching helpers.
- `migrations/versions/0004_email_tracking.py` — adds `last_email_at` +
  `last_email_summary` to `applications`.
- `tests/test_email_classifier.py` — 13 tests (each bucket, LLM company_hint
  match, sender-domain fallback, malformed LLM → no-op, similarity threshold).
- `tests/test_email_webhook.py` — 8 tests (auth 401 / 503, all classification
  bucket paths, unknown-company no-op, malformed 422, DB update assertion).

### Modified
- `src/cinch/domain/enums.py` — 5 new statuses (`INTERVIEW_INVITED`,
  `INTERVIEW_SCHEDULED`, `OFFERED`, `ACCEPTED`, `REJECTED`).
- `src/cinch/domain/models.py` + `src/cinch/db/models.py` — new nullable columns.
- `src/cinch/db/repositories.py` — `list_candidates_for_email_match`,
  `record_email_update`.
- `src/cinch/services/prompts.py` — `EMAIL_CLASSIFY_SYSTEM_PROMPT` +
  `build_email_classify_user_prompt`.
- `src/cinch/core/config.py` — `interview_webhook_secret` env var.
- `src/cinch/api/app.py` — mounts the email webhook router.
- `src/cinch/bot/{notify,messages}.py` — `send_email_status_update` +
  `format_email_update_message`.
- `src/cinch/services/dashboard_stats.py` — new statuses in `_STATUS_ORDER`.
- Dashboard templates — colors + labels for the new statuses.
- `.env.example` — documents `INTERVIEW_WEBHOOK_SECRET`.

## Safety properties (asserted by tests)

1. Missing / wrong header secret → 401 (no LLM call, no DB touch).
2. `INTERVIEW_WEBHOOK_SECRET` unset → 503 (no LLM call).
3. `acknowledgement` / `other` buckets never advance status, even with a match.
4. Company-hint mismatch (ratio < 0.6) never accidentally attaches to a random application.
5. Malformed LLM output → no-op 200 (never crashes the request; never advances state).
6. Repository record only touches the matched application (foreign key + user_id-scoped candidates).

## Verification

- `ruff`, `ruff format`, `mypy --strict` all clean.
- `uv run pytest` — **204 passed, 88% coverage**.
- Manual smoke (post-deploy): forward a real interview / rejection email through
  Zapier → dashboard status updates within one poll; Telegram DM arrives.

## Out of scope (candidates for the next MVP-plus)

- Per-user secrets for a multi-tenant deploy.
- ACCEPTED-from-OFFERED transition (needs a bot command like `/accept <app>`).
- GHOSTED sweep — flag SUBMITTED apps quiet for > 30 days.
- Native Gmail OAuth (avoids the Zapier hop; ~1 day extra plumbing).
- Sanity-filter to reject job-alert / newsletter / DocuSign emails before the LLM call.
