"""send_application: card always sent; PDF attached only when provided (Phase 9)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from telegram import Bot

from cinch.bot.notify import TelegramNotifier, send_application
from cinch.domain.enums import JobSourceName
from cinch.domain.models import Job, TailoringResult


def _fake_job() -> Job:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Job(
        id=uuid4(),
        source=JobSourceName.ADZUNA,
        external_id="e1",
        title="Backend Engineer",
        company="Acme",
        location="Remote",
        description="Build things.",
        url="https://example.com/apply",
        discovered_at=now,
        created_at=now,
        updated_at=now,
    )


def _fake_bot() -> MagicMock:
    bot = MagicMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_document = AsyncMock()
    return bot


async def test_send_application_without_pdf_omits_send_document() -> None:
    bot = _fake_bot()
    await send_application(
        bot,
        chat_id=99,
        job=_fake_job(),
        tailoring=TailoringResult(job_id=uuid4(), resume_id=uuid4()),
        application_id=uuid4(),
    )
    bot.send_message.assert_awaited_once()
    bot.send_document.assert_not_called()


async def test_send_application_with_pdf_calls_send_document() -> None:
    bot = _fake_bot()
    pdf_bytes = b"%PDF-1.7 minimal"
    await send_application(
        bot,
        chat_id=99,
        job=_fake_job(),
        tailoring=TailoringResult(job_id=uuid4(), resume_id=uuid4()),
        application_id=uuid4(),
        resume_pdf=pdf_bytes,
    )
    bot.send_message.assert_awaited_once()
    bot.send_document.assert_awaited_once()
    kwargs = bot.send_document.await_args.kwargs
    assert kwargs["chat_id"] == 99
    assert kwargs["document"] == pdf_bytes
    assert kwargs["filename"] == "resume.pdf"


async def test_telegram_notifier_forwards_pdf_kwarg() -> None:
    bot = _fake_bot()
    notifier = TelegramNotifier(bot)
    await notifier.notify(
        chat_id=99,
        job=_fake_job(),
        tailoring=TailoringResult(job_id=uuid4(), resume_id=uuid4()),
        application_id=uuid4(),
        resume_pdf=b"%PDF-1.7 tiny",
    )
    bot.send_document.assert_awaited_once()
