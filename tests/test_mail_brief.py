"""The Outlook Brief rule set: digest, top message, reply starters."""

from datetime import datetime, timezone

from nexuusbot.mail.brief import (
    age_words,
    brief,
    digest_rows,
    reply_starters,
    top_message,
)
from nexuusbot.mail.core import Message, parse_eml, with_threads


def _msg(message_id, subject, sender, ts, to="employee@example.com",
         cc="", importance="", in_reply_to=""):
    return Message(id=message_id, in_reply_to=in_reply_to, sender=sender,
                   to=to, cc=cc, subject=subject, date_ts=ts,
                   importance=importance)


NOW = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc).timestamp()


def test_digest_rows_carry_the_thread_sender_count_and_age():
    messages = with_threads([
        _msg("<1@x>", "Q4 pipeline review", "Priya <priya@northwind.example>",
             NOW - 3 * 3600),
        _msg("<2@x>", "Re: Q4 pipeline review", "employee@example.com",
             NOW - 2 * 3600, in_reply_to="<1@x>"),
        _msg("<3@x>", "Lunch on Friday?", "Ana <ana@northwind.example>",
             NOW - 30 * 60),
    ])
    rows = digest_rows(messages, NOW)
    assert [row["primary"] for row in rows] == [
        "Lunch on Friday?", "Q4 pipeline review"]
    assert rows[1]["secondary"] == "employee@example.com"
    assert rows[1]["meta"] == "2 msg · 2 h ago"
    assert rows[0]["secondary"] == "Ana"
    assert rows[0]["meta"] == "1 msg · 30 min ago"


def test_top_message_prefers_high_importance_action_mail_over_quiet_mail():
    messages = with_threads([
        _msg("<1@x>", "Q4 pipeline review - need your numbers by EOD",
             "Priya <priya@northwind.example>", NOW - 2 * 3600,
             importance="high"),
        _msg("<2@x>", "Contract renewal", "Legal <legal@northwind.example>",
             NOW - 3 * 3600),
        _msg("<3@x>", "Lunch on Friday?", "Ana <ana@northwind.example>",
             NOW - 20 * 3600),
    ])
    top = top_message(messages, NOW, self_address="employee@example.com")
    assert top is not None
    assert top.message.id == "<1@x>"
    assert "high importance" in top.why
    assert "eod" in top.why
    assert "addressed to you" in top.why


def test_a_message_older_than_the_window_is_not_named_top():
    messages = with_threads([
        _msg("<1@x>", "Q4 pricing", "a@example.com", NOW - 5 * 86400),
    ])
    assert top_message(messages, NOW) is None
    data = brief(messages, NOW)
    assert data["topEmailSubject"] == "No recent message"
    assert data["replyOptions"] == []


def test_reply_starters_are_three_and_never_claim_to_have_read_a_body():
    top = top_message(with_threads([
        _msg("<1@x>", "Can you approve the Q4 numbers?",
             "Priya <priya@northwind.example>", NOW - 3600),
    ]), NOW)
    starters = reply_starters(top)
    assert len(starters) == 3
    assert [row["secondary"] for row in starters] == ["Direct", "Clarify", "Brief"]
    assert starters[0]["primary"].startswith("Good question.")
    assert "Can you approve the Q4 numbers?" in starters[0]["primary"]
    assert all("body" not in row["primary"].lower() for row in starters)


def test_age_words_never_invents_a_time():
    assert age_words(5) == "just now"
    assert age_words(90) == "1 min ago"
    assert age_words(3 * 3600) == "3 h ago"
    assert age_words(2 * 86400) == "2 d ago"


def test_parse_eml_reads_importance_without_reading_the_body():
    raw = "\r\n".join([
        "From: Priya <priya@northwind.example>",
        "To: employee@example.com",
        "Subject: Q4 pipeline review",
        "Date: Tue, 17 Nov 2026 20:40:00 +0000",
        "Message-ID: <1@x>",
        "Importance: high",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "",
        "a body that must never reach a card",
    ])
    message = parse_eml(raw)
    assert message.importance == "high"
    assert not hasattr(message, "body")
