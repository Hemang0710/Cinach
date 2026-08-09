"""Phase 12 — /accept command + offer-accept callback.

Same security discipline as Approve/Skip: only the owning Telegram user can
accept, only an OFFERED application transitions, and a double-tap is a no-op.
Uses mocked Telegram objects over a real in-memory database.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from cinch.bot import handlers
from cinch.core.config import Settings
from cinch.db.repositories import ApplicationRepository, JobRepository, UserRepository
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName

OWNER_TG_ID = 42
OTHER_TG_ID = 999
CHAT_ID = 99


async def _seed_offer(
    db: Database,
    *,
    external_id: str = "off-1",
    status: ApplicationStatus = ApplicationStatus.OFFERED,
) -> UUID:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(OWNER_TG_ID, CHAT_ID)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id=external_id,
            title="Staff Engineer",
            company="Globex",
            description="D",
            url=f"https://example.com/{external_id}",
        )
        app = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job.id, status=status
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


def _command_update() -> tuple[MagicMock, MagicMock]:
    message = MagicMock()
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_user = SimpleNamespace(id=OWNER_TG_ID)
    update.effective_chat = SimpleNamespace(id=CHAT_ID)
    return update, message


def _context(db: Database, settings: Settings) -> MagicMock:
    ctx = MagicMock()
    ctx.bot_data = {"db": db, "settings": settings}
    ctx.bot = MagicMock()
    return ctx


# --- /accept command listing -------------------------------------------------


async def test_accept_command_with_no_offers_replies_cleanly(
    db: Database, settings: Settings
) -> None:
    update, message = _command_update()
    await handlers.accept_command(update, _context(db, settings))
    message.reply_text.assert_awaited_once()
    assert "no open offers" in message.reply_text.await_args.args[0].lower()


async def test_accept_command_sends_one_card_per_offer(db: Database, settings: Settings) -> None:
    id1 = await _seed_offer(db, external_id="off-1")
    id2 = await _seed_offer(db, external_id="off-2")
    update, _ = _command_update()

    with patch("cinch.bot.handlers.send_offer_card", AsyncMock()) as send:
        await handlers.accept_command(update, _context(db, settings))

    assert send.await_count == 2
    sent_ids = {call.kwargs["application_id"] for call in send.await_args_list}
    assert sent_ids == {id1, id2}


# --- accept callback ---------------------------------------------------------


async def test_owner_accept_transitions_and_removes_buttons(
    db: Database, settings: Settings
) -> None:
    app_id = await _seed_offer(db)
    update, query = _callback_update(data=f"accept:{app_id}", from_user_id=OWNER_TG_ID)
    await handlers.callback_handler(update, _context(db, settings))

    assert await _status(db, app_id) is ApplicationStatus.ACCEPTED
    query.answer.assert_awaited_once()
    query.edit_message_reply_markup.assert_awaited_once()


async def test_non_owner_accept_leaves_status_unchanged(db: Database, settings: Settings) -> None:
    app_id = await _seed_offer(db)
    update, query = _callback_update(data=f"accept:{app_id}", from_user_id=OTHER_TG_ID)
    await handlers.callback_handler(update, _context(db, settings))

    assert await _status(db, app_id) is ApplicationStatus.OFFERED
    query.answer.assert_awaited_once()
    query.edit_message_reply_markup.assert_not_called()  # message left intact


async def test_accept_on_non_offered_is_noop(db: Database, settings: Settings) -> None:
    # A SUBMITTED application can't be accepted — nothing to accept there.
    app_id = await _seed_offer(db, status=ApplicationStatus.SUBMITTED)
    update, query = _callback_update(data=f"accept:{app_id}", from_user_id=OWNER_TG_ID)
    await handlers.callback_handler(update, _context(db, settings))

    assert await _status(db, app_id) is ApplicationStatus.SUBMITTED
    query.answer.assert_awaited_once()


async def test_double_tap_accept_is_idempotent(db: Database, settings: Settings) -> None:
    app_id = await _seed_offer(db)
    ctx = _context(db, settings)

    update1, _ = _callback_update(data=f"accept:{app_id}", from_user_id=OWNER_TG_ID)
    await handlers.callback_handler(update1, ctx)
    assert await _status(db, app_id) is ApplicationStatus.ACCEPTED

    # Second press: already ACCEPTED → NOT_OFFERED, still ACCEPTED (no corruption).
    update2, query2 = _callback_update(data=f"accept:{app_id}", from_user_id=OWNER_TG_ID)
    await handlers.callback_handler(update2, ctx)
    assert await _status(db, app_id) is ApplicationStatus.ACCEPTED
    query2.answer.assert_awaited_once()


async def test_accept_unknown_application_is_answered(db: Database, settings: Settings) -> None:
    update, query = _callback_update(data=f"accept:{uuid4()}", from_user_id=OWNER_TG_ID)
    await handlers.callback_handler(update, _context(db, settings))
    query.answer.assert_awaited_once()
    query.edit_message_reply_markup.assert_not_called()
