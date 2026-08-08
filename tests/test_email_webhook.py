"""POST /webhook/email: auth, LLM classification, DB update, DM notification."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from cinch.api.app import create_app
from cinch.api.email_webhook import WEBHOOK_SECRET_HEADER
from cinch.core.config import Settings
from cinch.db.repositories import ApplicationRepository, JobRepository, UserRepository
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.providers.llm.fake import FakeLLMProvider

_SECRET = "test-cinch-webhook-secret"
_OWNER_TG_ID = 42
_CHAT_ID = 99


@pytest.fixture
def webhook_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="local",
        log_json=False,
        interview_webhook_secret=_SECRET,
        anthropic_api_key="unused-because-we-patch-get_llm_provider",
    )


@pytest.fixture
async def webhook_client(webhook_settings: Settings, db: Database) -> AsyncIterator[AsyncClient]:
    app = create_app(settings=webhook_settings, db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _seed_submitted_application(db: Database, *, company: str = "Acme Corp") -> str:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(_OWNER_TG_ID, _CHAT_ID)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id="e1",
            title="Backend Engineer",
            company=company,
            description="d",
            url="https://ex.com/apply",
        )
        app = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job.id, status=ApplicationStatus.SUBMITTED
        )
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


async def test_missing_secret_returns_401(webhook_client: AsyncClient) -> None:
    r = await webhook_client.post("/webhook/email", json=_PAYLOAD)
    assert r.status_code == 401


async def test_wrong_secret_returns_401(webhook_client: AsyncClient) -> None:
    r = await webhook_client.post(
        "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: "wrong-value"}
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
            headers={WEBHOOK_SECRET_HEADER: _SECRET},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "status_updated"
    assert body["new_status"] == "interview_invited"
    assert body["application_id"] == app_id

    async with db.session() as session:
        updated = await ApplicationRepository(session).get(__import__("uuid").UUID(app_id))
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
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: _SECRET}
        )
    assert r.status_code == 200 and r.json()["new_status"] == "rejected"

    async with db.session() as session:
        updated = await ApplicationRepository(session).get(__import__("uuid").UUID(app_id))
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
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: _SECRET}
        )

    assert r.status_code == 200
    assert r.json()["action"] == "no_status_change"
    async with db.session() as session:
        app = await ApplicationRepository(session).get(__import__("uuid").UUID(app_id))
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
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: _SECRET}
        )

    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "no_status_change"
    assert "matched" in body["reason"]


async def test_webhook_unconfigured_returns_503(db: Database) -> None:
    """No INTERVIEW_WEBHOOK_SECRET set → webhook refuses cleanly."""
    settings = Settings(_env_file=None, interview_webhook_secret=None)
    app = create_app(settings=settings, db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        r = await ac.post(
            "/webhook/email", json=_PAYLOAD, headers={WEBHOOK_SECRET_HEADER: "anything"}
        )
    assert r.status_code == 503


async def test_malformed_payload_returns_422(webhook_client: AsyncClient) -> None:
    """Missing required 'from_email' → FastAPI's built-in Pydantic 422."""
    r = await webhook_client.post(
        "/webhook/email",
        json={"subject": "no from field"},
        headers={WEBHOOK_SECRET_HEADER: _SECRET},
    )
    assert r.status_code == 422
