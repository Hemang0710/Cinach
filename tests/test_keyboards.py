"""Approve/Skip callback-data encoding round-trip + rejection of forged data."""

from __future__ import annotations

from uuid import uuid4

import pytest

from cinch.bot.keyboards import (
    accept_markup,
    approve_skip_markup,
    parse_accept_callback,
    parse_callback,
)
from cinch.services.workflow import ApprovalDecision


def test_markup_roundtrips_both_decisions() -> None:
    application_id = uuid4()
    markup = approve_skip_markup(application_id, "Backend Engineer", "Remote")
    # Only the callback buttons round-trip; the handoff row is URL buttons (no data).
    callback_buttons = [
        b for row in markup.inline_keyboard for b in row if b.callback_data is not None
    ]
    assert len(callback_buttons) == 2

    decisions: set[ApprovalDecision] = set()
    for button in callback_buttons:
        data = button.callback_data
        assert isinstance(data, str)  # PTB types callback_data as object | None
        decision, parsed_id = parse_callback(data)
        decisions.add(decision)
        assert parsed_id == application_id
    assert decisions == {ApprovalDecision.APPROVE, ApprovalDecision.SKIP}


def test_apply_handoff_row_links_to_linkedin_and_indeed() -> None:
    """The handoff buttons are URL buttons pointing at pre-filled searches — no
    callback_data (nothing to automate), title + location URL-encoded into the query."""
    markup = approve_skip_markup(uuid4(), "Staff Data Engineer", "New York, NY")
    urls = [b.url for row in markup.inline_keyboard for b in row if b.url is not None]
    assert any("linkedin.com/jobs/search" in u for u in urls)
    assert any("indeed.com/jobs" in u for u in urls)
    # Spaces are encoded (quote_plus), so the query is a valid search URL.
    assert any("keywords=Staff+Data+Engineer" in u and "location=New+York" in u for u in urls)
    assert any("q=Staff+Data+Engineer" in u and "l=New+York" in u for u in urls)


def test_apply_handoff_row_omits_location_when_absent() -> None:
    """A job with no location still yields valid search links (keyword only)."""
    markup = approve_skip_markup(uuid4(), "SRE")
    urls = [b.url for row in markup.inline_keyboard for b in row if b.url is not None]
    assert len(urls) == 2
    assert all("location=" not in u and "&l=" not in u for u in urls)


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "approve",  # no separator
        "approve:not-a-uuid",  # bad uuid
        f"delete:{uuid4()}",  # unknown decision
        f"{uuid4()}",  # uuid only, no decision
    ],
)
def test_malformed_callback_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_callback(bad)


def test_accept_markup_roundtrips() -> None:
    application_id = uuid4()
    markup = accept_markup(application_id)
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 1
    data = buttons[0].callback_data
    assert isinstance(data, str)
    assert parse_accept_callback(data) == application_id


def test_parse_accept_ignores_non_accept_actions() -> None:
    # Approve/Skip data is not an accept press → None (so the router falls through).
    assert parse_accept_callback(f"approve:{uuid4()}") is None
    assert parse_accept_callback(f"skip:{uuid4()}") is None
    assert parse_accept_callback("garbage") is None


def test_parse_accept_rejects_forged_uuid() -> None:
    with pytest.raises(ValueError):
        parse_accept_callback("accept:not-a-uuid")
