# Deploying Cinch to Render

This guide takes Cinch from repo to a live Telegram bot on [Render](https://render.com).
Render gives you a public HTTPS URL (which Telegram webhooks require) and managed
Postgres, so no reverse proxy or certificate wrangling is needed.

There are two paths:

- **A. Blueprint (recommended)** — one-click from [`render.yaml`](render.yaml).
- **B. Manual** — create the database and web service by hand in the dashboard.

Both end at the same place: [Register the Telegram webhook](#4-register-the-telegram-webhook).

---

## 0. Prerequisites — gather your credentials

| Secret | Where to get it |
| ------ | --------------- |
| `TELEGRAM_BOT_TOKEN` | Message [@BotFather](https://t.me/BotFather) → `/newbot`. |
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/). (Or use OpenAI/Google — set `LLM_PROVIDER` + `LLM_MODEL`.) |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Register at [developer.adzuna.com](https://developer.adzuna.com/). Needed only if you enable job discovery. |
| `ENCRYPTION_KEY` | Generate a Fernet key (below) — encrypts resume PII at rest. |

Generate the encryption key locally:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

You do **not** need to pick `TELEGRAM_WEBHOOK_SECRET` yourself — the Blueprint generates
one. (Manual path: use any long random string, e.g. `openssl rand -hex 32`.)

---

## A. Deploy with the Blueprint (recommended)

1. Push this repo to your own GitHub account.
2. In Render: **New → Blueprint**, select the repo, and **Apply**. This creates the
   Postgres database and the `cinch` web service from [`render.yaml`](render.yaml), and
   wires `DATABASE_URL` automatically.
3. Open the `cinch` service → **Environment** and fill in the secrets marked
   `sync: false`: `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `ENCRYPTION_KEY`, and
   (optionally) the Adzuna keys. Leave `TELEGRAM_WEBHOOK_URL` for step 4.
4. Continue to [Register the Telegram webhook](#4-register-the-telegram-webhook).

> The Blueprint's start command is `alembic upgrade head && python -m cinch.api`, so the
> database schema is migrated on every deploy — no separate migration step needed.

---

## B. Deploy manually

### 1. Create the Postgres database

**New → Postgres.** Name it (e.g. `cinch-db`), pick a region and plan, create it. When it's
ready, copy the **Internal Database URL** (starts with `postgresql://…`). Cinch rewrites
that scheme to the async driver it needs automatically, so you can paste it as-is.

### 2. Create the web service

**New → Web Service**, connect this repo, and set:

- **Runtime:** Docker (the repo's `Dockerfile` is used automatically).
- **Health Check Path:** `/healthz`
- **Docker Command** (override): `sh -c "alembic upgrade head && python -m cinch.api"`
  — this migrates the DB, then starts the app, on every boot.

Render injects `PORT`; the app binds it automatically (no action needed).

### 3. Set environment variables

On the web service's **Environment** tab:

| Variable | Value |
| -------- | ----- |
| `ENVIRONMENT` | `production` |
| `DATABASE_URL` | the **Internal Database URL** from step 1 |
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `TELEGRAM_WEBHOOK_SECRET` | a long random string |
| `ANTHROPIC_API_KEY` | your key |
| `ENCRYPTION_KEY` | the Fernet key from step 0 |
| `TELEGRAM_WEBHOOK_URL` | *(set in step 4)* |

---

## 4. Register the Telegram webhook

Your service's public URL is `https://<your-service-name>.onrender.com`.

Set **`TELEGRAM_WEBHOOK_URL`** to exactly that origin (no trailing path) and save. Render
redeploys; on startup the app registers the webhook with Telegram at
`…/telegram/webhook`, verified by `TELEGRAM_WEBHOOK_SECRET`.

Confirm it's live:

```bash
curl https://<your-service-name>.onrender.com/readyz
```

`/readyz` returns `200` once the database is reachable (`503` until then); `/healthz` is the
liveness probe Render uses.

Then open your bot in Telegram, send `/start`, and upload your master resume as a `.json`
file. You're live. 🎉

---

## 5. Turn on job discovery (optional)

To have Cinch discover jobs and message you with **Approve / Skip** cards, set:

- `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` (and optionally `ADZUNA_COUNTRY`, default `us`)
- `DISCOVERY_ENABLED=true`

> **Use a non-free plan for schedulers.** Discovery runs on an in-process scheduler.
> Render **free** web services sleep when idle, which pauses the scheduler. Use **Starter**
> or higher so discovery cycles actually run. Run a **single instance** — multiple
> instances would each run their own cycle.

---

## 6. Turn on assisted submission (optional, experimental)

Assisted submission (Phase 6) auto-submits applications you've **already Approved** and
hands anything unsafe (login/CAPTCHA/unknown form) back to you. It is **off by default**.

> ⚠️ **Terms-of-Service risk.** Auto-submitting to job sites may violate their ToS. Enabling
> this is a deliberate, at-your-own-risk choice. See [SECURITY.md](SECURITY.md) and
> [README.md](README.md#assisted-submission-experimental-opt-in).

It needs a real Chromium in the image, which the default `Dockerfile` does **not** install.
To enable it, add a browser layer to the runtime stage of the `Dockerfile`:

```dockerfile
# In the runtime stage, install the submit extra + Chromium (as root, before `USER app`):
RUN uv pip install --python /app/.venv playwright \
 && /app/.venv/bin/playwright install --with-deps chromium
```

Then set `SUBMISSION_ENABLED=true` (again, **Starter** plan or higher so the 5-minute
submission scheduler keeps running). Make sure each user's master resume includes `name`,
`email`, and `phone`, or applications are handed back rather than submitted.

---

## Troubleshooting

| Symptom | Likely cause / fix |
| ------- | ------------------ |
| Bot doesn't respond | `TELEGRAM_WEBHOOK_URL` not set to the exact Render origin, or a wrong `TELEGRAM_BOT_TOKEN`. Check the service **Logs** for `set_webhook`. |
| `/readyz` returns 503 | Database unreachable — verify `DATABASE_URL` (use the **Internal** URL) and that the DB is running. |
| First request is slow | On the **free** plan the service cold-starts from sleep; Telegram retries. Upgrade to avoid sleep. |
| `relation "users" does not exist` | Migrations didn't run — confirm the Docker Command includes `alembic upgrade head`. |
| Discovery/submission never fire | Free-plan sleep pauses the scheduler — use Starter+; and keep a single instance. |
| Submission errors every few minutes | `SUBMISSION_ENABLED=true` without Chromium in the image — see step 6, or set it back to `false`. |

For local development and the full config reference, see [README.md](README.md) and
[.env.example](.env.example).
