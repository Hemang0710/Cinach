"""Outbound notification: send a job + tailored resume with Approve/Skip buttons.

Used by the ``/demo`` command now and by the Phase 4 scheduler later. Sends through
``bot.send_message``, which the PTB ``AIORateLimiter`` throttles (per-chat + global)
and retries on 429 — so callers don't implement backoff themselves.
"""

from __future__ import annotations

from uuid import UUID

from telegram import Bot
from telegram.constants import ParseMode

from cinch.bot.keyboards import approve_skip_markup
from cinch.bot.messages import format_application_message
from cinch.domain.models import Job, TailoringResult


async def send_application(
    bot: Bot,
    *,
    chat_id: int,
    job: Job,
    tailoring: TailoringResult,
    application_id: UUID,
) -> None:
    """Send the application card (job + highlights) with Approve/Skip buttons."""
    await bot.send_message(
        chat_id=chat_id,
        text=format_application_message(job, tailoring),
        parse_mode=ParseMode.HTML,
        reply_markup=approve_skip_markup(application_id),
        disable_web_page_preview=True,
    )


class TelegramNotifier:
    """Adapts a Telegram ``Bot`` to the discovery layer's ``JobNotifier`` protocol.

    Lives in the bot layer so ``services/`` never imports Telegram; the discovery
    orchestrator depends only on the protocol.
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify(
        self, *, chat_id: int, job: Job, tailoring: TailoringResult, application_id: UUID
    ) -> None:
        """Deliver a tailored application via Telegram (rate-limited by AIORateLimiter)."""
        await send_application(
            self._bot,
            chat_id=chat_id,
            job=job,
            tailoring=tailoring,
            application_id=application_id,
        )
