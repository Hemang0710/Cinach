"""Telegram handlers — thin translation between Telegram updates and services.

Handlers pull the injected :class:`~cinch.db.session.Database` and
:class:`~cinch.core.config.Settings` out of ``bot_data`` (dependency injection, no
globals), open a session, and delegate every decision to the service layer. No
business logic or authorization rule lives here — that is in
:class:`~cinch.services.workflow.ApprovalService`.

User content (resume JSON, message text) is never logged.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from telegram import Update
from telegram.ext import ContextTypes

from cinch.bot.keyboards import parse_accept_callback, parse_callback
from cinch.bot.messages import accept_ack, decision_ack
from cinch.bot.notify import send_application, send_offer_card
from cinch.core.config import Settings
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
from cinch.services.workflow import AcceptOutcome, ApprovalService, DecisionOutcome

logger = get_logger(__name__)

_MAX_RESUME_BYTES = 1_000_000  # reject oversized uploads before downloading fully

_WELCOME = (
    "👋 Welcome to Cinch — your human-in-the-loop job application assistant.\n\n"
    "I tailor your master resume to each job and send it here with Approve / Skip "
    "buttons. Nothing is ever submitted without your approval.\n\n"
    "To get started, send me your master resume as a <b>.json</b> or <b>.pdf</b> "
    "file (see /setresume). Then run /discover any time to pull jobs on demand."
)

_SETRESUME_HELP = (
    "Two ways to set your master résumé:\n"
    "• Send a <b>.pdf</b> résumé — I extract the text and structure it (a strict "
    "grounding check refuses anything the parser can't verify in the PDF).\n"
    "• Send a <b>.json</b> file matching Cinch's schema (summary, skills, "
    "experiences[], education[]).\n\n"
    "Either way, I never invent new experience — only rephrase what's real."
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
    """Accept a ``.json`` or ``.pdf`` master-resume upload; validate and store it."""
    message, user, chat = update.message, update.effective_user, update.effective_chat
    if message is None or message.document is None or user is None or chat is None:
        return
    document = message.document
    filename = (document.file_name or "").lower()
    if not (filename.endswith(".json") or filename.endswith(".pdf")):
        await message.reply_text("Please upload your master resume as a .json or .pdf file.")
        return
    if document.file_size is not None and document.file_size > _MAX_RESUME_BYTES:
        await message.reply_text("That file is too large (max 1 MB).")
        return

    tg_file = await document.get_file()
    raw = bytes(await tg_file.download_as_bytearray())

    if filename.endswith(".pdf"):
        master = await _parse_pdf_or_reply(raw, message, context, user_id=user.id)
    else:
        master = await _parse_json_or_reply(raw, message, user_id=user.id)
    if master is None:
        return  # user was already told what went wrong

    async with _db(context).session() as session:
        owner = await UserRepository(session).get_or_create(user.id, chat.id)
        await ResumeRepository(session).set_master(owner.id, master.model_dump())
    logger.info("resume_saved", telegram_user_id=user.id)
    summary = f"parsed {len(master.experiences)} experience(s) and {len(master.skills)} skill(s)"
    await message.reply_text(f"✅ Master resume saved — {summary}.")


async def _parse_json_or_reply(raw: bytes, message: Any, *, user_id: int) -> MasterResume | None:
    try:
        return MasterResume.model_validate_json(raw)
    except ValidationError:
        logger.info("resume_upload_rejected", telegram_user_id=user_id)  # no content logged
        await message.reply_text(
            "That resume JSON didn't match the expected schema. Please fix it and resend."
        )
        return None


async def _parse_pdf_or_reply(
    raw: bytes, message: Any, context: ContextTypes.DEFAULT_TYPE, *, user_id: int
) -> MasterResume | None:
    """Parse a PDF résumé via the anti-fabrication PDFIngestService.

    Any failure is reported to the user with the service's own PII-free message.
    """
    from cinch.providers.llm import get_llm_provider
    from cinch.services.pdf_ingest import PDFIngestError, PDFIngestService

    await message.reply_text("🔎 Parsing your résumé…")
    settings = cast(Settings, context.bot_data["settings"])
    try:
        provider = get_llm_provider(settings)
    except Exception:
        logger.exception("pdf_ingest_no_llm", telegram_user_id=user_id)
        await message.reply_text("⚠️ No LLM provider configured — can't parse PDFs.")
        return None
    service = PDFIngestService(provider, settings)
    try:
        return await service.ingest(raw)
    except PDFIngestError as exc:
        logger.info("pdf_ingest_failed", telegram_user_id=user_id)  # no content logged
        await message.reply_text(str(exc))
        return None
    except Exception:
        logger.exception("pdf_ingest_error", telegram_user_id=user_id)
        await message.reply_text("⚠️ Couldn't parse that PDF — try again later.")
        return None


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


async def discover_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/discover — trigger one discovery cycle now.

    On free hosting the scheduler's 60-min tick often misses because the instance
    sleeps between requests. This lets the user pull jobs on demand from Telegram
    (which wakes the app naturally). Requires the caller to already have a master
    resume — so unauthenticated callers can't spam the Adzuna/LLM quotas.
    """
    message, user, chat = update.message, update.effective_user, update.effective_chat
    if message is None or user is None or chat is None:
        return

    settings = cast(Settings, context.bot_data["settings"])
    if not (settings.adzuna_app_id and settings.adzuna_app_key):
        await message.reply_text("⚠️ Job discovery isn't configured on this instance.")
        return

    db = _db(context)
    async with db.session() as session:
        owner = await UserRepository(session).get_or_create(user.id, chat.id)
        has_master = await ResumeRepository(session).get_master(owner.id) is not None
    if not has_master:
        await message.reply_text("Upload your master resume first (see /setresume).")
        return

    await message.reply_text("🔎 Searching for jobs…")
    from cinch.api.scheduler import run_discovery_cycle

    try:
        summary = await run_discovery_cycle(db, settings, context.bot)
    except Exception:
        logger.exception("discover_command_failed", telegram_user_id=user.id)
        await message.reply_text("⚠️ Job discovery failed — check the server logs.")
        return

    # New job cards were already sent as separate messages by the notifier.
    if summary.notified > 0:
        return
    if summary.discovered == 0:
        await message.reply_text("No jobs found right now. Try again later.")
    else:
        await message.reply_text(
            f"Found {summary.discovered} job(s), but all were already sent to you."
        )


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/dashboard — DM the caller a short-lived signed link to the web dashboard.

    The URL includes a magic-link token that ``GET /dashboard/login`` verifies and
    exchanges for a 7-day session cookie. Only requestable via Telegram, so only
    an authenticated Telegram user (owner of the account) can obtain access.
    """
    from cinch.api.dashboard.router import issue_magic_link

    message, user, chat = update.message, update.effective_user, update.effective_chat
    if message is None or user is None or chat is None:
        return

    settings = cast(Settings, context.bot_data["settings"])
    async with _db(context).session() as session:
        owner = await UserRepository(session).get_or_create(user.id, chat.id)

    try:
        url = issue_magic_link(owner.id, settings)
    except RuntimeError as exc:
        # Missing webhook secret / URL — surface a clean actionable message.
        logger.warning("dashboard_link_unavailable", reason=str(exc))
        await message.reply_text("⚠️ Dashboard isn't fully configured on this instance.")
        return

    await message.reply_html(
        "🔗 <b>One-time dashboard link</b> (valid ~10 min):\n"
        f'<a href="{url}">Open the dashboard</a>\n\n'
        "It sets a 7-day session cookie, so you won't need a fresh link every visit."
    )


async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/accept — list the caller's open offers, each with an Accept button.

    Offers are addressed by inline button (not a typed id): callback data carries
    the application id, and the acceptance is authorized + made idempotent in the
    service layer, exactly like Approve/Skip.
    """
    message, user, chat = update.message, update.effective_user, update.effective_chat
    if message is None or user is None or chat is None:
        return

    async with _db(context).session() as session:
        owner = await UserRepository(session).get_or_create(user.id, chat.id)
        offers = await ApplicationRepository(session).list_offered(owner.id)
        jobs = {offer.id: await JobRepository(session).get(offer.job_id) for offer in offers}

    if not offers:
        await message.reply_text("You have no open offers to accept.")
        return

    for offer in offers:
        job = jobs.get(offer.id)
        if job is None:
            continue
        await send_offer_card(context.bot, chat_id=chat.id, job=job, application_id=offer.id)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route an inline-button press — accept, or approve/skip — through the service."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    # Accept presses carry their own namespace; try that first, else approve/skip.
    try:
        accept_id = parse_accept_callback(query.data)
    except ValueError:
        await query.answer("Unrecognized action.")
        return
    if accept_id is not None:
        await _handle_accept(query, context, accept_id)
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


async def _handle_accept(
    query: Any, context: ContextTypes.DEFAULT_TYPE, application_id: UUID
) -> None:
    """Apply an offer-accept callback and update the message accordingly."""
    async with _db(context).session() as session:
        outcome = await ApprovalService(session).accept(
            telegram_user_id=query.from_user.id,
            application_id=application_id,
        )

    if outcome is AcceptOutcome.ACCEPTED:
        await query.answer(accept_ack())
        await query.edit_message_reply_markup(reply_markup=None)
    elif outcome is AcceptOutcome.NOT_OFFERED:
        await query.answer("Already handled.")
        await query.edit_message_reply_markup(reply_markup=None)
    elif outcome is AcceptOutcome.UNAUTHORIZED:
        # Do not modify the message; only the owner may act on it.
        await query.answer("You can't act on this application.", show_alert=True)
    else:  # NOT_FOUND
        await query.answer("This application no longer exists.")
