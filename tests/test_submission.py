"""SubmissionService orchestration + safety (no live browser/Telegram).

A FakeSubmitter supplies scripted outcomes; a recording notifier stands in for
Telegram. Covers: successful submit, the no-double-submit guarantee, the safe
handoffs (missing/invalid contact, submitter-reported NEEDS_HUMAN), FAILED being
terminal, crash containment, and the SUBMISSION_ENABLED scheduler gate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from telegram import Bot

from cinch.api.scheduler import run_submission_cycle
from cinch.bot.messages import format_submission_message
from cinch.core.config import Settings
from cinch.db.repositories import (
    ApplicationRepository,
    JobRepository,
    ResumeRepository,
    UserRepository,
)
from cinch.db.session import Database
from cinch.domain.enums import ApplicationStatus, JobSourceName
from cinch.domain.models import Application, Job
from cinch.providers.submit.base import Applicant, SubmissionOutcome, SubmissionResult
from cinch.providers.submit.fake import FakeSubmitter
from cinch.services.submission import SubmissionService

CHAT_ID = 99

MASTER: dict[str, object] = {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1-555-0100",
    "summary": "Engineer",
    "skills": ["Python"],
    "experiences": [
        {"company": "Acme", "title": "Backend Engineer", "start": "2020", "bullets": ["Built X"]}
    ],
    "education": [],
}
MASTER_NO_EMAIL: dict[str, object] = {"name": "Jane Doe", "skills": ["Python"], "experiences": []}


class RecordingSubmissionNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[int, UUID, SubmissionOutcome, str]] = []

    async def notify_submission(
        self, *, chat_id: int, job: Job, outcome: SubmissionOutcome, detail: str
    ) -> None:
        self.sent.append((chat_id, job.id, outcome, detail))


class RaisingSubmitter:
    async def submit(
        self, *, apply_url: str, applicant: Applicant, resume_html: str
    ) -> SubmissionResult:
        raise RuntimeError("unexpected browser crash")


class RaisingNotifier:
    async def notify_submission(
        self, *, chat_id: int, job: Job, outcome: SubmissionOutcome, detail: str
    ) -> None:
        raise RuntimeError("telegram unreachable")


async def _seed_approved(
    db: Database, *, master_content: dict[str, object] | None, uid: int = 42
) -> UUID:
    """Create a user (+optional master resume), a job, and an APPROVED application."""
    async with db.session() as session:
        user = await UserRepository(session).get_or_create(uid, CHAT_ID)
        if master_content is not None:
            await ResumeRepository(session).set_master(user.id, master_content)
        job = await JobRepository(session).get_or_create(
            source=JobSourceName.ADZUNA,
            external_id=f"ext-{uid}",
            title="Backend Engineer",
            company="Acme",
            description="Build things.",
            url="https://example.com/apply/1",
            location="Remote",
        )
        application = await ApplicationRepository(session).get_or_create(
            user_id=user.id, job_id=job.id, status=ApplicationStatus.APPROVED
        )
    return application.id


async def _get_app(db: Database, application_id: UUID) -> Application:
    async with db.session() as session:
        application = await ApplicationRepository(session).get(application_id)
    assert application is not None
    return application


def _submitted() -> FakeSubmitter:
    return FakeSubmitter(default=SubmissionResult(SubmissionOutcome.SUBMITTED, "submitted"))


async def test_submits_approved_application(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=MASTER)
    submitter, notifier = _submitted(), RecordingSubmissionNotifier()

    summary = await SubmissionService(db, submitter=submitter, notifier=notifier).run()

    assert (summary.approved, summary.submitted) == (1, 1)
    assert len(submitter.calls) == 1
    url, applicant, html = submitter.calls[0]
    assert "example.com/apply/1" in url
    assert applicant.name == "Jane Doe"
    assert applicant.email == "jane@example.com"
    assert "Jane Doe" in html and "Built X" in html  # the real, rendered resume
    assert [outcome for _, _, outcome, _ in notifier.sent] == [SubmissionOutcome.SUBMITTED]

    app = await _get_app(db, app_id)
    assert app.status is ApplicationStatus.SUBMITTED
    assert app.submitted_at is not None
    assert app.submission_detail == "submitted"


async def test_no_double_submit_second_cycle_is_noop(db: Database) -> None:
    await _seed_approved(db, master_content=MASTER)
    submitter, notifier = _submitted(), RecordingSubmissionNotifier()
    service = SubmissionService(db, submitter=submitter, notifier=notifier)

    await service.run()
    summary2 = await service.run()

    assert summary2.approved == 0 and summary2.submitted == 0
    assert len(submitter.calls) == 1  # the same application is never submitted twice


async def test_missing_contact_hands_back_without_submitting(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=MASTER_NO_EMAIL)
    submitter, notifier = _submitted(), RecordingSubmissionNotifier()

    summary = await SubmissionService(db, submitter=submitter, notifier=notifier).run()

    assert summary.needs_human == 1 and summary.submitted == 0
    assert submitter.calls == []  # never attempts a blind submit
    app = await _get_app(db, app_id)
    assert app.status is ApplicationStatus.NEEDS_HUMAN
    assert app.submitted_at is None
    assert [outcome for _, _, outcome, _ in notifier.sent] == [SubmissionOutcome.NEEDS_HUMAN]


async def test_no_master_resume_hands_back(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=None)
    submitter, notifier = _submitted(), RecordingSubmissionNotifier()

    summary = await SubmissionService(db, submitter=submitter, notifier=notifier).run()

    assert summary.needs_human == 1
    assert submitter.calls == []
    assert (await _get_app(db, app_id)).status is ApplicationStatus.NEEDS_HUMAN


async def test_invalid_master_resume_hands_back(db: Database) -> None:
    app_id = await _seed_approved(db, master_content={"skills": "not-a-list"})
    submitter, notifier = _submitted(), RecordingSubmissionNotifier()

    summary = await SubmissionService(db, submitter=submitter, notifier=notifier).run()

    assert summary.needs_human == 1
    assert submitter.calls == []
    assert (await _get_app(db, app_id)).status is ApplicationStatus.NEEDS_HUMAN


async def test_submitter_needs_human_is_recorded(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=MASTER)
    submitter = FakeSubmitter([SubmissionResult(SubmissionOutcome.NEEDS_HUMAN, "sign-in required")])
    notifier = RecordingSubmissionNotifier()

    summary = await SubmissionService(db, submitter=submitter, notifier=notifier).run()

    assert summary.needs_human == 1
    assert len(submitter.calls) == 1
    app = await _get_app(db, app_id)
    assert app.status is ApplicationStatus.NEEDS_HUMAN
    assert app.submission_detail == "sign-in required"
    assert app.submitted_at is None


async def test_failed_outcome_is_terminal_and_not_retried(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=MASTER)
    submitter = FakeSubmitter([SubmissionResult(SubmissionOutcome.FAILED, "timed out")])
    service = SubmissionService(db, submitter=submitter, notifier=RecordingSubmissionNotifier())

    summary = await service.run()
    assert summary.failed == 1
    assert (await _get_app(db, app_id)).status is ApplicationStatus.FAILED

    summary2 = await service.run()  # FAILED is terminal — a retry could double-apply
    assert summary2.approved == 0
    assert len(submitter.calls) == 1


async def test_unexpected_submitter_error_is_contained(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=MASTER)

    summary = await SubmissionService(
        db, submitter=RaisingSubmitter(), notifier=RecordingSubmissionNotifier()
    ).run()

    assert summary.failed == 1
    # Claimed out of APPROVED before the crash, so it is never re-picked / re-submitted.
    assert (await _get_app(db, app_id)).status is ApplicationStatus.FAILED


async def test_notify_failure_does_not_prevent_recording(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=MASTER)

    summary = await SubmissionService(db, submitter=_submitted(), notifier=RaisingNotifier()).run()

    assert summary.submitted == 1  # outcome durably recorded despite the notify raising
    assert (await _get_app(db, app_id)).status is ApplicationStatus.SUBMITTED


async def test_claim_can_only_succeed_once(db: Database) -> None:
    app_id = await _seed_approved(db, master_content=MASTER)
    async with db.session() as session:
        first = await ApplicationRepository(session).claim_for_submission(app_id)
    async with db.session() as session:
        second = await ApplicationRepository(session).claim_for_submission(app_id)
    assert first is not None and first.status is ApplicationStatus.FAILED
    assert second is None  # no longer APPROVED — cannot be claimed again


async def test_run_submission_cycle_disabled_is_noop(db: Database) -> None:
    """SUBMISSION_ENABLED off ⇒ the cycle returns immediately and builds no submitter."""
    summary = await run_submission_cycle(db, Settings(_env_file=None), cast(Bot, object()))
    assert summary.approved == 0 and summary.submitted == 0


def test_submission_message_variants() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    job = Job(
        id=uuid4(),
        source=JobSourceName.ADZUNA,
        external_id="e1",
        title="Backend <Eng>",
        company="Acme & Co",
        location="Remote",
        description="d",
        url="https://example.com/apply",
        discovered_at=now,
        created_at=now,
        updated_at=now,
    )
    submitted = format_submission_message(job, SubmissionOutcome.SUBMITTED, "submitted")
    needs = format_submission_message(job, SubmissionOutcome.NEEDS_HUMAN, "sign-in required")
    failed = format_submission_message(job, SubmissionOutcome.FAILED, "timed out")

    assert "Applied" in submitted and "example.com/apply" in submitted
    assert "Needs you" in needs and "sign-in required" in needs
    assert "Couldn't apply" in failed and "timed out" in failed
    # Job fields are HTML-escaped before reaching Telegram's HTML parse mode.
    assert "Backend &lt;Eng&gt;" in submitted
    assert "Acme &amp; Co" in submitted
