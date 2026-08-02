"""Approve/Skip callback-data encoding round-trip + rejection of forged data."""

from __future__ import annotations

from uuid import uuid4

import pytest

from cinch.bot.keyboards import approve_skip_markup, parse_callback
from cinch.services.workflow import ApprovalDecision


def test_markup_roundtrips_both_decisions() -> None:
    application_id = uuid4()
    markup = approve_skip_markup(application_id)
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 2

    decisions: set[ApprovalDecision] = set()
    for button in buttons:
        data = button.callback_data
        assert isinstance(data, str)  # PTB types callback_data as object | None
        decision, parsed_id = parse_callback(data)
        decisions.add(decision)
        assert parsed_id == application_id
    assert decisions == {ApprovalDecision.APPROVE, ApprovalDecision.SKIP}


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
