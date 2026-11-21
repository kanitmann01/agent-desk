"""Header-only mail parsing, threading and the digest/follow-up sets.

The DLP invariant is the headline: the parsed record has no body field,
and no test or code path places a message body into any prompt. The
donor (packages/host/src/mail/mail.ts) kept bodies on the message and
read them into model calls; this port is metadata-only by construction.
"""

import dataclasses
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.mail.core import (
    DAY_S,
    DIGEST_HOURS,
    FOLLOW_UP_DAYS,
    Message,
    digest_details,
    follow_ups,
    parse_eml,
    read_eml_folder,
    recent_threads,
    reply_recipients,
    reply_subject,
    read_eml_folder_reported,
    format_header_ts,
    thread_of,
    with_threads,
    write_reply,
)

FIXTURES = ROOT / "tests" / "fixtures" / "mail"

# The fixture mailbox's user: the address the tests configure as self.
MAIL_USER = "employee@example.com"

# The donor's frozen sample moment: 2026-11-11T12:00:00Z.
SAMPLE_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc).timestamp()


def eml(
    message_id: str,
    subject: str,
    sender: str,
    to: str,
    date: str,
    in_reply_to: str = "",
    cc: str = "",
    body: str = "a harmless placeholder body line",
) -> str:
    """One .eml text, in the donor fixtures' shape."""
    lines = [
        f"From: {sender}",
        f"To: {to}",
        f"Subject: {subject}",
        f"Date: {date}",
        f"Message-ID: {message_id}",
    ]
    if cc:
        lines.append(f"Cc: {cc}")
    if in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    lines += ["MIME-Version: 1.0", "Content-Type: text/plain; charset=utf-8", "", body]
    return "\r\n".join(lines) + "\r\n"


# -- slice 1: parsing reads the named headers only ------------------------


def test_parse_reads_the_named_headers():
    text = eml(
        "<a-1@example.com>", "North contract", "a@example.com",
        "employee@example.com", "Tue, 28 Oct 2026 12:00:00 GMT",
        cc="b@example.com",
    )
    message = parse_eml(text)
    assert message.id == "<a-1@example.com>"
    assert message.sender == "a@example.com"
    assert message.to == "employee@example.com"
    assert message.cc == "b@example.com"
    assert message.subject == "North contract"
    assert message.in_reply_to == ""
    parsed = datetime.fromtimestamp(message.date_ts, tz=timezone.utc)
    assert parsed == datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def test_parsed_record_has_no_body_field_at_all():
    text = eml(
        "<a-1@example.com>", "North contract", "a@example.com",
        "employee@example.com", "Tue, 28 Oct 2026 12:00:00 GMT",
        body="SECRET-BODY-TEXT that must never be stored or sent",
    )
    message = parse_eml(text)
    assert not hasattr(message, "body")
    # No field of the record carries any part of the body, either.
    assert "SECRET-BODY-TEXT" not in str(dataclasses.asdict(message))


def test_parse_discards_the_body_even_for_fixture_files():
    message = parse_eml((FIXTURES / "north-1example.com.eml").read_text(encoding="utf-8"))
    assert message.id == "<north-1@example.com>"
    assert message.subject == "North contract"
    assert not hasattr(message, "body")
    # The fixture's own body line ("North contract note 1") survives nowhere.
    assert "note 1" not in str(dataclasses.asdict(message))


def test_parse_survives_missing_headers_and_bad_dates():
    message = parse_eml("From: a@example.com\r\n\r\nignored body\r\n")
    assert message.id == ""
    assert message.subject == ""
    assert message.date_ts == 0.0
    assert message.cc == ""


def test_parse_decodes_encoded_words_in_subjects():
    text = eml(
        "<enc-1@example.com>", None, "a@example.com",
        "employee@example.com", "Tue, 28 Oct 2026 12:00:00 GMT",
    ).replace("Subject: None", "Subject: =?utf-8?q?Caf=C3=A9_plan?=")
    message = parse_eml(text)
    assert message.subject == "Café plan"


def test_read_folder_reads_only_eml_files_sorted_by_date(tmp_path):
    # Written as bytes: .eml files are CRLF, and a text-mode write would
    # translate the newlines again on Windows.
    (tmp_path / "b.eml").write_bytes(eml(
        "<b-1@example.com>", "Second", "b@example.com", MAIL_USER,
        "Wed, 29 Oct 2026 12:00:00 GMT").encode("utf-8"))
    (tmp_path / "a.eml").write_bytes(eml(
        "<a-1@example.com>", "First", "a@example.com", MAIL_USER,
        "Tue, 28 Oct 2026 12:00:00 GMT").encode("utf-8"))
    (tmp_path / "notes.txt").write_text("not mail", encoding="utf-8")
    messages = read_eml_folder(tmp_path)
    assert [m.id for m in messages] == ["<a-1@example.com>", "<b-1@example.com>"]
    assert all(not hasattr(m, "body") for m in messages)


def test_read_folder_isolates_unparseable_files_and_counts_them(tmp_path):
    """One malformed export (here: an encoded-word charset the machine
    does not know) must not kill the whole poll or the page: it is
    skipped, the good files still parse, and the counted reader says
    how many were left out."""
    (tmp_path / "good.eml").write_bytes(eml(
        "<good-1@example.com>", "Patch review", "a@example.com", MAIL_USER,
        "Wed, 11 Nov 2026 09:00:00 GMT").encode("utf-8"))
    bad = eml(
        "<bad-1@example.com>", "placeholder", "b@example.com", MAIL_USER,
        "Wed, 11 Nov 2026 10:00:00 GMT",
    ).replace("Subject: placeholder", "Subject: =?x-unknown?Q?Secret_plan?=")
    (tmp_path / "bad.eml").write_bytes(bad.encode("utf-8"))
    messages = read_eml_folder(tmp_path)  # must not raise
    assert [m.id for m in messages] == ["<good-1@example.com>"]
    reported, skipped = read_eml_folder_reported(tmp_path)
    assert skipped == 1
    assert [m.id for m in reported] == ["<good-1@example.com>"]


# -- slice 2: threading by In-Reply-To ------------------------------------


def _thread_sample():
    """One chain plus an orphan: root a-1, replies a-2 and a-3."""
    root = parse_eml(eml("<a-1@example.com>", "North contract", "a@example.com",
                         MAIL_USER, "Tue, 28 Oct 2026 12:00:00 GMT"))
    mid = parse_eml(eml("<a-2@example.com>", "Re: North contract", MAIL_USER,
                        "a@example.com", "Wed, 29 Oct 2026 12:00:00 GMT",
                        in_reply_to="<a-1@example.com>"))
    leaf = parse_eml(eml("<a-3@example.com>", "RE: North contract", "a@example.com",
                         MAIL_USER, "Thu, 30 Oct 2026 12:00:00 GMT",
                         in_reply_to="<a-2@example.com>"))
    orphan = parse_eml(eml("<o-1@example.com>", "Re: Never seen", "x@example.com",
                           MAIL_USER, "Fri, 31 Oct 2026 12:00:00 GMT",
                           in_reply_to="<missing@example.com>"))
    return root, mid, leaf, orphan


def test_thread_walks_in_reply_to_the_root_and_strips_re():
    root, mid, leaf, orphan = _thread_sample()
    by_id = {m.id: m for m in (root, mid, leaf, orphan)}
    assert thread_of(root, by_id) == "North contract"
    assert thread_of(mid, by_id) == "North contract"
    assert thread_of(leaf, by_id) == "North contract"
    # The orphan's parent is absent, so it threads under its own subject.
    assert thread_of(orphan, by_id) == "Never seen"


def test_thread_walk_survives_a_cycle():
    first = parse_eml(eml("<c-1@example.com>", "Loop", "a@example.com", MAIL_USER,
                          "Tue, 28 Oct 2026 12:00:00 GMT", in_reply_to="<c-2@example.com>"))
    second = parse_eml(eml("<c-2@example.com>", "Re: Loop", "a@example.com", MAIL_USER,
                           "Wed, 29 Oct 2026 12:00:00 GMT", in_reply_to="<c-1@example.com>"))
    by_id = {m.id: m for m in (first, second)}
    assert thread_of(first, by_id) == "Loop"
    assert thread_of(second, by_id) == "Loop"


def test_self_reply_cycle_points_at_itself():
    node = parse_eml(eml("<s-1@example.com>", "Self loop", "a@example.com", MAIL_USER,
                         "Tue, 28 Oct 2026 12:00:00 GMT", in_reply_to="<s-1@example.com>"))
    assert thread_of(node, {node.id: node}) == "Self loop"


def test_with_threads_fills_thread_and_sorts_by_date():
    root, mid, leaf, orphan = _thread_sample()
    threaded = with_threads([leaf, orphan, root, mid])
    assert [m.id for m in threaded] == [
        "<a-1@example.com>", "<a-2@example.com>", "<a-3@example.com>", "<o-1@example.com>",
    ]
    assert all(m.thread == "North contract" for m in threaded[:3])
    assert threaded[3].thread == "Never seen"


# -- slice 3: digest and follow-up thread sets ----------------------------


def _full_mailbox():
    """The donor's sample mailbox, rebuilt from the adapted fixtures."""
    return with_threads(read_eml_folder(FIXTURES))


def test_recent_threads_is_the_24_hour_set_from_the_fixtures():
    assert recent_threads(_full_mailbox(), SAMPLE_NOW) == ["Budget notes", "Desk request", "Lunch"]


def test_digest_hours_is_24():
    assert DIGEST_HOURS == 24


def test_recent_threads_empty_when_nothing_is_active():
    assert recent_threads(_full_mailbox(), SAMPLE_NOW + 30 * 86400) == []


def test_follow_ups_match_the_donor_expectations():
    assert follow_ups(_full_mailbox(), set(), SAMPLE_NOW,
                     self_address=MAIL_USER) == ["North contract", "Q4 plan", "West renewal"]


def test_follow_up_days_defaults_to_two():
    assert FOLLOW_UP_DAYS == 2


def test_follow_ups_exclude_threads_whose_latest_is_from_the_user():
    # South invoice's latest message is the user's own reply.
    assert "South invoice" not in follow_ups(_full_mailbox(), set(), SAMPLE_NOW,
                                           self_address=MAIL_USER)


def test_follow_ups_exclude_handled_threads():
    handled = {"North contract"}
    assert follow_ups(_full_mailbox(), handled, SAMPLE_NOW,
                     self_address=MAIL_USER) == ["Q4 plan", "West renewal"]


def test_follow_ups_honour_a_custom_threshold():
    # The threshold waits N days past the latest message: a bigger N is
    # a stricter cutoff (fewer threads qualify), the donor's arithmetic.
    assert follow_ups(_full_mailbox(), set(), SAMPLE_NOW, days=1,
                     self_address=MAIL_USER) == [
        "North contract", "Q4 plan", "West renewal",
    ]
    # days=8 puts the cutoff at 11-03, so West renewal (latest 11-05)
    # drops out; days=12 (cutoff 10-30) also drops North (latest 11-01);
    # days=45 (cutoff 09-27) finally drops the 10-01 Q4 plan.
    assert follow_ups(_full_mailbox(), set(), SAMPLE_NOW, days=8,
                     self_address=MAIL_USER) == [
        "North contract", "Q4 plan",
    ]
    assert follow_ups(_full_mailbox(), set(), SAMPLE_NOW, days=12,
                     self_address=MAIL_USER) == ["Q4 plan"]
    assert follow_ups(_full_mailbox(), set(), SAMPLE_NOW, days=45,
                     self_address=MAIL_USER) == []


def test_digest_details_carry_metadata_only():
    details = digest_details(_full_mailbox(), SAMPLE_NOW)
    names = [d["thread"] for d in details]
    assert names == ["Budget notes", "Desk request", "Lunch"]
    for detail in details:
        assert set(detail) == {"thread", "count", "lastFrom", "lastTs"}
    budget = next(d for d in details if d["thread"] == "Budget notes")
    assert budget["count"] == 4
    assert budget["lastFrom"] == "c@example.com"


# -- reply helpers (donor replyRecipients / writeReply) --------------------


def test_reply_recipients_is_reply_all_minus_self_deduped():
    message = parse_eml(eml(
        "<r-1@example.com>", "Party", "a@example.com",
        f"{MAIL_USER}, b@example.com, B@example.com", "Tue, 28 Oct 2026 12:00:00 GMT",
        cc="c@example.com; d@example.com",
    ))
    assert reply_recipients(message, self_address=MAIL_USER) == (
        "a@example.com, b@example.com, c@example.com, d@example.com"
    )


def test_reply_recipients_raises_when_nobody_else_is_left():
    message = parse_eml(eml(
        "<r-2@example.com>", "Solo", MAIL_USER, MAIL_USER,
        "Tue, 28 Oct 2026 12:00:00 GMT",
    ))
    with pytest.raises(ValueError):
        reply_recipients(message, self_address=MAIL_USER)


def test_reply_subject_prefixes_re_once():
    assert reply_subject("North contract") == "Re: North contract"
    assert reply_subject("Re: North contract") == "Re: North contract"


def test_write_reply_writes_a_threaded_crlf_eml_to_the_outbox(tmp_path):
    outbox = tmp_path / "outbox"
    frozen = 1731326400.0  # a fixed moment, so the names are deterministic
    path = write_reply(
        outbox,
        original_id="<a-1@example.com>",
        to="a@example.com, b@example.com",
        subject="Re: North contract",
        body="Here is my reply.",
        clock=lambda: frozen,
    )
    assert path.parent == outbox
    assert path.name.endswith(".eml")
    text = path.read_bytes().decode("utf-8")  # bytes: text mode would translate the CRLFs
    headers = text.split("\r\n\r\n", 1)[0]
    assert f"In-Reply-To: <a-1@example.com>" in headers
    assert "Message-ID: <reply-1731326400000@example.com>" in headers
    assert "To: a@example.com, b@example.com" in headers
    assert "Subject: Re: North contract" in headers
    assert "\n" not in text.replace("\r\n", "")  # CRLF line endings only
    assert text.endswith("Here is my reply.\r\n")
    # The written file carries only the user's body, never stored content.
    assert "SECRET-BODY-TEXT" not in text


def test_write_reply_creates_the_outbox_folder(tmp_path):
    outbox = tmp_path / "nested" / "outbox"
    path = write_reply(outbox, "<x@example.com>", "a@example.com", "Re: x", "hi", clock=lambda: 0.0)
    assert path.is_file()


@pytest.mark.parametrize("odd_date_ts", [-86400.0, 10.0 ** 20])
def test_format_header_ts_survives_odd_dates(odd_date_ts):
    """A pre-1970 Date header raises OSError on Windows and an
    out-of-range one raises OverflowError, while POSIX builds accept
    both and render them. The portable contract is only that an odd
    date never costs the page its render: some string comes back."""
    rendered = format_header_ts(odd_date_ts)
    assert isinstance(rendered, str)
    assert rendered


@pytest.mark.parametrize("error", [OSError, OverflowError, ValueError])
def test_format_header_ts_reads_unknown_date_when_the_clock_refuses(monkeypatch, error):
    """When the platform's clock refuses a date outright (OSError on
    Windows for pre-1970, OverflowError for out-of-range years, and a
    malformed one raising ValueError), the page reads 'unknown date'
    instead of losing the whole render."""

    class RefusingClock:
        @staticmethod
        def fromtimestamp(_ts):
            raise error("the platform refused this date")

    monkeypatch.setattr("agentdesk.mail.core.datetime", RefusingClock)
    assert format_header_ts(10.0 ** 20) == "unknown date"


# -- the header injection guard -------------------------------------------


@pytest.mark.parametrize("smuggled", ["\r\n", "\r", "\n"])
@pytest.mark.parametrize("field", ["original_id", "to", "subject"])
def test_write_reply_rejects_line_breaks_in_header_fields(tmp_path, field, smuggled):
    """The reply file's headers must be lines the app composed. The
    generic cards route lets a caller store a mailDraft whose to (or
    subject, or original id) carries a smuggled "\\r\\nBcc: x@y.z", which
    the user would later send from their own mail client; write_reply
    refuses such metadata with a clean ValueError, before it even
    creates the outbox folder. The body is exempt: the user's own words
    may contain newlines, and they live after the header block."""
    values = {
        "original_id": f"<a-1@example.com>{smuggled}Bcc: x@y.z",
        "to": f"a@example.com{smuggled}Bcc: x@y.z",
        "subject": f"Re: North{smuggled}Bcc: x@y.z",
    }
    kwargs = {
        "original_id": "<a-1@example.com>",
        "to": "a@example.com",
        "subject": "Re: North contract",
        "body": "Here is my reply.",
    }
    kwargs[field] = values[field]
    with pytest.raises(ValueError) as raised:
        write_reply(tmp_path / "outbox", clock=lambda: 0.0, **kwargs)
    assert "line break" in str(raised.value)
    assert not (tmp_path / "outbox").exists()  # refused before any write


# -- self detection compares the configured address, inside the header ----


def test_follow_ups_treat_a_display_name_from_header_as_answered():
    """The user's own reply carries a display name; the address inside
    the angle brackets is what self-detection must compare."""
    mine = "priya@corp.com"
    original = parse_eml(eml(
        "<a-1@example.com>", "North contract", "a@example.com",
        mine, "Mon, 27 Oct 2026 12:00:00 GMT",
    ))
    replied = parse_eml(eml(
        "<p-2@corp.com>", "Re: North contract", f"Priya Sharma <{mine}>",
        "team@corp.com", "Tue, 28 Oct 2026 12:00:00 GMT",
        in_reply_to="<a-1@example.com>",
    ))
    messages = with_threads([original, replied])
    now = replied.date_ts + 3 * DAY_S
    assert follow_ups(messages, set(), now, self_address=mine) == []


def test_reply_recipients_drop_self_with_a_display_name():
    message = parse_eml(eml(
        "<r-3@corp.com>", "Party", "Priya Sharma <priya@corp.com>",
        "priya@corp.com, team@corp.com", "Tue, 28 Oct 2026 12:00:00 GMT",
    ))
    assert reply_recipients(message, self_address="priya@corp.com") == "team@corp.com"


def test_an_unconfigured_address_disables_self_detection():
    """No address configured: the follow-up set cannot claim 'nothing
    from you on this thread', so it stays empty instead of nagging on
    threads the user may already have answered."""
    from_other = parse_eml(eml(
        "<a-9@example.com>", "North contract", "a@example.com",
        "employee@example.com", "Tue, 28 Oct 2026 12:00:00 GMT",
    ))
    messages = with_threads([from_other])
    now = from_other.date_ts + 3 * DAY_S
    assert follow_ups(messages, set(), now, self_address="") == []


def test_write_reply_uses_the_configured_address_as_from(tmp_path):
    path = write_reply(
        tmp_path / "outbox", "<a-1@example.com>", "a@example.com",
        "Re: North contract", "Here is my reply.",
        clock=lambda: 0.0, self_address="priya@corp.com",
    )
    headers = path.read_bytes().decode("utf-8").split("\r\n\r\n", 1)[0]
    assert "From: priya@corp.com" in headers
