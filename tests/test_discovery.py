"""DiscoveryService orchestration + idempotency (no live Adzuna/LLM/Telegram).

FakeJobSource supplies postings; a real TailoringService runs against a scripted
FakeLLMProvider; a recording notifier stands in for Telegram.
"""

from __future__ import annotations

from uuid import UUID

from cinch.core.config import Settings
from cinch.db.repositories import ApplicationRepository, ResumeRepository, UserRepository
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus
from cinch.domain.models import Job, TailoringResult
from cinch.domain.resume import MasterResume
from cinch.providers.jobs.base import RawJob
from cinch.providers.jobs.fake import FakeJobSource
from cinch.providers.llm.fake import FakeLLMProvider
from cinch.services.discovery import DiscoveryService, query_from_resume
from cinch.services.tailoring import TailoringService

CHAT_ID = 99
MASTER_CONTENT: dict[str, object] = {
    "summary": "Engineer",
    "skills": ["Python"],
    "experiences": [
        {"company": "Acme", "title": "Backend Engineer", "start": "2020", "bullets": ["Built X"]}
    ],
    "education": [],
}
_EMPTY_TAILORING = '{"bullets": []}'


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[int, UUID]] = []

    async def notify(
        self, *, chat_id: int, job: Job, tailoring: TailoringResult, application_id: UUID
    ) -> None:
        self.sent.append((chat_id, application_id))


def _raw(external_id: str) -> RawJob:
    return RawJob(
        external_id=external_id,
        title="Backend Engineer",
        company="Acme",
        description="Build async services.",
        url=f"https://example.com/{external_id}",
        location="Remote",
    )


def _service(
    session: object, *, job_source: FakeJobSource, llm: FakeLLMProvider, notifier: RecordingNotifier
) -> DiscoveryService:
    settings = Settings(_env_file=None)
    return DiscoveryService(
        session,  # type: ignore[arg-type]
        job_source=job_source,
        tailoring=TailoringService(llm, settings),
        notifier=notifier,
        settings=settings,
    )


async def _seed_user_with_master(db: Database, *, telegram_user_id: int) -> None:
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(telegram_user_id, CHAT_ID)
        await ResumeRepository(session).set_master(user.id, MASTER_CONTENT)


def test_query_from_resume() -> None:
    assert query_from_resume(MasterResume(), where=None, results=5) is None
    master = MasterResume.model_validate(MASTER_CONTENT)
    query = query_from_resume(master, where="Remote", results=3)
    assert query is not None
    assert query.what == "Backend Engineer"
    assert query.where == "Remote"
    assert query.results == 3


async def test_cycle_discovers_tailors_notifies_then_is_idempotent(db: Database) -> None:
    await _seed_user_with_master(db, telegram_user_id=42)
    job_source = FakeJobSource([_raw("a1"), _raw("a2")])
    llm = FakeLLMProvider(responses=[_EMPTY_TAILORING, _EMPTY_TAILORING])
    notifier = RecordingNotifier()

    # First cycle: two jobs discovered → tailored → notified.
    async with db.session() as session:
        summary = await _service(session, job_source=job_source, llm=llm, notifier=notifier).run()
    assert (summary.discovered, summary.notified) == (2, 2)
    assert len(notifier.sent) == 2

    async with db.session() as session:
        apps = await ApplicationRepository(session).list()
    assert len(apps) == 2
    assert all(a.status is ApplicationStatus.PENDING_APPROVAL for a in apps)

    # Second cycle over the SAME postings: nothing new is created or sent.
    async with db.session() as session:
        summary2 = await _service(session, job_source=job_source, llm=llm, notifier=notifier).run()
    assert summary2.notified == 0
    assert summary2.skipped_existing == 2
    assert len(notifier.sent) == 2  # unchanged — no double-notify

    async with db.session() as session:
        apps_after = await ApplicationRepository(session).list()
    assert len(apps_after) == 2  # no duplicate applications


async def test_user_without_master_resume_is_skipped(db: Database) -> None:
    async with db.session() as session:
        await UserRepository(session).get_or_create(7, CHAT_ID)  # no master resume
    job_source = FakeJobSource([_raw("a1")])
    llm = FakeLLMProvider(responses=[])
    notifier = RecordingNotifier()

    async with db.session() as session:
        summary = await _service(session, job_source=job_source, llm=llm, notifier=notifier).run()

    assert summary.skipped_no_resume == 1
    assert summary.notified == 0
    assert notifier.sent == []
    assert job_source.calls == []  # never even searched
