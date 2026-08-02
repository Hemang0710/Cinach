"""Telegram handlers — thin translation between Telegram updates and services.

Handlers pull the injected :class:`~cinch.db.session.Database` and
:class:`~cinch.core.config.Settings` out of ``bot_data`` (dependency injection, no
globals), open a session, and delegate every decision to the service layer. No
business logic or authorization rule lives here — that is in
:class:`~cinch.services.workflow.ApprovalService`.

User content (resume JSON, message text) is never logged.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from pydantic import ValidationError
from telegram import Update
from telegram.ext import ContextTypes

from cinch.bot.keyboards import parse_callback
from cinch.bot.messages import decision_ack
from cinch.bot.notify import send_application
from cinch.core.logging import get_logger
from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    ResumeRepository,
    UserRepository,
)
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.domain.models import TailoredBullet, TailoringResult
from cinch.domain.resume import MasterResume
from cinch.services.workflow import ApprovalService, DecisionOutcome

logger = get_logger(__name__)

_MAX_RESUME_BYTES = 1_000_000  # reject oversized uploads before downloading fully

_WELCOME = (
    "👋 Welcome to Cinch — your human-in-the-loop job application assistant.\n\n"
    "I tailor your master resume to each job and send it here with Approve / Skip "
    "buttons. Nothing is ever submitted without your approval.\n\n"
    "To get started, send me your master resume as a <b>.json</b> file "
    "(see /setresume)."
)

_SETRESUME_HELP = (
    "Send your master resume as a <b>.json</b> file matching Cinch's schema "
    "(summary, skills, experiences[], education[]). I validate it before saving and "
    "only ever rephrase what's in it — never inventing new experience."
)


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return cast(Database, context.bot_data["db"])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — register the user (idempotent) and explain the flow."""
    user, chat = update.effective_user, update.effective_chat
    if user is None or chat is None or update.message is None:
        return
    async with _db(context).session() as session:
        await UserRepository(session).get_or_create(user.id, chat.id)
    await update.message.reply_html(_WELCOME)


async def setresume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setresume — explain how to submit the master resume."""
    if update.message is not None:
        await update.message.reply_html(_SETRESUME_HELP)


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept a ``.json`` master-resume upload; validate and store it."""
    message, user, chat = update.message, update.effective_user, update.effective_chat
    if message is None or message.document is None or user is None or chat is None:
        return
    document = message.document
    if not (document.file_name or "").lower().endswith(".json"):
        await message.reply_text("Please upload your master resume as a .json file.")
        return
    if document.file_size is not None and document.file_size > _MAX_RESUME_BYTES:
        await message.reply_text("That file is too large (max 1 MB).")
        return

    tg_file = await document.get_file()
    raw = bytes(await tg_file.download_as_bytearray())
    try:
        master = MasterResume.model_validate_json(raw)
    except ValidationError:
        logger.info("resume_upload_rejected", telegram_user_id=user.id)  # no content logged
        await message.reply_text(
            "That resume JSON didn't match the expected schema. Please fix it and resend."
        )
        return

    async with _db(context).session() as session:
        owner = await UserRepository(session).get_or_create(user.id, chat.id)
        await ResumeRepository(session).set_master(owner.id, master.model_dump())
    logger.info("resume_saved", telegram_user_id=user.id)
    await message.reply_text("✅ Master resume saved.")


async def demo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/demo (non-production) — send a sample application to exercise Approve/Skip."""
    user, chat = update.effective_user, update.effective_chat
    if user is None or chat is None:
        return
    async with _db(context).session() as session:
        owner = await UserRepository(session).get_or_create(user.id, chat.id)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id=f"demo-{user.id}",
            title="Senior Python Engineer",
            company="Acme Corp",
            description="Build and scale async Python services.",
            url="https://example.com/jobs/demo",
            location="Remote",
        )
        application = await ApplicationRepository(session).get_or_create(
            user_id=owner.id, job_id=job.id
        )
        # Re-arm so /demo is repeatable even after a prior approve/skip.
        await ApplicationRepository(session).set_status(
            application.id, ApplicationStatus.PENDING_APPROVAL
        )
    tailoring = TailoringResult(
        job_id=job.id,
        resume_id=uuid4(),
        bullets=[
            TailoredBullet(
                text="Scaled async Python services to 10k req/s.",
                source_text="Scaled backend services.",
                grounded=True,
            )
        ],
        ungrounded=[],
    )
    await send_application(
        context.bot,
        chat_id=chat.id,
        job=job,
        tailoring=tailoring,
        application_id=application.id,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve/Skip callback — authorize via the service, then update the message."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    try:
        decision, application_id = parse_callback(query.data)
    except ValueError:
        await query.answer("Unrecognized action.")
        return

    async with _db(context).session() as session:
        outcome = await ApprovalService(session).decide(
            telegram_user_id=query.from_user.id,
            application_id=application_id,
            decision=decision,
        )

    if outcome in (DecisionOutcome.APPROVED, DecisionOutcome.SKIPPED):
        await query.answer(decision_ack(approved=outcome is DecisionOutcome.APPROVED))
        await query.edit_message_reply_markup(reply_markup=None)
    elif outcome is DecisionOutcome.ALREADY_HANDLED:
        await query.answer("Already handled.")
        await query.edit_message_reply_markup(reply_markup=None)
    elif outcome is DecisionOutcome.UNAUTHORIZED:
        # Do not modify the message; only the owner may act on it.
        await query.answer("You can't act on this application.", show_alert=True)
    else:  # NOT_FOUND
        await query.answer("This application no longer exists.")
