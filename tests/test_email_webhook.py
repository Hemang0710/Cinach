"""POST /webhook/email: per-user token auth, classification, DB update, DM.

Phase 14: the ``X-Cinch-Webhook-Secret`` header carries a per-user token (issued
by ``/emailhook``), not a global shared secret. The route resolves token → user
and matches only within that user's applications.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from cinch.api.app import create_app
from cinch.api.email_webhook import WEBHOOK_SECRET_HEADER
from cinch.core.config import Settings
from cinch.db.models import UserORM
from cinch.db.repositories import ApplicationRepository, JobRepository, UserRepository
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.providers.llm.fake import FakeLLMProvider

_TOKEN = "test-user-email-token"
_OWNER_TG_ID = 42
_CHAT_ID = 99


@pytest.fixture
def webhook_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="local",
        log_json=False,
        anthropic_api_key="unused-because-we-patch-get_llm_provider",
    )


@pytest.fixture
async def webhook_client(webhook_settings: Settings, db: Database) -> AsyncIterator[AsyncClient]:
    app = create_app(settings=webhook_settings, db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _set_token(db: Database, user_id: UUID, token: str) -> None:
    """Pin a known email-webhook token on a user so tests can send it in the header."""
    async with db.session() as session:
        orm = await session.get(UserORM, user_id)
        assert orm is not None
        orm.email_webhook_token = token
        await session.commit()


async def _seed_submitted_application(
    db: Database,
    *,
    company: str = "Acme Corp",
    telegram_id: int = _OWNER_TG_ID,
    chat_id: int = _CHAT_ID,
    token: str = _TOKEN,
    external_id: str = "e1",
) -> str:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(telegram_id, chat_id)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id=external_id,
            title="Backend Engineer",
            company=company,
            description="d",
            url="https://ex.com/apply",
        )
        app = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job.id, status=ApplicationStatus.SUBMITTED
        )
        user_id = user.id
    await _set_token(db, user_id, token)
    return str(app.id)


def _llm_returning(json_response: str) -> object:
    return FakeLLMProvider([json_response])


_PAYLOAD = {
    "from_email": "recruiter@acme.com",
    "from_name": "Acme Recruiting",
    "subject": "Phone screen for Backend Engineer role",
    "body_text": "Hi, we'd like to set up a phone screen next week.",
    "received_at": "2026-08-07T12:00:00Z",
}


async def test_missing_token_returns_401(webhook_client: AsyncClient) -> None:
    r = await webhook_client.post("/webhook/email", json=_PAYLOAD)
    assert r.status_code == 401


async def test_unknown_token_returns_401(webhook_client: AsyncClient, db: Database) -> None:
    """A well-formed request whose token matches no user is rejected (no info leak)."""
    await _seed_submitted_application(db)  # a user exists, but with a different token
    r = await webhook_client.post(
        "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: "not-a-real-token"}
    )
    assert r.status_code == 401


async def test_valid_interview_email_updates_status_and_replies_200(
    webhook_client: AsyncClient, db: Database
) -> None:
    app_id = await _seed_submitted_application(db)

    fake_llm = _llm_returning(
        '{"classification": "interview_invited", '
        '"company_hint": "Acme", '
        '"summary": "Phone screen scheduled."}'
    )
    with patch("cinch.api.email_webhook.get_llm_provider", return_value=fake_llm):
        r = await webhook_client.post(
            "/webhook/email",
            json=_PAYLOAD,
            headers={WEBHOOK_SECRET_HEADER: _TOKEN},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "status_updated"
    assert body["new_status"] == "interview_invited"
    assert body["application_id"] == app_id

    async with db.session() as session:
        updated = await ApplicationRepository(session).get(UUID(app_id))
    assert updated is not None
    assert updated.status is ApplicationStatus.INTERVIEW_INVITED
    assert updated.last_email_summary == "Phone screen scheduled."
    assert updated.last_email_at is not None


async def test_rejection_email_advances_to_rejected(
    webhook_client: AsyncClient, db: Database
) -> None:
    app_id = await _seed_submitted_application(db)

    fake_llm = _llm_returning(
        '{"classification": "rejection", "company_hint": "Acme", "summary": "Not moving forward."}'
    )
    with patch("cinch.api.email_webhook.get_llm_provider", return_value=fake_llm):
        r = await webhook_client.post(
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: _TOKEN}
        )
    assert r.status_code == 200 and r.json()["new_status"] == "rejected"

    async with db.session() as session:
        updated = await ApplicationRepository(session).get(UUID(app_id))
    assert updated is not None
    assert updated.status is ApplicationStatus.REJECTED


async def test_acknowledgement_email_leaves_status_unchanged(
    webhook_client: AsyncClient, db: Database
) -> None:
    """Auto-reply / 'we received your application' must not advance state."""
    app_id = await _seed_submitted_application(db)

    fake_llm = _llm_returning(
        '{"classification": "acknowledgement", "company_hint": "Acme", "summary": "Auto-reply."}'
    )
    with patch("cinch.api.email_webhook.get_llm_provider", return_value=fake_llm):
        r = await webhook_client.post(
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: _TOKEN}
        )

    assert r.status_code == 200
    assert r.json()["action"] == "no_status_change"
    async with db.session() as session:
        app = await ApplicationRepository(session).get(UUID(app_id))
    assert app is not None
    assert app.status is ApplicationStatus.SUBMITTED  # unchanged


async def test_no_matching_application_is_a_no_op_200(
    webhook_client: AsyncClient, db: Database
) -> None:
    await _seed_submitted_application(db, company="Beta Inc")

    fake_llm = _llm_returning(
        '{"classification": "interview_invited", "company_hint": "Zeta", "summary": "..."}'
    )
    with patch("cinch.api.email_webhook.get_llm_provider", return_value=fake_llm):
        r = await webhook_client.post(
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: _TOKEN}
        )

    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "no_status_change"
    assert "matched" in body["reason"]


async def test_token_routes_to_correct_user_only(webhook_client: AsyncClient, db: Database) -> None:
    """Tenant isolation: an email with user A's token never touches user B's app.

    Both users have a SUBMITTED application at the same company, so matching by
    company alone would be ambiguous — the token is what scopes it to user A.
    """
    app_a = await _seed_submitted_application(
        db, telegram_id=1, chat_id=1, token="token-a", external_id="a1"
    )
    app_b = await _seed_submitted_application(
        db, telegram_id=2, chat_id=2, token="token-b", external_id="b1"
    )

    fake_llm = _llm_returning(
        '{"classification": "offer", "company_hint": "Acme", "summary": "Offer!"}'
    )
    with patch("cinch.api.email_webhook.get_llm_provider", return_value=fake_llm):
        r = await webhook_client.post(
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: "token-a"}
        )

    assert r.status_code == 200
    assert r.json()["application_id"] == app_a  # A advanced, not B

    async with db.session() as session:
        repo = ApplicationRepository(session)
        a = await repo.get(UUID(app_a))
        b = await repo.get(UUID(app_b))
    assert a is not None and a.status is ApplicationStatus.OFFERED
    assert b is not None and b.status is ApplicationStatus.SUBMITTED  # untouched


async def test_malformed_payload_returns_422(webhook_client: AsyncClient) -> None:
    """Missing required 'from_email' → FastAPI's built-in Pydantic 422 (before auth)."""
    r = await webhook_client.post(
        "/webhook/email",
        json={"subject": "no from field"},
        headers={WEBHOOK_SECRET_HEADER: _TOKEN},
    )
    assert r.status_code == 422
