"""Outbound notification: send a job + tailored resume with Approve/Skip buttons.

Used by the ``/demo`` command now and by the Phase 4 scheduler later. Sends through
``bot.send_message``, which the PTB ``AIORateLimiter`` throttles (per-chat + global)
and retries on 429 — so callers don't implement backoff themselves.
"""

from __future__ import annotations

from uuid import UUID

from telegram import Bot
from telegram.constants import ParseMode

from cinch.bot.keyboards import accept_markup, approve_skip_markup
from cinch.bot.messages import (
    format_application_message,
    format_email_update_message,
    format_ghosted_message,
    format_offer_card,
    format_submission_message,
)
from cinch.domain.enums import ApplicationStatus
from cinch.domain.models import Job, TailoringResult
from cinch.providers.submit.base import SubmissionOutcome


async def send_application(
    bot: Bot,
    *,
    chat_id: int,
    job: Job,
    tailoring: TailoringResult,
    application_id: UUID,
    resume_pdf: bytes | None = None,
) -> None:
    """Send the application card (job + highlights) with Approve/Skip buttons.

    When ``resume_pdf`` is provided (Phase 9), the tailored résumé is sent as a
    ``.pdf`` attachment right after the card so the user can preview exactly what
    would be submitted. If it isn't provided, only the card is sent — no failure.
    """
    await bot.send_message(
        chat_id=chat_id,
        text=format_application_message(job, tailoring),
        parse_mode=ParseMode.HTML,
        reply_markup=approve_skip_markup(application_id, job.title, job.location),
        disable_web_page_preview=True,
    )
    if resume_pdf is not None:
        await bot.send_document(
            chat_id=chat_id,
            document=resume_pdf,
            filename="resume.pdf",
            caption="Your résumé, tailored for this job.",
            disable_content_type_detection=False,
        )


class TelegramNotifier:
    """Adapts a Telegram ``Bot`` to the discovery layer's ``JobNotifier`` protocol.

    Lives in the bot layer so ``services/`` never imports Telegram; the discovery
    orchestrator depends only on the protocol.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify(
        self,
        *,
        chat_id: int,
        job: Job,
        tailoring: TailoringResult,
        application_id: UUID,
        resume_pdf: bytes | None = None,
    ) -> None:
        """Deliver a tailored application via Telegram (rate-limited by AIORateLimiter)."""
        await send_application(
            self._bot,
            chat_id=chat_id,
            job=job,
            tailoring=tailoring,
            application_id=application_id,
            resume_pdf=resume_pdf,
        )


async def send_submission_update(
    bot: Bot, *, chat_id: int, job: Job, outcome: SubmissionOutcome, detail: str
) -> None:
    """Send a submission outcome message (no buttons — it's a terminal notification)."""
    await bot.send_message(
        chat_id=chat_id,
        text=format_submission_message(job, outcome, detail),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


class TelegramSubmissionNotifier:
    """Adapts a Telegram ``Bot`` to the submission layer's ``SubmissionNotifier`` protocol.

    Lives in the bot layer so ``services/`` never imports Telegram; the submission
    orchestrator depends only on the protocol.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify_submission(
        self, *, chat_id: int, job: Job, outcome: SubmissionOutcome, detail: str
    ) -> None:
        """Deliver a submission outcome via Telegram (rate-limited by AIORateLimiter)."""
        await send_submission_update(
            self._bot, chat_id=chat_id, job=job, outcome=outcome, detail=detail
        )


async def send_email_status_update(
    bot: Bot, *, chat_id: int, job: Job, status: ApplicationStatus, summary: str
) -> None:
    """Send a Telegram nudge when an inbound email advanced an application's status.

    Terminal notification — no buttons. The user can open the dashboard for detail.
    """
    await bot.send_message(
        chat_id=chat_id,
        text=format_email_update_message(job, status, summary),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def send_offer_card(bot: Bot, *, chat_id: int, job: Job, application_id: UUID) -> None:
    """Send one open-offer card with an Accept button (used by ``/accept``)."""
    await bot.send_message(
        chat_id=chat_id,
        text=format_offer_card(job),
        parse_mode=ParseMode.HTML,
        reply_markup=accept_markup(application_id),
        disable_web_page_preview=True,
    )


async def send_ghosted_notice(bot: Bot, *, chat_id: int, job: Job, quiet_days: int) -> None:
    """Send the terminal "no response" nudge for a newly-ghosted application."""
    await bot.send_message(
        chat_id=chat_id,
        text=format_ghosted_message(job, quiet_days=quiet_days),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


class TelegramGhostNotifier:
    """Adapts a Telegram ``Bot`` to the sweep layer's ``GhostNotifier`` protocol.

    Lives in the bot layer so ``services/`` never imports Telegram; the sweep
    orchestrator depends only on the protocol.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify_ghosted(self, *, chat_id: int, job: Job, quiet_days: int) -> None:
        """Deliver a ghosted notice via Telegram (rate-limited by AIORateLimiter)."""
        await send_ghosted_notice(self._bot, chat_id=chat_id, job=job, quiet_days=quiet_days)
