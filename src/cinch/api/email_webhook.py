"""Inbound email webhook (Phase 11) — Zapier / Make → Cinch.

Users configure a Zapier automation:
    Gmail trigger (subject/from filter) → "Webhooks by Zapier: POST" →
    URL: https://<your-cinch>/webhook/email
    Headers: X-Cinch-Webhook-Secret: <same value as INTERVIEW_WEBHOOK_SECRET>
    Body (JSON):
        {"from_email": "{{From Email}}",
         "from_name":  "{{From Name}}",
         "subject":    "{{Subject}}",
         "body_text":  "{{Body Plain}}",
         "received_at": "{{Received}}"}

The route:
  1. Verifies the ``X-Cinch-Webhook-Secret`` header (constant-time compare).
  2. Loads the user's post-submit applications as classification candidates.
  3. Delegates to :class:`EmailClassifier`, which does the LLM call + matching.
  4. If the classification maps to a real status change AND we matched an
     application, records the update and DMs the user on Telegram.
  5. Always returns 200 with a small JSON summary — Zapier retries 5xx, but
     "informational email, no state change" is a *successful* outcome, not an
     error, so we don't provoke retries on quiet emails.

Auth + routing (Phase 14): the ``X-Cinch-Webhook-Secret`` header carries a
**per-user token** (issued by the bot's ``/emailhook`` command). The route
resolves token → user and matches only within that user's applications, so a
multi-tenant deploy routes each user's mail to their own pipeline. A missing or
unknown token is a clean 401 (4xx ⇒ Zapier does not retry).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from cinch.core.config import Settings
from cinch.core.logging import get_logger
from cinch.db.models import JobORM
from cinch.db.repositories import ApplicationRepository, JobRepository, UserRepository
from cinch.db.session import Database
from cinch.providers.llm import get_llm_provider
from cinch.services.email_classifier import (
    EmailClassificationResult,
    EmailClassifier,
    EmailPayload,
)

logger = get_logger(__name__)

WEBHOOK_SECRET_HEADER = "X-Cinch-Webhook-Secret"  # noqa: S105 - header NAME, not a secret


def build_email_webhook_router() -> APIRouter:
    """Construct the ``POST /webhook/email`` router. Mounted by the app factory."""
    router = APIRouter(prefix="/webhook", tags=["webhook"])

    @router.post("/email")
    async def receive_email(
        request: Request,
        payload: EmailPayload,
        x_cinch_webhook_secret: str | None = Header(default=None),
    ) -> JSONResponse:
        """Classify one inbound email and (if applicable) advance an application."""
        settings: Settings = request.app.state.settings

        db: Database | None = request.app.state.db
        if db is None:
            raise HTTPException(status_code=503, detail="database not configured")

        if not x_cinch_webhook_secret:
            raise HTTPException(status_code=401, detail="missing webhook token")

        # Bot is optional at this layer — an email may arrive before the bot is
        # wired up (tests). If present, we DM the user; if absent, we still update
        # the DB and return the outcome for Zapier's records.
        bot_app: Any | None = request.app.state.bot_app
        bot = bot_app.bot if bot_app is not None else None

        # Resolve the per-user token, then assemble what the classifier needs.
        async with db.session() as session:
            owner = await UserRepository(session).get_by_email_webhook_token(x_cinch_webhook_secret)
            if owner is None:
                raise HTTPException(status_code=401, detail="invalid webhook token")
            candidates = await ApplicationRepository(session).list_candidates_for_email_match(
                owner.id
            )
            jobs_by_id = await _jobs_by_id_for_apps(session, [a.job_id for a in candidates])

        provider = get_llm_provider(settings)
        classifier = EmailClassifier(provider, settings)
        result = await classifier.classify(payload, candidates=candidates, jobs_by_id=jobs_by_id)

        if result.matched_application is None or result.new_status is None:
            logger.info(
                "email_webhook_no_action",
                classification=result.classification.value,
                reason=result.reason,
            )
            return _reply(_no_action_body(result))

        # Record + notify. A DM failure should not roll back the DB update.
        async with db.session() as session:
            updated = await ApplicationRepository(session).record_email_update(
                result.matched_application.id,
                status=result.new_status,
                summary=result.summary,
                received_at=result.received_at,
            )
        if updated is not None and bot is not None:
            try:
                from cinch.bot.notify import send_email_status_update

                async with db.session() as session:
                    job = await JobRepository(session).get(updated.job_id)
                    notify_user = await UserRepository(session).get(updated.user_id)
                if job is not None and notify_user is not None:
                    await send_email_status_update(
                        bot,
                        chat_id=notify_user.telegram_chat_id,
                        job=job,
                        status=updated.status,
                        summary=updated.last_email_summary or "",
                    )
            except Exception:
                logger.exception("email_webhook_notify_failed")

        logger.info(
            "email_webhook_status_update",
            classification=result.classification.value,
            new_status=result.new_status.value,
            application_id=str(result.matched_application.id),
        )
        return _reply(_updated_body(result))

    return router


async def _jobs_by_id_for_apps(session: Any, job_ids: list[UUID]) -> dict[str, str]:
    """Batch-load ``job_id`` → ``company`` for the candidate applications.

    ``JobORM.id`` is a UUID column, so we pass real ``UUID`` objects (SQLAlchemy's
    Uuid type calls ``.hex`` on the value, which strings don't support).
    """
    if not job_ids:
        return {}
    result = await session.scalars(select(JobORM).where(JobORM.id.in_(job_ids)))
    return {str(job.id): job.company for job in result.all()}


def _reply(body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=200)


def _no_action_body(result: EmailClassificationResult) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "no_status_change",
        "classification": result.classification.value,
        "reason": result.reason,
    }


def _updated_body(result: EmailClassificationResult) -> dict[str, Any]:
    assert result.matched_application is not None and result.new_status is not None
    return {
        "ok": True,
        "action": "status_updated",
        "classification": result.classification.value,
        "application_id": str(result.matched_application.id),
        "new_status": result.new_status.value,
    }
