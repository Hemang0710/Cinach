"""Bot handler tests with mocked Telegram objects + a real in-memory database.

Focus on the security-relevant paths: the callback handler must only mutate state
for the owning user, and the document handler must reject resume JSON that fails
schema validation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from cinch.bot import handlers
from cinch.core.config import Settings
from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    ResumeRepository,
    UserRepository,
)
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.services.discovery import DiscoverySummary

OWNER_TG_ID = 42
OTHER_TG_ID = 999
CHAT_ID = 99


async def _seed_pending(db: Database, *, owner_tg_id: int = OWNER_TG_ID) -> UUID:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(owner_tg_id, CHAT_ID)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id="h-1",
            title="T",
            company="C",
            description="D",
            url="https://example.com/1",
        )
        app = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job.id, status=ApplicationStatus.PENDING_APPROVAL
        )
    return app.id


async def _status(db: Database, application_id: UUID) -> ApplicationStatus:
    async with db.session() as session:
        app = await ApplicationRepository(session).get(application_id)
    assert app is not None
    return app.status


def _callback_update(*, data: str, from_user_id: int) -> tuple[MagicMock, MagicMock]:
    query = MagicMock()
    query.data = data
    query.from_user = SimpleNamespace(id=from_user_id)
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


def _context(db: Database, settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"db": db, "settings": settings}
    return ctx


async def test_owner_approve_records_status_and_removes_buttons(
    db: Database, settings: Settings
) -> None:
    app_id = await _seed_pending(db)
    update, query = _callback_update(data=f"approve:{app_id}", from_user_id=OWNER_TG_ID)
    await handlers.callback_handler(update, _context(db, settings))

    assert await _status(db, app_id) is ApplicationStatus.APPROVED
    query.answer.assert_awaited_once()
    query.edit_message_reply_markup.assert_awaited_once()


async def test_non_owner_callback_leaves_status_unchanged(db: Database, settings: Settings) -> None:
    app_id = await _seed_pending(db)
    update, query = _callback_update(data=f"approve:{app_id}", from_user_id=OTHER_TG_ID)
    await handlers.callback_handler(update, _context(db, settings))

    assert await _status(db, app_id) is ApplicationStatus.PENDING_APPROVAL
    query.answer.assert_awaited_once()  # answered, but...
    query.edit_message_reply_markup.assert_not_called()  # ...message left intact


async def test_malformed_callback_is_answered_without_db_change(
    db: Database, settings: Settings
) -> None:
    app_id = await _seed_pending(db)
    update, query = _callback_update(data="garbage", from_user_id=OWNER_TG_ID)
    await handlers.callback_handler(update, _context(db, settings))

    assert await _status(db, app_id) is ApplicationStatus.PENDING_APPROVAL
    query.answer.assert_awaited_once()
    query.edit_message_reply_markup.assert_not_called()


def _document_update(
    *, content: bytes, file_name: str = "resume.json"
) -> tuple[MagicMock, MagicMock]:
    tg_file = MagicMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(content))
    document = MagicMock()
    document.file_name = file_name
    document.file_size = len(content)
    document.get_file = AsyncMock(return_value=tg_file)
    message = MagicMock()
    message.document = document
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_user = SimpleNamespace(id=OWNER_TG_ID)
    update.effective_chat = SimpleNamespace(id=CHAT_ID)
    return update, message


async def test_document_handler_rejects_invalid_schema(db: Database, settings: Settings) -> None:
    update, message = _document_update(content=b'{"unexpected_field": 1}')
    await handlers.document_handler(update, _context(db, settings))

    message.reply_text.assert_awaited_once()
    assert "schema" in message.reply_text.await_args.args[0].lower()
    async with db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
        assert user is None or await ResumeRepository(session).get_master(user.id) is None


async def test_document_handler_saves_valid_master_resume(db: Database, settings: Settings) -> None:
    resume_json = (
        b'{"summary": "Engineer", "skills": ["Python"], '
        b'"experiences": [{"company": "C", "title": "T", "start": "2020", '
        b'"bullets": ["Built X"]}], "education": []}'
    )
    update, message = _document_update(content=resume_json)
    await handlers.document_handler(update, _context(db, settings))

    message.reply_text.assert_awaited_once()
    async with db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
        assert user is not None
        master = await ResumeRepository(session).get_master(user.id)
        assert master is not None
        assert master.content["summary"] == "Engineer"


async def test_document_handler_rejects_unknown_extension(db: Database, settings: Settings) -> None:
    update, message = _document_update(content=b"anything", file_name="resume.docx")
    await handlers.document_handler(update, _context(db, settings))
    message.reply_text.assert_awaited_once()
    assert ".json" in message.reply_text.await_args.args[0]
    assert ".pdf" in message.reply_text.await_args.args[0]


async def test_document_handler_routes_pdf_through_ingest_service(
    db: Database, settings: Settings
) -> None:
    """A .pdf upload runs through PDFIngestService and saves the returned MasterResume."""
    from cinch.domain.resume import ExperienceEntry, MasterResume
    from cinch.providers.llm.fake import FakeLLMProvider

    fake_master = MasterResume(
        name="Jane Doe",
        email="jane@example.com",
        summary="Engineer",
        skills=["Python"],
        experiences=[ExperienceEntry(company="C", title="T", start="2020", bullets=["Built X"])],
    )
    update, message = _document_update(content=b"fake-pdf-bytes", file_name="resume.pdf")

    with (
        patch("cinch.providers.llm.get_llm_provider", return_value=FakeLLMProvider([])),
        patch(
            "cinch.services.pdf_ingest.PDFIngestService.ingest",
            AsyncMock(return_value=fake_master),
        ),
    ):
        await handlers.document_handler(update, _context(db, settings))

    # First reply is "🔎 Parsing…", second is "✅ Master resume saved — …".
    assert message.reply_text.await_count == 2
    assert "saved" in message.reply_text.await_args.args[0].lower()
    async with db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
        assert user is not None
        master = await ResumeRepository(session).get_master(user.id)
        assert master is not None
        assert master.content["name"] == "Jane Doe"


async def test_document_handler_pdf_ingest_failure_replies_and_does_not_save(
    db: Database, settings: Settings
) -> None:
    from cinch.providers.llm.fake import FakeLLMProvider
    from cinch.services.pdf_ingest import PDFIngestError

    update, message = _document_update(content=b"fake-pdf-bytes", file_name="resume.pdf")
    with (
        patch("cinch.providers.llm.get_llm_provider", return_value=FakeLLMProvider([])),
        patch(
            "cinch.services.pdf_ingest.PDFIngestService.ingest",
            AsyncMock(side_effect=PDFIngestError("Parsed field 'name' isn't in the PDF text.")),
        ),
    ):
        await handlers.document_handler(update, _context(db, settings))

    # "🔎 Parsing…" then the error message — never "saved".
    assert message.reply_text.await_count == 2
    assert "isn't in the PDF" in message.reply_text.await_args.args[0]
    async with db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
        assert user is None or await ResumeRepository(session).get_master(user.id) is None


def _command_update() -> tuple[MagicMock, MagicMock]:
    message = MagicMock()
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_user = SimpleNamespace(id=OWNER_TG_ID)
    update.effective_chat = SimpleNamespace(id=CHAT_ID)
    return update, message


async def _seed_master_resume(db: Database) -> None:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(OWNER_TG_ID, CHAT_ID)
        await ResumeRepository(session).set_master(
            user.id,
            {"summary": "E", "skills": ["Py"], "experiences": [], "education": []},
        )


async def test_discover_command_needs_adzuna_configured(db: Database) -> None:
    # Fresh settings with no ambient .env so the check is deterministic.
    settings = Settings(_env_file=None)
    update, message = _command_update()
    await handlers.discover_command(update, _context(db, settings))
    message.reply_text.assert_awaited_once()
    assert "configured" in message.reply_text.await_args.args[0].lower()


async def test_discover_command_asks_for_resume_first(db: Database) -> None:
    settings = Settings(_env_file=None, adzuna_app_id="a", adzuna_app_key="k")
    update, message = _command_update()
    await handlers.discover_command(update, _context(db, settings))
    # First reply asks the user to upload their resume; never triggers a cycle.
    assert any("resume" in call.args[0].lower() for call in message.reply_text.await_args_list)


async def test_discover_command_runs_cycle_when_configured(db: Database) -> None:
    await _seed_master_resume(db)
    settings = Settings(_env_file=None, adzuna_app_id="a", adzuna_app_key="k")
    update, message = _command_update()
    fake_cycle = AsyncMock(return_value=DiscoverySummary(users=1, discovered=2, notified=2))

    with patch("cinch.api.scheduler.run_discovery_cycle", fake_cycle):
        await handlers.discover_command(update, _context(db, settings))

    fake_cycle.assert_awaited_once()
    # Only the "🔎 Searching…" ack is sent; job cards themselves are sent by the notifier.
    assert message.reply_text.await_count == 1
    assert "search" in message.reply_text.await_args.args[0].lower()


async def _dashboard_update() -> tuple[MagicMock, MagicMock]:
    """A fresh /dashboard invocation update + captured reply_html mock."""
    message = MagicMock()
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_user = SimpleNamespace(id=OWNER_TG_ID)
    update.effective_chat = SimpleNamespace(id=CHAT_ID)
    return update, message


async def test_dashboard_command_dms_signed_magic_link(db: Database) -> None:
    """/dashboard replies with an HTML link containing the signed magic-link URL."""
    settings = Settings(
        _env_file=None,
        telegram_webhook_secret="test-secret-abc123",
        telegram_webhook_url="https://cinch.example.com",
    )
    update, message = await _dashboard_update()

    await handlers.dashboard_command(update, _context(db, settings))

    message.reply_html.assert_awaited_once()
    body = message.reply_html.await_args.args[0]
    assert "cinch.example.com/dashboard/login?token=" in body
    assert "10 min" in body  # user-visible TTL hint


async def test_dashboard_command_fails_gracefully_when_unconfigured(db: Database) -> None:
    """No webhook secret / URL configured → clean 'not configured' message."""
    settings = Settings(_env_file=None)  # missing both
    update, message = await _dashboard_update()

    await handlers.dashboard_command(update, _context(db, settings))

    message.reply_text.assert_awaited_once()
    assert "configured" in message.reply_text.await_args.args[0].lower()
    message.reply_html.assert_not_called()  # no link ever leaked


# --- Phase 14: allowlist + /emailhook ---------------------------------------


def _message_update(
    *, from_user_id: int = OWNER_TG_ID, chat_id: int = CHAT_ID, chat_type: str = "private"
) -> tuple[MagicMock, MagicMock]:
    """A message-based update (for /start, /emailhook) with reply_html/reply_text."""
    message = MagicMock()
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_user = SimpleNamespace(id=from_user_id)
    update.effective_chat = SimpleNamespace(id=chat_id, type=chat_type)
    return update, message


async def test_start_registers_allowlisted_user(db: Database) -> None:
    settings = Settings(_env_file=None, allowed_telegram_ids=str(OWNER_TG_ID))
    update, message = _message_update()
    await handlers.start_command(update, _context(db, settings))

    message.reply_html.assert_awaited_once()  # welcome sent
    async with db.session() as session:
        assert await UserRepository(session).get_by_telegram_id(OWNER_TG_ID) is not None


async def test_start_rejects_non_allowlisted_user_without_registering(db: Database) -> None:
    settings = Settings(_env_file=None, allowed_telegram_ids=str(OWNER_TG_ID))
    update, message = _message_update(from_user_id=OTHER_TG_ID)
    await handlers.start_command(update, _context(db, settings))

    message.reply_text.assert_awaited_once()
    assert "private" in message.reply_text.await_args.args[0].lower()
    message.reply_html.assert_not_called()  # no welcome
    async with db.session() as session:
        assert await UserRepository(session).get_by_telegram_id(OTHER_TG_ID) is None  # no row


async def test_empty_allowlist_is_open(db: Database) -> None:
    settings = Settings(_env_file=None, allowed_telegram_ids="")
    update, message = _message_update(from_user_id=OTHER_TG_ID)
    await handlers.start_command(update, _context(db, settings))

    message.reply_html.assert_awaited_once()
    async with db.session() as session:
        assert await UserRepository(session).get_by_telegram_id(OTHER_TG_ID) is not None


async def test_document_upload_rejected_when_not_allowlisted(db: Database) -> None:
    settings = Settings(_env_file=None, allowed_telegram_ids="1,2,3")  # OWNER not listed
    update, message = _document_update(content=b'{"summary": "x"}')
    await handlers.document_handler(update, _context(db, settings))

    message.reply_text.assert_awaited_once()
    assert "private" in message.reply_text.await_args.args[0].lower()
    async with db.session() as session:
        assert await UserRepository(session).get_by_telegram_id(OWNER_TG_ID) is None


async def test_emailhook_issues_token_and_persists_it(db: Database) -> None:
    settings = Settings(_env_file=None, telegram_webhook_url="https://cinch.example.com")
    update, message = _message_update()
    await handlers.emailhook_command(update, _context(db, settings))

    message.reply_html.assert_awaited_once()
    body = message.reply_html.await_args.args[0]
    assert "cinch.example.com/webhook/email" in body
    async with db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
    assert user is not None and user.email_webhook_token is not None
    assert user.email_webhook_token in body  # the exact token is shown to the user


async def test_emailhook_refuses_non_private_chat(db: Database) -> None:
    settings = Settings(_env_file=None)
    update, message = _message_update(chat_type="group")
    await handlers.emailhook_command(update, _context(db, settings))

    message.reply_text.assert_awaited_once()
    assert "direct message" in message.reply_text.await_args.args[0].lower()
    message.reply_html.assert_not_called()  # secret never sent to a group
    async with db.session() as session:
        user = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
    assert user is None or user.email_webhook_token is None


async def test_emailhook_rotates_existing_token(db: Database) -> None:
    settings = Settings(_env_file=None)
    update, message = _message_update()

    await handlers.emailhook_command(update, _context(db, settings))
    async with db.session() as session:
        user1 = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
    assert user1 is not None
    first = user1.email_webhook_token

    await handlers.emailhook_command(update, _context(db, settings))
    async with db.session() as session:
        user2 = await UserRepository(session).get_by_telegram_id(OWNER_TG_ID)
    assert user2 is not None
    second = user2.email_webhook_token

    assert first is not None and second is not None and first != second
    assert "no longer works" in message.reply_html.await_args.args[0]  # rotation notice


async def test_discover_rejected_when_not_allowlisted_creates_no_user(db: Database) -> None:
    """A non-allowlisted /discover is refused before any user row or quota spend."""
    settings = Settings(
        _env_file=None,
        allowed_telegram_ids="1,2,3",  # OWNER not listed
        adzuna_app_id="a",
        adzuna_app_key="k",
    )
    update, message = _command_update()
    await handlers.discover_command(update, _context(db, settings))

    message.reply_text.assert_awaited_once()
    assert "private" in message.reply_text.await_args.args[0].lower()
    async with db.session() as session:
        assert await UserRepository(session).get_by_telegram_id(OWNER_TG_ID) is None
