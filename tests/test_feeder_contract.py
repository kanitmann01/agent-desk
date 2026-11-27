"""The feeder contract: one small collector protocol over the existing
Message record.

The return type is agentdesk.mail.core.Message, so the no-body
invariant is inherited instead of restated: a collector cannot hand the
feeder a body field because the record has none.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.feeder.contract import (
    MANUAL_CAUSE,
    MANUAL_COLLECTOR_NAME,
    MailCollector,
    UnavailableCollector,
)
from agentdesk.mail.core import Message, parse_eml


class FakeCollector:
    """One collector shaped the way the runner sees it."""

    name = "fake"

    def __init__(self, messages) -> None:
        """Hold the messages this fake hands back."""
        self.messages = list(messages)
        self.calls: list[tuple] = []

    def available(self) -> tuple[bool, str]:
        """The fake always runs."""
        return True, ""

    def collect(self, since, limit: int) -> list[Message]:
        """Record the call and hand back the held messages."""
        self.calls.append((since, limit))
        return list(self.messages)


def test_a_small_collector_satisfies_the_protocol():
    fake = FakeCollector([])
    assert isinstance(fake, MailCollector)
    ok, cause = fake.available()
    assert ok is True
    assert cause == ""


def test_the_protocol_hands_back_the_existing_message_type_only():
    message = parse_eml(
        "From: a@example.com\r\n"
        "To: employee@example.com\r\n"
        "Subject: North contract\r\n"
        "Date: Wed, 11 Nov 2026 12:00:00 GMT\r\n"
        "Message-ID: <a-1@example.com>\r\n"
        "\r\n"
        "SECRET-BODY-TOKEN that no feeder file may carry\r\n"
    )
    fake = FakeCollector([message])
    collected = fake.collect(None, 5)
    assert collected == [message]
    assert isinstance(collected[0], Message)
    assert not hasattr(collected[0], "body")


def test_the_unavailable_collector_always_stays_unavailable():
    collector = UnavailableCollector()
    assert isinstance(collector, MailCollector)
    assert collector.name == MANUAL_COLLECTOR_NAME
    ok, cause = collector.available()
    assert ok is False
    assert cause == MANUAL_CAUSE
    assert collector.collect(None, 10) == []


def test_the_manual_cause_names_save_as_in_one_plain_sentence():
    assert "Save as" in MANUAL_CAUSE
    assert "\n" not in MANUAL_CAUSE
    assert "\r" not in MANUAL_CAUSE
    assert MANUAL_CAUSE == MANUAL_CAUSE.strip()
    assert MANUAL_CAUSE.endswith(".")
