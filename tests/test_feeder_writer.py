"""The feeder writer: headers in, header-only .eml files out.

The writer is the one serializer in the package. These tests pin the
contract the rest of the mail path already reads: exact headers, CRLF,
UTF-8 without BOM, a unique Message-ID, and no bytes after the header
terminator, so parse_eml round-trips every field and no body (or body
marker) ever reaches a file.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.feeder.writer import FEEDER_PREFIX, render_eml, write_mail, write_status
from agentdesk.mail.core import Message, parse_eml, read_eml_folder_reported

SAMPLE_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc).timestamp()
DAY_S = 24 * 60 * 60

HEADER_ORDER = [
    "From",
    "To",
    "Cc",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "Importance",
]


def message(**overrides) -> Message:
    """One fully populated header record, with fields a test can replace."""
    fields = {
        "id": "<a-1@example.com>",
        "in_reply_to": "<root-1@example.com>",
        "sender": "Priya Sharma <priya@example.com>",
        "to": "employee@example.com",
        "cc": "team@example.com",
        "subject": "North contract",
        "date_ts": SAMPLE_NOW,
        "importance": "High",
    }
    fields.update(overrides)
    return Message(**fields)


def raw_headers(data: bytes) -> list[str]:
    """The header block's lines, split on CRLF, without the blank terminator."""
    block = data.split(b"\r\n\r\n", 1)[0]
    return block.decode("utf-8").split("\r\n")


# -- render_eml -----------------------------------------------------------


def test_render_round_trips_every_field_through_parse_eml():
    original = message(subject="Caf\u00e9 plan")
    parsed = parse_eml(render_eml(original).decode("utf-8"))
    assert parsed.id == original.id
    assert parsed.in_reply_to == original.in_reply_to
    assert parsed.sender == original.sender
    assert parsed.to == original.to
    assert parsed.cc == original.cc
    assert parsed.subject == original.subject
    assert parsed.date_ts == original.date_ts
    assert parsed.importance == original.importance
    assert parsed == original


def test_render_writes_exactly_the_named_headers_in_order():
    lines = raw_headers(render_eml(message()))
    assert [line.split(":", 1)[0] for line in lines] == HEADER_ORDER


def test_render_omits_metadata_it_does_not_have_instead_of_inventing_it():
    bare = message(id="<b-1@example.com>", in_reply_to="", cc="", importance="", date_ts=0.0)
    lines = raw_headers(render_eml(bare))
    names = [line.split(":", 1)[0] for line in lines]
    assert names == ["From", "To", "Subject", "Message-ID"]
    parsed = parse_eml(render_eml(bare).decode("utf-8"))
    assert parsed.cc == ""
    assert parsed.in_reply_to == ""
    assert parsed.importance == ""
    assert parsed.date_ts == 0.0


def test_render_ends_at_the_header_terminator_with_no_body():
    data = render_eml(message())
    assert data.endswith(b"\r\n\r\n")
    assert data.count(b"\r\n\r\n") == 1
    assert data.split(b"\r\n\r\n", 1)[1] == b""
    # No MIME envelope and no body markers, the shape a full export has.
    assert b"MIME-Version" not in data
    assert b"Content-Type" not in data
    assert b"Content-Transfer-Encoding" not in data


def test_render_is_utf8_without_a_bom_and_crlf_only():
    data = render_eml(message(subject="Caf\u00e9 plan"))
    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert "Caf\u00e9".encode("utf-8") in data


def test_render_strips_crlf_from_values_so_no_header_can_be_smuggled():
    smuggled = "North\r\nBcc: evil@example.com"
    data = render_eml(message(subject=smuggled))
    lines = raw_headers(data)
    assert len(lines) == len(HEADER_ORDER)  # one line per header, nothing more
    assert not any(line.startswith("Bcc:") for line in lines)
    parsed = parse_eml(data.decode("utf-8"))
    assert not hasattr(parsed, "bcc")
    assert parsed.subject == "North Bcc: evil@example.com"


def test_render_generates_a_stable_unique_message_id_when_the_source_has_none():
    first = render_eml(message(id=""))
    again = render_eml(message(id=""))
    other = render_eml(message(id="", subject="Something else"))
    first_id = parse_eml(first.decode("utf-8")).id
    other_id = parse_eml(other.decode("utf-8")).id
    assert first == again  # deterministic, so a rerun overwrites
    assert first_id
    assert first_id != other_id
    assert first_id.startswith("<feeder-")
    assert first_id.endswith("@agent-desk.local>")


# -- write_mail -----------------------------------------------------------


def test_write_mail_writes_one_parseable_file_per_message(tmp_path):
    folder = tmp_path / "mail"
    messages = [
        message(id="<a-1@example.com>", subject="North contract", date_ts=SAMPLE_NOW - DAY_S),
        message(id="", subject="No id in the index", date_ts=SAMPLE_NOW - 2 * DAY_S),
        message(id="<c-1@example.com>", subject="Third", date_ts=SAMPLE_NOW - 3 * DAY_S,
                cc="", importance="", in_reply_to=""),
    ]
    written = write_mail(messages, folder, now=SAMPLE_NOW, window_days=14)
    assert written == 3
    parsed, unparsed = read_eml_folder_reported(folder)
    assert unparsed == 0
    by_subject = {m.subject: m for m in parsed}
    assert set(by_subject) == {"North contract", "No id in the index", "Third"}
    assert by_subject["North contract"].sender == "Priya Sharma <priya@example.com>"
    assert by_subject["No id in the index"].id  # generated, never blank
    assert len({m.id for m in parsed}) == 3
    for path in folder.iterdir():
        assert path.name.startswith(FEEDER_PREFIX)
        assert path.name.endswith(".eml")
        data = path.read_bytes()
        assert data.endswith(b"\r\n\r\n")
        assert data.count(b"\r\n\r\n") == 1


def test_write_mail_never_writes_a_body_even_when_the_source_carried_one(tmp_path):
    folder = tmp_path / "mail"
    source = (
        "From: a@example.com\r\n"
        "To: employee@example.com\r\n"
        "Subject: Quarterly plan\r\n"
        "Date: Wed, 11 Nov 2026 12:00:00 GMT\r\n"
        "Message-ID: <q-1@example.com>\r\n"
        "\r\n"
        "SECRET-BODY-TOKEN that must never reach a feeder file\r\n"
    )
    collected = parse_eml(source)
    write_mail([collected], folder, now=SAMPLE_NOW, window_days=14)
    assert folder.exists()
    for path in folder.iterdir():
        data = path.read_bytes()
        assert b"SECRET-BODY-TOKEN" not in data
        assert data.split(b"\r\n\r\n", 1)[1] == b""


def test_write_mail_is_idempotent_and_names_files_deterministically(tmp_path):
    folder = tmp_path / "mail"
    messages = [message(id="<a-1@example.com>"), message(id="")]
    write_mail(messages, folder, now=SAMPLE_NOW, window_days=14)
    first = {p.name: p.read_bytes() for p in folder.iterdir()}
    written = write_mail(messages, folder, now=SAMPLE_NOW + 60, window_days=14)
    second = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert written == 2
    assert second == first  # same names, same bytes, no duplicates


def test_write_mail_prunes_feeder_files_outside_the_window_only(tmp_path):
    folder = tmp_path / "mail"
    old_now = SAMPLE_NOW - 30 * DAY_S
    old_message = message(id="<old@example.com>", subject="Old thread", date_ts=old_now - DAY_S)
    write_mail([old_message], folder, now=old_now, window_days=14)
    old_file = next(p for p in folder.iterdir() if p.name.startswith(FEEDER_PREFIX))
    # A file the user saved by hand, with an old date, must survive pruning.
    manual = folder / "save-as-copy.eml"
    manual.write_bytes(render_eml(message(id="<manual@example.com>", subject="Manual")))
    recent = message(id="<new@example.com>", subject="Recent thread", date_ts=SAMPLE_NOW - DAY_S)
    write_mail([recent], folder, now=SAMPLE_NOW, window_days=14)
    names = sorted(p.name for p in folder.iterdir())
    assert old_file.name not in names
    assert manual.name in names
    assert len(names) == 2  # the manual file and the recent feeder file


def test_write_mail_keeps_the_previous_file_and_cleans_temp_when_replace_fails(tmp_path, monkeypatch):
    folder = tmp_path / "mail"
    write_mail([message(subject="First")], folder, now=SAMPLE_NOW, window_days=14)
    (before,) = list(folder.iterdir())
    previous = before.read_bytes()

    def refuse_replace(source, destination):
        """Stand in for a failing atomic replace."""
        raise OSError("the volume refused the replace")

    monkeypatch.setattr("agentdesk.feeder.writer.os.replace", refuse_replace)
    with pytest.raises(OSError):
        write_mail([message(subject="Second")], folder, now=SAMPLE_NOW, window_days=14)

    (after,) = list(folder.iterdir())
    assert after.name == before.name
    assert after.read_bytes() == previous
    assert [p.suffix for p in folder.iterdir()] == [".eml"]  # no temp left behind


def test_write_mail_creates_the_folder_even_when_there_is_nothing_to_write(tmp_path):
    folder = tmp_path / "nested" / "mail"
    assert write_mail([], folder, now=SAMPLE_NOW, window_days=14) == 0
    assert folder.is_dir()
    assert list(folder.iterdir()) == []


# -- write_status ---------------------------------------------------------

STATUS = {
    "collector": "manual",
    "platform": "test-os",
    "lastRunTs": SAMPLE_NOW,
    "lastResult": "unavailable",
    "lastError": "No automatic Outlook collector is available.",
    "written": 0,
}


def test_write_status_writes_parseable_utf8_json(tmp_path):
    path = tmp_path / "feeder-status.json"
    write_status(STATUS, path)
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert json.loads(data.decode("utf-8")) == STATUS


def test_write_status_overwrites_atomically_and_keeps_the_old_file_on_a_fault(tmp_path, monkeypatch):
    path = tmp_path / "feeder-status.json"
    write_status(STATUS, path)
    previous = path.read_bytes()

    def refuse_replace(source, destination):
        """Stand in for a failing atomic replace."""
        raise OSError("the volume refused the replace")

    monkeypatch.setattr("agentdesk.feeder.writer.os.replace", refuse_replace)
    with pytest.raises(OSError):
        write_status({**STATUS, "written": 9}, path)
    assert path.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]
