"""Phase 13 — is_noise_email: the deterministic pre-LLM noise gate.

High-precision by design: noise categories are dropped, but anything that could
plausibly advance an application must pass through (return None).
"""

from __future__ import annotations

import pytest

from cinch.services.email_classifier import EmailPayload
from cinch.services.email_filter import is_noise_email


def _payload(**overrides: object) -> EmailPayload:
    defaults = {
        "from_email": "recruiter@acme.com",
        "from_name": "Acme Recruiting",
        "subject": "Next steps for your application",
        "body_text": "We'd like to schedule a phone screen.",
    }
    return EmailPayload(**{**defaults, **overrides})


# --- noise is filtered -------------------------------------------------------


@pytest.mark.parametrize(
    "subject",
    [
        "Jobs for you this week",
        "5 new jobs matching your search",
        "Recommended jobs at top companies",
        "Your weekly job alert",
        "New opportunities for you",
    ],
)
def test_job_alert_subjects_are_filtered(subject: str) -> None:
    assert is_noise_email(_payload(subject=subject)) == "job_alert"


def test_job_alert_detected_in_body_too() -> None:
    payload = _payload(subject="Hello", body_text="Here are new jobs matching your profile.")
    assert is_noise_email(payload) == "job_alert"


def test_newsletter_footer_is_filtered() -> None:
    body = (
        "Big product news this month!\n\n"
        "You are receiving this because you signed up.\n"
        "Manage your preferences or unsubscribe here."
    )
    assert is_noise_email(_payload(subject="Company Monthly", body_text=body)) == "newsletter"


@pytest.mark.parametrize(
    "from_email",
    [
        "newsletter@company.com",
        "digest@updates.company.com",
        "marketing@company.com",
        "promotions@shop.com",
        "mailer@company.com",
        "bounces@company.com",
    ],
)
def test_bulk_sender_mailboxes_are_filtered(from_email: str) -> None:
    payload = _payload(from_email=from_email, subject="This week at Company")
    assert is_noise_email(payload) == "bulk_sender"


# --- real / ambiguous mail passes through ------------------------------------


@pytest.mark.parametrize(
    "subject",
    [
        "Next steps for your application",
        "Interview invitation — Backend Engineer",
        "We'd like to extend you an offer",
        "Update on your application (unfortunately)",
    ],
)
def test_real_hiring_emails_are_not_filtered(subject: str) -> None:
    assert is_noise_email(_payload(subject=subject)) is None


def test_bulk_sender_is_rescued_by_advancing_subject() -> None:
    # An offer that happens to come from a bulk-looking mailbox must NOT be dropped.
    payload = _payload(from_email="mailer@company.com", subject="Your offer letter is ready")
    assert is_noise_email(payload) is None


def test_lone_unsubscribe_is_not_a_newsletter() -> None:
    # A single "unsubscribe" in an otherwise normal email is too weak to filter.
    body = "Thanks for applying! Reply STOP or unsubscribe if you'd prefer no updates."
    assert is_noise_email(_payload(subject="Application received", body_text=body)) is None


def test_noreply_sender_alone_is_not_filtered() -> None:
    # Lever/Greenhouse interview invites use no-reply@ — must pass through.
    payload = _payload(
        from_email="no-reply@hire.lever.co",
        subject="Interview invitation",
        body_text="Please pick a time for your interview.",
    )
    assert is_noise_email(payload) is None
