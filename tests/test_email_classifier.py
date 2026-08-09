"""EmailClassifier: LLM output → bucket + company match, no state changes here."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cinch.core.config import Settings
from cinch.domain.enums import ApplicationStatus
from cinch.domain.models import Application
from cinch.providers.llm.fake import FakeLLMProvider
from cinch.services.email_classifier import (
    EmailClassification,
    EmailClassifier,
    EmailPayload,
    _best_match,
    _sender_company_hint,
)


def _now() -> datetime:
    return datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _app(company_key: str, status: ApplicationStatus) -> Application:
    return Application(
        id=uuid4(),
        user_id=uuid4(),
        job_id=uuid4(),
        status=status,
        created_at=_now(),
        updated_at=_now(),
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


def _classifier(response_json: str) -> EmailClassifier:
    """Build a classifier backed by a scripted LLM response."""
    return EmailClassifier(FakeLLMProvider([response_json]), _settings())


def _payload(**overrides: object) -> EmailPayload:
    defaults = {
        "from_email": "jobs@acme.com",
        "from_name": "Acme Recruiting",
        "subject": "Next steps for your application",
        "body_text": "We'd like to schedule a phone screen for the Backend role.",
        "received_at": _now(),
    }
    return EmailPayload(**{**defaults, **overrides})


async def test_interview_invited_matched_by_llm_company_hint() -> None:
    """LLM says interview_invited + names Acme; matches the Acme application."""
    acme_app = _app("Acme Corp", ApplicationStatus.SUBMITTED)
    beta_app = _app("Beta Inc", ApplicationStatus.SUBMITTED)
    jobs_by_id = {str(acme_app.job_id): "Acme Corp", str(beta_app.job_id): "Beta Inc"}

    classifier = _classifier(
        '{"classification": "interview_invited", '
        '"company_hint": "Acme", '
        '"summary": "Phone screen requested."}'
    )
    result = await classifier.classify(
        _payload(), candidates=[acme_app, beta_app], jobs_by_id=jobs_by_id
    )

    assert result.classification is EmailClassification.INTERVIEW_INVITED
    assert result.matched_application is not None
    assert result.matched_application.id == acme_app.id
    assert result.new_status is ApplicationStatus.INTERVIEW_INVITED
    assert result.summary == "Phone screen requested."


async def test_rejection_maps_to_rejected_status() -> None:
    acme_app = _app("Acme Corp", ApplicationStatus.SUBMITTED)
    jobs_by_id = {str(acme_app.job_id): "Acme Corp"}
    classifier = _classifier(
        '{"classification": "rejection", "company_hint": "Acme", "summary": "Not moving forward."}'
    )
    result = await classifier.classify(_payload(), candidates=[acme_app], jobs_by_id=jobs_by_id)
    assert result.new_status is ApplicationStatus.REJECTED


async def test_offer_maps_to_offered() -> None:
    acme_app = _app("Acme Corp", ApplicationStatus.INTERVIEW_SCHEDULED)
    classifier = _classifier(
        '{"classification": "offer", "company_hint": "Acme", "summary": "Offer letter attached."}'
    )
    result = await classifier.classify(
        _payload(),
        candidates=[acme_app],
        jobs_by_id={str(acme_app.job_id): "Acme Corp"},
    )
    assert result.new_status is ApplicationStatus.OFFERED
    assert result.matched_application is not None


async def test_acknowledgement_is_no_action_even_when_matched() -> None:
    """'We received your application' auto-replies must not advance state."""
    acme_app = _app("Acme Corp", ApplicationStatus.SUBMITTED)
    classifier = _classifier(
        '{"classification": "acknowledgement", "company_hint": "Acme", "summary": "Auto-reply."}'
    )
    result = await classifier.classify(
        _payload(),
        candidates=[acme_app],
        jobs_by_id={str(acme_app.job_id): "Acme Corp"},
    )
    assert result.classification is EmailClassification.ACKNOWLEDGEMENT
    assert result.new_status is None  # even though we matched, no status change


async def test_no_matching_application_is_a_no_op() -> None:
    beta_app = _app("Beta Inc", ApplicationStatus.SUBMITTED)
    classifier = _classifier(
        '{"classification": "interview_invited", "company_hint": "Zeta", "summary": "..."}'
    )
    result = await classifier.classify(
        _payload(), candidates=[beta_app], jobs_by_id={str(beta_app.job_id): "Beta Inc"}
    )
    assert result.matched_application is None
    assert result.new_status is None
    assert "matched" in result.reason  # human-readable explanation


async def test_missing_llm_company_hint_falls_back_to_sender_domain() -> None:
    """LLM returns null company_hint → domain of 'jobs@acme.com' rescues the match."""
    acme_app = _app("Acme Corp", ApplicationStatus.SUBMITTED)
    classifier = _classifier(
        '{"classification": "interview_invited", "company_hint": null, "summary": "Phone screen"}'
    )
    result = await classifier.classify(
        _payload(from_email="jobs@acme.com"),
        candidates=[acme_app],
        jobs_by_id={str(acme_app.job_id): "Acme Corp"},
    )
    assert result.matched_application is not None
    assert result.matched_application.id == acme_app.id


async def test_malformed_llm_output_becomes_a_no_op() -> None:
    """A garbage LLM response never crashes the pipeline — it just does nothing."""
    classifier = _classifier("not-json-at-all")
    result = await classifier.classify(_payload(), candidates=[], jobs_by_id={})
    assert result.matched_application is None
    assert result.new_status is None


def test_sender_company_hint_skips_webmail_domains() -> None:
    """gmail/yahoo/outlook say nothing about the employer — return None."""
    assert _sender_company_hint("random.name@gmail.com") is None
    assert _sender_company_hint("hr@acme.com") == "acme"
    assert _sender_company_hint("careers@boards.greenhouse.io") == "greenhouse"


def test_best_match_requires_reasonable_similarity() -> None:
    """A completely unrelated company name must not match."""
    a1 = _app("Acme Corp", ApplicationStatus.SUBMITTED)
    a2 = _app("Beta Inc", ApplicationStatus.SUBMITTED)
    jobs_by_id = {str(a1.job_id): "Acme Corp", str(a2.job_id): "Beta Inc"}
    # 'zeta' matches neither well enough (< 0.6 similarity) → no match.
    assert _best_match("zeta", [a1, a2], jobs_by_id) is None
    # 'acme' matches Acme Corp exactly by substring.
    matched = _best_match("acme", [a1, a2], jobs_by_id)
    assert matched is not None and matched.id == a1.id


@pytest.mark.parametrize(
    "classification_str,expected_status",
    [
        ("interview_invited", ApplicationStatus.INTERVIEW_INVITED),
        ("interview_scheduled", ApplicationStatus.INTERVIEW_SCHEDULED),
        ("offer", ApplicationStatus.OFFERED),
        ("rejection", ApplicationStatus.REJECTED),
    ],
)
async def test_all_action_classifications_map_correctly(
    classification_str: str, expected_status: ApplicationStatus
) -> None:
    acme_app = _app("Acme Corp", ApplicationStatus.SUBMITTED)
    classifier = _classifier(
        f'{{"classification": "{classification_str}", "company_hint": "Acme", "summary": "x"}}'
    )
    result = await classifier.classify(
        _payload(),
        candidates=[acme_app],
        jobs_by_id={str(acme_app.job_id): "Acme Corp"},
    )
    assert result.new_status is expected_status


# --- Phase 13: pre-LLM sanity filter -----------------------------------------


async def test_noise_email_is_filtered_without_an_llm_call() -> None:
    """A job-alert digest is dropped before the LLM — provider records zero calls."""
    provider = FakeLLMProvider([])  # no scripted responses: any call would raise
    classifier = EmailClassifier(provider, Settings(_env_file=None))
    result = await classifier.classify(
        _payload(subject="Jobs for you this week", body_text="New jobs matching your search."),
        candidates=[],
        jobs_by_id={},
    )
    assert provider.calls == []  # the LLM was never invoked
    assert result.new_status is None
    assert result.matched_application is None
    assert result.reason == "filtered: job_alert"


async def test_real_interview_email_is_not_filtered() -> None:
    """A genuine interview email still reaches the LLM and advances (filter on)."""
    acme_app = _app("Acme Corp", ApplicationStatus.SUBMITTED)
    provider = FakeLLMProvider(
        ['{"classification": "interview_invited", "company_hint": "Acme", "summary": "Screen."}']
    )
    classifier = EmailClassifier(provider, Settings(_env_file=None))
    result = await classifier.classify(
        _payload(subject="Interview invitation for the Backend role"),
        candidates=[acme_app],
        jobs_by_id={str(acme_app.job_id): "Acme Corp"},
    )
    assert len(provider.calls) == 1  # the LLM WAS invoked
    assert result.new_status is ApplicationStatus.INTERVIEW_INVITED


async def test_filter_disabled_sends_noise_to_the_llm() -> None:
    """With the gate off, even a job-alert reaches the LLM (Phase 11 behaviour)."""
    provider = FakeLLMProvider(
        ['{"classification": "other", "company_hint": null, "summary": "n/a"}']
    )
    settings = Settings(_env_file=None, email_sanity_filter_enabled=False)
    classifier = EmailClassifier(provider, settings)
    await classifier.classify(
        _payload(subject="Jobs for you this week"), candidates=[], jobs_by_id={}
    )
    assert len(provider.calls) == 1  # gate disabled → LLM invoked despite the noise
