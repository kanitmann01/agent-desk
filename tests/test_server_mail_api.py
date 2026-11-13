"""Mail over HTTP: the gate, the off state, the draft flow, the outbox.

The seam tests drive the real server: the mail toggle (default off), the
folder setting, digest and follow-up cards under the inbox budget, the
reply draft flow (draft card, edit, accept writes the threaded .eml,
dismiss writes nothing, and a decide-once guard for every card), the
capabilities card and the what-this-touches statement. The DLP
invariant is proven live here: a capture stub sits where a model
adapter would be, and the whole mail flow must not produce one prompt.
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

import server_harness
from agentdesk.inbox.store import InboxStore
from agentdesk.mail.core import read_eml_folder_reported
from agentdesk.mail.store import MailStore
from agentdesk.mail.watcher import Adapters, MailWatch
from agentdesk.server import app as server_app
from agentdesk.settings import SettingsStore

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mail"

# The fixtures were written for the donor's frozen sample moment; the
# server-side mail watch freezes the same clock so the digest and
# follow-up sets stay the donor's sets on any day the suite runs.
SAMPLE_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc).timestamp()

DRAFT_BODY = "Sounds good, let us lock the numbers tomorrow."


def eml_bytes(message_id: str, subject: str, sender: str, to: str, date: str) -> bytes:
    """One .eml as bytes, the fixtures' shape."""
    lines = [
        f"From: {sender}",
        f"To: {to}",
        f"Subject: {subject}",
        f"Date: {date}",
        f"Message-ID: {message_id}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "",
        "placeholder body",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


class CaptureLlm:
    """The stub adapter: records every prompt. The mail flow must leave
    it untouched."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "a reply no mail flow should ever need"


def frozen_mail_bundle():
    """A deterministic watch plus the ONE inbox and settings store the
    boot will use (the watch files cards into the server's inbox, the
    decide hooks mark handled in the server's mail store). The folder
    still comes from the settings at poll time, so the settings flow is
    exercised end to end (exactly how _default_mail_watch wires it)."""
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False), time.time)
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), lambda: SAMPLE_NOW)
    store = MailStore(sqlite3.connect(":memory:", check_same_thread=False), lambda: SAMPLE_NOW)
    watch = MailWatch(
        inbox=inbox,
        store=store,
        adapters=Adapters(read_folder=read_eml_folder_reported, clock=lambda: SAMPLE_NOW),
        folder_provider=lambda: settings.get("mail_folder"),
    )
    return watch, inbox, store, settings


@pytest.fixture()
def env(tmp_path):
    outbox = tmp_path / "outbox"
    watch, inbox, store, settings = frozen_mail_bundle()
    booted = server_harness.Booted(
        llm=CaptureLlm(), outbox_dir=outbox, mail=watch, inbox_store=inbox,
        mail_store=store, settings_store=settings)
    booted.outbox = outbox
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _enable_mail(env, auth, folder=None):
    """The settings dance: toggle on, then (optionally) set the folder."""
    status, _h, body = env.post_json("/settings/toggle", {"key": "mail_enabled"}, auth)
    assert status == 200
    assert json.loads(body)["value"] is True
    if folder is not None:
        status, _h, body = env.post_json("/settings/mail/folder", {"folder": str(folder)}, auth)
        assert status == 200
    return json.loads(body)


def _mail_cards(env):
    return [c for c in env.server.inbox.waiting() if c.kind.startswith("mail_")]


# -- the gate and the off state -------------------------------------------


def test_mail_endpoints_require_a_session(env):
    status, _h, _b = env.request("GET", "/mail", env.host_header())
    assert status == 401
    status, _h, _b = env.post_json("/mail/retest", {}, env.host_header())
    assert status == 401


def test_mail_off_by_default_and_the_page_says_so_honestly(env, auth):
    assert env.server.settings.get("mail_enabled") is False
    assert env.server.inbox.waiting() == []  # no mail cards while off
    status, _h, body = env.request("GET", "/mail", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "off" in page.lower()
    assert "/settings" in page  # the honest enable pointer
    assert "message-{0}" not in page  # no per-message draft forms while off


def test_off_means_no_watcher_and_no_cards(env, auth):
    status, _h, body = env.post_json("/mail/retest", {}, auth)
    assert status == 409
    assert json.loads(body)["reconnect"] == "/settings"
    status, _h, _b = env.post_json(
        f"/mail/{quote('<desk-3@example.com>', safe='')}/draft",
        {"body": "hi"}, auth)
    assert status == 409
    assert env.server.inbox.waiting() == []
    # Toggling on constructs the watch; toggling off stops it for good.
    _enable_mail(env, auth, folder=FIXTURES)
    assert env.server.mail is not None
    status, _h, body = env.post_json("/settings/toggle", {"key": "mail_enabled"}, auth)
    assert json.loads(body)["value"] is False
    status, _h, _b = env.post_json("/mail/retest", {}, auth)
    assert status == 409
    status, _h, page = env.request("GET", "/mail", auth)
    assert "off" in page.decode("utf-8").lower()


# -- toggling on end to end ------------------------------------------------


def test_toggle_on_polls_the_folder_and_files_cards(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    status, _h, body = env.post_json("/mail/retest", {}, auth)
    payload = json.loads(body)
    assert status == 200
    assert payload["state"] == "watching"
    assert payload["folder"] == str(FIXTURES)
    kinds = sorted(c.kind for c in _mail_cards(env))
    assert kinds == [
        "mail_digest", "mail_follow_up", "mail_follow_up", "mail_follow_up",
    ]
    digest = next(c for c in _mail_cards(env) if c.kind == "mail_digest")
    assert digest.meta["threads"] == ["Budget notes", "Desk request", "Lunch"]
    # A poll touched the folder, read-only, and said so in the audit.
    entries = [e["action"] for e in _audit_entries(env)]
    assert "mail.poll" in entries


def test_the_mail_page_shows_the_digest_and_follow_ups(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    env.post_json("/mail/retest", {}, auth)
    status, _h, body = env.request("GET", "/mail", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "Budget notes" in page
    assert "West renewal" in page
    assert "/mail/retest" in page
    assert "Draft reply" in page


def test_a_malformed_file_does_not_break_the_mail_page(env, auth, tmp_path):
    """An unknown encoded-word charset in one file used to raise out of
    the page render (500). The folder read isolates bad files, so the
    poll files the good threads and the page renders."""
    mailbox = tmp_path / "mailbox"
    mailbox.mkdir()
    (mailbox / "good.eml").write_bytes(eml_bytes(
        "<g1@example.com>", "Patch review", "a@example.com",
        "employee@example.com", "Wed, 11 Nov 2026 09:00:00 GMT"))
    bad = eml_bytes("<bad@example.com>", "placeholder", "b@example.com",
                    "employee@example.com", "Wed, 11 Nov 2026 10:00:00 GMT")
    (mailbox / "bad.eml").write_bytes(bad.replace(
        b"Subject: placeholder", b"Subject: =?x-unknown?Q?Secret_plan?="))
    _enable_mail(env, auth, folder=mailbox)
    status, _h, _b = env.post_json("/mail/retest", {}, auth)
    assert status == 200
    page_status, _h, body = env.request("GET", "/mail", auth)
    assert page_status == 200
    assert "Patch review" in body.decode("utf-8")
    assert [c.kind for c in _mail_cards(env)] == ["mail_digest"]


def test_the_whole_mail_flow_sends_nothing_to_any_model(env, auth):
    """The DLP invariant, live: not one prompt may be produced by the
    mail flow, and no fixture body may appear in any prompt ever."""
    _enable_mail(env, auth, folder=FIXTURES)
    env.post_json("/mail/retest", {}, auth)
    env.request("GET", "/mail", auth)
    message_id = "<desk-3@example.com>"
    status, _h, body = env.post_json(
        f"/mail/{quote(message_id, safe='')}/draft", {"body": DRAFT_BODY}, auth)
    card_id = json.loads(body)["id"]
    status, _h, _b = env.post_json(f"/inbox/cards/{card_id}/accept", {}, auth)
    assert status == 200
    capture = env.server.llm
    assert capture.prompts == []


def test_no_fixture_body_text_lands_in_any_prompt_or_outbox_file(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    env.post_json("/mail/retest", {}, auth)
    status, _h, body = env.post_json(
        f"/mail/{quote('<desk-3@example.com>', safe='')}/draft",
        {"body": DRAFT_BODY}, auth)
    card_id = json.loads(body)["id"]
    env.post_json(f"/inbox/cards/{card_id}/accept", {}, auth)
    capture = env.server.llm
    for prompt in capture.prompts:
        assert "Desk request note" not in prompt
    files = list(env.outbox.glob("*.eml"))
    assert len(files) == 1
    written = files[0].read_bytes().decode("utf-8")
    assert "Desk request note" not in written  # only the user's own body
    assert DRAFT_BODY in written


# -- the reply draft flow ---------------------------------------------------


def _draft_card(env, auth, message_id="<desk-3@example.com>", body=DRAFT_BODY):
    status, _h, body_out = env.post_json(
        f"/mail/{quote(message_id, safe='')}/draft", {"body": body}, auth)
    assert status == 201
    return json.loads(body_out)


def test_draft_card_carries_metadata_and_the_user_text(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    card = _draft_card(env, auth)
    assert card["kind"] == "suggestion"
    assert card["draft"] == DRAFT_BODY
    meta = card["meta"]["mailDraft"]
    assert meta["messageId"] == "<desk-3@example.com>"
    assert meta["to"] == "b@example.com"  # reply-all minus self
    assert meta["subject"] == "Re: Desk request"
    assert "mail.draft" in [e["action"] for e in _audit_entries(env)]


def test_draft_without_body_or_unknown_message_is_rejected(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    status, _h, body = env.post_json(
        f"/mail/{quote('<desk-3@example.com>', safe='')}/draft", {}, auth)
    assert status == 400
    status, _h, _b = env.post_json(
        f"/mail/{quote('<nope@example.com>', safe='')}/draft",
        {"body": "x"}, auth)
    assert status == 404


def test_accepting_a_draft_writes_a_threaded_eml_to_the_outbox(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    card = _draft_card(env, auth)
    status, _h, _b = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 200
    files = list(env.outbox.glob("*.eml"))
    assert len(files) == 1
    text = files[0].read_bytes().decode("utf-8")
    headers = text.split("\r\n\r\n", 1)[0]
    assert "In-Reply-To: <desk-3@example.com>" in headers
    assert "To: b@example.com" in headers
    assert "Subject: Re: Desk request" in headers
    assert "Message-ID: <reply-" in headers
    assert DRAFT_BODY in text
    assert "mail.sent" in [e["action"] for e in _audit_entries(env)]


def test_editing_the_draft_then_accepting_writes_the_edited_text(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    card = _draft_card(env, auth)
    status, _h, _b = env.post_json(
        f"/inbox/cards/{card['id']}/edit", {"draft": "Edited reply."}, auth)
    assert status == 200
    env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    files = list(env.outbox.glob("*.eml"))
    assert len(files) == 1
    assert "Edited reply." in files[0].read_bytes().decode("utf-8")


def test_dismissing_a_draft_writes_nothing(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    card = _draft_card(env, auth)
    status, _h, _b = env.post_json(f"/inbox/cards/{card['id']}/dismiss", {}, auth)
    assert status == 200
    assert list(env.outbox.glob("*.eml")) == []
    assert "mail.sent" not in [e["action"] for e in _audit_entries(env)]


def test_a_smuggled_header_in_the_draft_metadata_is_refused_on_accept(env, auth):
    """The generic cards route stores meta as given, so an
    authenticated caller can plant a mailDraft whose to carries a
    smuggled "\\r\\nBcc:" line. The accept path refuses it: the reply
    file is never written, the card stays waiting, and the answer says
    why (the write_reply guard's clean error)."""
    _enable_mail(env, auth, folder=FIXTURES)
    status, _h, body = env.post_json("/inbox/cards", {
        "kind": "suggestion",
        "origin": "planted card",
        "title": "Reply draft: Re: North contract",
        "actionLabel": "Write to outbox",
        "draft": DRAFT_BODY,
        "meta": {"mailDraft": {
            "messageId": "<north-1@example.com>",
            "to": "a@example.com\r\nBcc: x@y.z",
            "subject": "Re: North contract",
        }},
    }, auth)
    assert status == 201
    card_id = json.loads(body)["id"]
    status, _h, payload = env.post_json(f"/inbox/cards/{card_id}/accept", {}, auth)
    assert status == 400
    assert "line break" in json.loads(payload)["error"]
    assert list(env.outbox.glob("*.eml")) == []  # nothing to send later
    assert env.server.inbox.get(card_id).status == "waiting"  # not accepted


def test_a_failed_outbox_write_leaves_the_card_waiting(env, auth, monkeypatch):
    _enable_mail(env, auth, folder=FIXTURES)
    card = _draft_card(env, auth)

    def boom(outbox, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(server_app, "write_reply", boom)
    status, _h, body = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 500
    assert env.server.inbox.get(card["id"]).status == "waiting"  # not accepted
    assert list(env.outbox.glob("*.eml")) == []


# -- the decide-once replay guard (all kinds) -------------------------------


def test_accepting_twice_is_refused_and_writes_one_file(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    card = _draft_card(env, auth)
    status, _h, _b = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 200
    assert len(list(env.outbox.glob("*.eml"))) == 1
    status, _h, body = env.post_json(f"/inbox/cards/{card['id']}/accept", {}, auth)
    assert status == 409
    assert len(list(env.outbox.glob("*.eml"))) == 1  # the replay wrote nothing


def test_accept_then_dismiss_is_refused_for_any_kind(env, auth):
    card = env.server.inbox.add(kind="suggestion", origin="test origin", title="t")
    env.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    status, _h, _b = env.post_json(f"/inbox/cards/{card.id}/dismiss", {}, auth)
    assert status == 409
    status, _h, _b = env.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    assert status == 409
    assert env.server.inbox.get(card.id).status == "accepted"


def test_form_replay_redirects_instead_of_erroring(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    card = _draft_card(env, auth)
    form_headers = {"Content-Type": "application/x-www-form-urlencoded", **auth}
    env.post_json(f"/inbox/cards/{card['id']}/accept", {}, form_headers)
    status, headers, _b = env.post_json(
        f"/inbox/cards/{card['id']}/accept", {}, form_headers)
    assert status == 303  # a double-clicked form lands back on the inbox
    assert headers["Location"] == "/inbox"
    assert len(list(env.outbox.glob("*.eml"))) == 1


def test_inbox_page_labels_mail_cards(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    env.post_json("/mail/retest", {}, auth)
    status, _h, body = env.request("GET", "/inbox", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "Mail digest" in page
    assert "Needs a reply" in page


def test_deciding_a_follow_up_marks_the_thread_handled(env, auth):
    _enable_mail(env, auth, folder=FIXTURES)
    env.post_json("/mail/retest", {}, auth)
    follow = next(c for c in _mail_cards(env) if c.kind == "mail_follow_up")
    thread = follow.meta["thread"]
    env.post_json(f"/inbox/cards/{follow.id}/dismiss", {}, auth)
    assert env.server.mail_store.is_handled(thread)
    # A later poll does not re-mint the handled thread's card.
    env.post_json("/mail/retest", {}, auth)
    assert thread not in [c.title for c in _mail_cards(env) if c.kind == "mail_follow_up"]
    # The page shows the handled state.
    status, _h, page = env.request("GET", "/mail", auth)
    assert "handled" in page.decode("utf-8").lower()


def test_a_snoozed_card_is_still_decidable(env, auth):
    """A snooze is not a decision: the card stays waiting, so a decided
    guard must not block a user who snoozes and then acts."""
    card = env.server.inbox.add(kind="suggestion", origin="test origin", title="t")
    env.server.inbox.snooze(card.id, env.server.inbox.now_ts() + 3600)
    status, _h, _b = env.post_json(f"/inbox/cards/{card.id}/accept", {}, auth)
    assert status == 200


# -- settings page, capabilities card, touches ------------------------------


def test_settings_page_lists_the_mail_toggle_and_folder_field(env, auth):
    status, _h, body = env.request("GET", "/settings", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "mail_enabled" in page
    assert "/settings/mail/folder" in page
    assert "/mail" in page  # the settings rail link to the mail page


def test_capabilities_card_reflects_off_watching_and_error(env, auth):
    def mail_word():
        status, _h, body = env.request("GET", "/capabilities", auth)
        page = body.decode("utf-8")
        marker = page[page.index("id='card-mail'"):]
        return marker.split("stamp")[1].split(">")[1].split("<")[0]

    _enable_mail(env, auth)  # on, but no folder yet
    assert mail_word() == "unconfigured"
    env.post_json("/settings/mail/folder", {"folder": str(FIXTURES)}, auth)
    assert mail_word() == "watching"
    env.post_json("/settings/toggle", {"key": "mail_enabled"}, auth)  # off again
    assert mail_word() == "off"


def test_capabilities_card_shows_error_when_folder_is_missing(env, auth):
    _enable_mail(env, auth, folder=str(env.server.outbox_dir.parent / "missing-mail"))
    env.post_json("/mail/retest", {}, auth)
    status, _h, body = env.request("GET", "/capabilities", auth)
    page = body.decode("utf-8")
    assert "id='card-mail'" in page
    assert "error" in page[page.index("id='card-mail'"):][:400]


def test_touches_page_states_mail_honestly(env, auth):
    status, _h, body = env.request("GET", "/what-this-touches", auth)
    page = body.decode("utf-8")
    assert status == 200
    assert "mail.poll" in page
    assert "mail.draft" in page
    assert "mail.sent" in page
    assert "headers" in page
    assert "off by default" in page
    assert "never" in page  # "never read" / "never sent" in the statements


def test_mail_folder_save_via_form_redirects_back_to_settings(env, auth):
    _enable_mail(env, auth)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    body = f"folder={quote(str(FIXTURES))}".encode("utf-8")
    status, resp_headers, _b = env.request("POST", "/settings/mail/folder", {
        **headers, "Content-Length": str(len(body)), **auth}, body)
    assert status == 303
    assert resp_headers["Location"] == "/settings"
    assert env.server.settings.get("mail_folder") == str(FIXTURES)


def _audit_entries(env):
    from agentdesk.assistant import audit as audit_store
    return audit_store.entries(env.server.audit_conn, 100)


def test_toggling_mail_rewires_the_plugin_runner(env, auth):
    """The runner's mail-digest binding follows the watcher the toggle
    owns (#64): on, plugin cards read the live watcher; off, the digest
    is paused and no plugin card reads the folder at all."""
    assert env.server.plugins is not None
    assert env.server.plugins.runner.mail is None  # off: no binding

    _enable_mail(env, auth)
    assert env.server.plugins.runner.mail is env.server.mail

    env.post_json("/settings/toggle", {"key": "mail_enabled"}, auth)  # off
    assert env.server.plugins.runner.mail is None
