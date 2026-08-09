"""End-to-end dashboard routes: magic-link → session cookie → HTML fragments."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from cinch.api.app import create_app
from cinch.api.dashboard.auth import (
    MAGIC_LINK_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    sign_token,
)
from cinch.api.dashboard.router import SESSION_COOKIE_NAME, issue_magic_link
from cinch.core.config import Settings
from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    UserRepository,
)
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName

_SECRET = "test-webhook-secret-for-dashboard"
_WEBHOOK_URL = "http://testserver"


@pytest.fixture
def dashboard_settings() -> Settings:
    """Settings with a webhook secret + URL so the dashboard is fully live."""
    return Settings(
        _env_file=None,
        environment="local",
        log_json=False,
        telegram_webhook_secret=_SECRET,
        telegram_webhook_url=_WEBHOOK_URL,
    )


@pytest.fixture
async def dashboard_client(
    dashboard_settings: Settings, db: Database
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings=dashboard_settings, db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=_WEBHOOK_URL) as ac:
        yield ac


async def _seed_user_with_pending_app(db: Database) -> str:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(42, 99)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.REMOTEOK,
            external_id="dash-1",
            title="Senior Backend Engineer",
            company="Acme Corp",
            description="d",
            url="https://example.com/apply/1",
            location="Remote",
        )
        await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job.id, status=ApplicationStatus.PENDING_APPROVAL
        )
    return str(user.id)


async def test_login_with_valid_token_sets_cookie_and_redirects(
    dashboard_client: AsyncClient, db: Database
) -> None:
    user_id = await _seed_user_with_pending_app(db)
    token = sign_token(__import__("uuid").UUID(user_id), MAGIC_LINK_TTL_SECONDS, _SECRET)

    r = await dashboard_client.get(f"/dashboard/login?token={token}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"
    assert SESSION_COOKIE_NAME in r.cookies


async def test_login_with_expired_token_renders_error(dashboard_client: AsyncClient) -> None:
    import uuid

    expired = sign_token(uuid.uuid4(), ttl_seconds=-60, webhook_secret=_SECRET)
    r = await dashboard_client.get(f"/dashboard/login?token={expired}", follow_redirects=False)
    assert r.status_code == 401
    assert "expired" in r.text.lower()


async def test_login_with_forged_token_renders_error(dashboard_client: AsyncClient) -> None:
    r = await dashboard_client.get("/dashboard/login?token=not.avalidtoken", follow_redirects=False)
    assert r.status_code == 401
    assert "invalid" in r.text.lower()


async def test_dashboard_requires_session_cookie(dashboard_client: AsyncClient) -> None:
    r = await dashboard_client.get("/dashboard")
    assert r.status_code == 401
    assert "required" in r.text.lower()


async def test_full_flow_login_then_view_dashboard(
    dashboard_client: AsyncClient, db: Database
) -> None:
    """Real user story: click magic-link → get redirected → dashboard renders their app."""
    user_id = await _seed_user_with_pending_app(db)
    token = sign_token(__import__("uuid").UUID(user_id), MAGIC_LINK_TTL_SECONDS, _SECRET)

    login = await dashboard_client.get(f"/dashboard/login?token={token}", follow_redirects=False)
    session_cookie = login.cookies[SESSION_COOKIE_NAME]

    page = await dashboard_client.get("/dashboard", cookies={SESSION_COOKIE_NAME: session_cookie})
    assert page.status_code == 200
    # The seeded application's title and company appear on the page.
    assert "Senior Backend Engineer" in page.text
    assert "Acme Corp" in page.text
    # Status + source badges render their labels (regression: the ORM returns a
    # plain str for these columns, so the row must coerce back to the enum or the
    # badges render blank).
    assert "pending approval" in page.text  # status label (underscore→space)
    assert "remoteok" in page.text  # source label
    # Header + polling script are present.
    assert "Cinch dashboard" in page.text
    assert "htmx.org" in page.text


async def test_fragment_endpoints_gated_by_cookie(
    dashboard_client: AsyncClient, db: Database
) -> None:
    await _seed_user_with_pending_app(db)
    # Without a cookie → 401.
    r = await dashboard_client.get("/dashboard/fragments/summary")
    assert r.status_code == 401
    r = await dashboard_client.get("/dashboard/fragments/applications")
    assert r.status_code == 401


async def test_fragment_summary_returns_only_the_tiles(
    dashboard_client: AsyncClient, db: Database
) -> None:
    """HTMX polling target must return the tiles fragment, not the whole page."""
    user_id = await _seed_user_with_pending_app(db)
    session = sign_token(__import__("uuid").UUID(user_id), SESSION_TTL_SECONDS, _SECRET)
    r = await dashboard_client.get(
        "/dashboard/fragments/summary", cookies={SESSION_COOKIE_NAME: session}
    )
    assert r.status_code == 200
    assert "Cinch dashboard" not in r.text  # not the full page
    assert "Awaiting you" in r.text  # tile label from _summary.html


async def test_logout_clears_cookie(dashboard_client: AsyncClient, db: Database) -> None:
    user_id = await _seed_user_with_pending_app(db)
    session = sign_token(__import__("uuid").UUID(user_id), SESSION_TTL_SECONDS, _SECRET)
    r = await dashboard_client.get("/dashboard/logout", cookies={SESSION_COOKIE_NAME: session})
    assert r.status_code == 401
    # Set-Cookie clears the session cookie (max-age=0 or explicit expiry in the past).
    set_cookie_header = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie_header


def test_issue_magic_link_builds_absolute_url(dashboard_settings: Settings) -> None:
    import uuid

    url = issue_magic_link(uuid.uuid4(), dashboard_settings)
    assert url.startswith(f"{_WEBHOOK_URL}/dashboard/login?token=")


def test_issue_magic_link_requires_webhook_url() -> None:
    import uuid

    with pytest.raises(RuntimeError, match="TELEGRAM_WEBHOOK_URL"):
        issue_magic_link(
            uuid.uuid4(),
            Settings(_env_file=None, telegram_webhook_secret=_SECRET),
        )
