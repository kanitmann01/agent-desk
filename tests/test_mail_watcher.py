"""The mail watcher: one poll reads the folder, computes the digest and
follow-up deltas, and files inbox cards.

The calendar bridge's timer pattern, with the same testability: the
folder read and the clock are injected, so every state runs against
fixtures and a frozen clock. The budget itself lives in the inbox
service; these tests also prove mail cards obey it like any other card.
"""

import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.inbox import service as inbox_service
from agentdesk.inbox.core import KIND_MAIL_DIGEST, KIND_MAIL_FOLLOW_UP
from agentdesk.inbox.store import InboxStore
from agentdesk.mail.core import read_eml_folder_reported
from agentdesk.mail.store import MailStore
from agentdesk.mail.watcher import (
    STATE_ERROR,
    STATE_UNCONFIGURED,
    STATE_WATCHING,
    Adapters,
    MailWatch,
    default_adapters,
    resolve_folder,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mail"
SAMPLE_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc).timestamp()


def eml(message_id, subject, sender, to, date, in_reply_to=""):
    lines = [
        f"From: {sender}",
        f"To: {to}",
        f"Subject: {subject}",
        f"Date: {date}",
        f"Message-ID: {message_id}",
    ]
    if in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    lines += ["MIME-Version: 1.0", "Content-Type: text/plain; charset=utf-8", "", "placeholder"]
    return "\r\n".join(lines) + "\r\n"


def write_message(folder: Path, message_id: str, subject: str, date: str, in_reply_to: str = "") -> None:
    name = message_id.strip("<>").split("@")[0]
    (folder / f"{name}.eml").write_bytes(eml(
        message_id, subject, "a@example.com", "employee@example.com", date,
        in_reply_to=in_reply_to,
    ).encode("utf-8"))


class WatchCase:
    """A watch over a mailbox with a frozen clock and fresh stores. The
    mailbox is a tmp dir by default, or an explicit path (the fixtures)."""

    def __init__(self, tmp_path, now=SAMPLE_NOW, mailbox: Path | None = None):
        self.folder = mailbox if mailbox is not None else tmp_path / "mail"
        if mailbox is None:
            self.folder.mkdir()
        self.now = now
        self.reads = 0
        adapters = Adapters(
            read_folder=self._read,
            clock=lambda: self.now,
        )
        self.inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), lambda: self.now)
        self.store = MailStore(sqlite3.connect(":memory:", check_same_thread=False), lambda: self.now)
        self.audit: list[tuple[str, str, str]] = []
        self.watch = MailWatch(
            inbox=self.inbox,
            store=self.store,
            adapters=adapters,
            folder_provider=lambda: str(self.folder),
            audit_hook=lambda action, target, status: self.audit.append((action, target, status)),
        )

    def _read(self, folder):
        self.reads += 1
        return read_eml_folder_reported(folder)


def test_resolve_folder_prefers_settings_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTDESK_MAIL_FOLDER", str(tmp_path / "from-env"))
    assert resolve_folder(str(tmp_path / "from-settings")) == tmp_path / "from-settings"
    assert resolve_folder("") == tmp_path / "from-env"
    monkeypatch.delenv("AGENTDESK_MAIL_FOLDER")
    assert resolve_folder("") is None
    assert resolve_folder("   ") is None  # whitespace-only counts as unset


def test_default_adapters_wire_the_real_reader_and_clock():
    adapters = default_adapters()
    assert adapters.read_folder is read_eml_folder_reported
    assert callable(adapters.clock)


def test_poll_without_a_folder_is_unconfigured_and_touches_nothing(tmp_path):
    case = WatchCase(tmp_path, mailbox=None)
    case.folder = None  # no folder configured at all
    case.watch.folder_provider = lambda: ""
    status = case.watch.poll()
    assert status["state"] == STATE_UNCONFIGURED
    assert status["configured"] is False
    assert status["created"] == 0  # the one shape, whatever path answered
    assert case.reads == 0
    assert case.inbox.waiting() == []
    assert case.audit == []  # nothing was touched, nothing to audit


def test_poll_files_a_digest_card_and_follow_up_cards(tmp_path):
    case = WatchCase(tmp_path)
    # Thread one's last word is six days back: follow-up material.
    write_message(case.folder, "<f1@example.com>", "Thread one", "Thu, 05 Nov 2026 12:00:00 GMT")
    write_message(case.folder, "<f2@example.com>", "Re: Thread one", "Fri, 06 Nov 2026 12:00:00 GMT",
                  in_reply_to="<f1@example.com>")
    # A thread active inside the 24-hour digest window, fully answered.
    write_message(case.folder, "<f3@example.com>", "Today", "Wed, 11 Nov 2026 08:00:00 GMT")
    status = case.watch.poll()
    assert status["state"] == STATE_WATCHING
    assert status["folder"] == str(case.folder)
    assert status["created"] == 2  # one digest, one follow-up
    kinds = sorted(c.kind for c in case.inbox.waiting())
    assert kinds == [KIND_MAIL_DIGEST, KIND_MAIL_FOLLOW_UP]
    digest = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST)
    assert digest.meta["threads"] == ["Today"]
    assert digest.body == "Today"
    follow = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_FOLLOW_UP)
    assert follow.title == "Thread one"
    assert follow.meta["thread"] == "Thread one"
    assert follow.meta["messageId"] == "<f2@example.com>"
    assert case.audit == [("mail.poll", "mail", "ok")]


def test_poll_uses_the_fixture_mailbox_and_matches_the_donor_sets(tmp_path):
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    status = case.watch.poll()
    digest = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST)
    assert digest.meta["threads"] == ["Budget notes", "Desk request", "Lunch"]
    follows = [c.title for c in case.inbox.waiting() if c.kind == KIND_MAIL_FOLLOW_UP]
    assert follows == ["North contract", "Q4 plan", "West renewal"]
    assert status["created"] == 4


def test_second_poll_mints_no_duplicates(tmp_path):
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    case.watch.poll()
    first = len(case.inbox.waiting())
    assert first == 4
    status = case.watch.poll()
    assert status["created"] == 0
    assert len(case.inbox.waiting()) == first


def test_a_growing_thread_set_replaces_only_after_the_digest_is_decided(tmp_path):
    case = WatchCase(tmp_path)
    write_message(case.folder, "<g1@example.com>", "Alpha", "Wed, 11 Nov 2026 09:00:00 GMT")
    write_message(case.folder, "<g2@example.com>", "Beta", "Wed, 11 Nov 2026 09:30:00 GMT")
    case.watch.poll()
    assert len([c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST]) == 1
    # More mail arrives while the first digest is still waiting: no twin.
    write_message(case.folder, "<g3@example.com>", "Gamma", "Wed, 11 Nov 2026 10:00:00 GMT")
    case.watch.poll()
    assert len([c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST]) == 1
    # Once decided, a changed set earns a fresh digest; the same set would not.
    digest = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST)
    assert digest.meta["threads"] == ["Alpha", "Beta"]
    case.inbox.dismiss(digest.id)
    case.watch.poll()
    threads = {tuple(c.meta["threads"]) for c in case.inbox.dismissed() if c.kind == KIND_MAIL_DIGEST}
    waiting = [c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST]
    assert len(waiting) == 1
    assert tuple(waiting[0].meta["threads"]) == ("Alpha", "Beta", "Gamma")
    assert tuple(waiting[0].meta["threads"]) not in threads


def test_an_accepted_digest_re_surfaces_while_the_set_stays_active(tmp_path):
    """The rule the dedupe comment states: waiting and dismissed
    suppress, an accepted digest re-files on the next poll while its
    threads are still inside the 24-hour window."""
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    case.watch.poll()
    digest = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST)
    case.inbox.accept(digest.id)
    status = case.watch.poll()
    assert status["created"] == 1  # only the digest; the follow-ups still wait
    assert len([c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST]) == 1


def test_a_dismissed_digest_does_not_re_mint_for_the_same_set(tmp_path):
    """The dismissed branch of the digest rule: hiding a digest must not
    mint its twin on the next poll (the briefs rule). A DIFFERENT active
    set still files; that is the growth test's business."""
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    case.watch.poll()
    digest = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST)
    threads = sorted(digest.meta["threads"])
    case.inbox.dismiss(digest.id)
    status = case.watch.poll()
    assert status["created"] == 0
    waiting_digests = [c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST]
    assert waiting_digests == []
    # The dismissal itself remains the record of what was decided.
    dismissed_sets = [sorted(c.meta["threads"]) for c in case.inbox.dismissed() if c.kind == KIND_MAIL_DIGEST]
    assert dismissed_sets == [threads]


def test_a_dismissed_follow_up_does_not_re_mint_for_the_same_thread(tmp_path):
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    case.watch.poll()
    follow = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_FOLLOW_UP)
    case.inbox.dismiss(follow.id)
    status = case.watch.poll()
    assert status["created"] == 0


def test_handled_threads_are_excluded_from_follow_ups_but_not_the_digest(tmp_path):
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    case.store.mark_handled("Lunch")  # a thread inside the digest window
    case.watch.poll()
    follows = [c.title for c in case.inbox.waiting() if c.kind == KIND_MAIL_FOLLOW_UP]
    assert follows == ["North contract", "Q4 plan", "West renewal"]  # unchanged by Lunch
    digest = next(c for c in case.inbox.waiting() if c.kind == KIND_MAIL_DIGEST)
    assert "Lunch" in digest.meta["threads"]  # handled still digests when active


def test_a_malformed_file_does_not_kill_the_poll(tmp_path):
    """One malformed .eml is skipped and counted; the good files still
    file their cards and the poll stays watching."""
    case = WatchCase(tmp_path)
    write_message(case.folder, "<g1@example.com>", "Thread one", "Thu, 05 Nov 2026 12:00:00 GMT")
    write_message(case.folder, "<g2@example.com>", "Re: Thread one", "Fri, 06 Nov 2026 12:00:00 GMT",
                  in_reply_to="<g1@example.com>")
    bad = eml("<bad@example.com>", "placeholder", "a@example.com", "employee@example.com",
              "Wed, 11 Nov 2026 09:00:00 GMT").replace(
        "Subject: placeholder", "Subject: =?x-unknown?Q?Secret_plan?=")
    (case.folder / "bad.eml").write_bytes(bad.encode("utf-8"))
    status = case.watch.poll()
    assert status["state"] == STATE_WATCHING
    assert status["unparsedFiles"] == 1
    kinds = sorted(c.kind for c in case.inbox.waiting())
    assert kinds == [KIND_MAIL_FOLLOW_UP]  # filed from the good files only


def test_missing_folder_is_an_error_state_and_is_audited(tmp_path):
    case = WatchCase(tmp_path)
    case.folder.rmdir()
    status = case.watch.poll()  # the folder is resolved, then fails to read
    assert status["state"] == STATE_ERROR
    assert status["cause"]
    assert status["created"] == 0  # the one shape, whatever path answered
    assert case.audit == [("mail.poll", "mail", "error")]


def test_view_returns_the_page_payload_without_filing_cards(tmp_path):
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    view = case.watch.view()
    assert view["state"] == STATE_WATCHING
    assert view["messages"]
    assert view["messages"][0].id == "<q4-1@example.com>"  # date ascending
    assert view["messages"][0].thread == "Q4 plan"
    assert view["messages"][-1].id == "<desk-3@example.com>"
    threads = [d["thread"] for d in view["digest"]]
    assert threads == ["Budget notes", "Desk request", "Lunch"]
    assert [f["thread"] for f in view["followUps"]] == ["North contract", "Q4 plan", "West renewal"]
    assert view["handled"] == []
    assert case.inbox.waiting() == []  # a view files nothing


def test_mail_cards_queue_under_quiet_hours_and_spend_under_the_cap(tmp_path):
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    case.watch.poll()
    waiting = case.inbox.waiting()
    assert len(waiting) == 4
    # 22:00 local: quiet hours. The cards wait, visibly, unnotified.
    evening = datetime(2026, 11, 11, 22, 0)
    inbox_service.evaluate(case.inbox, evening)
    assert all(c.notified_ts is None for c in case.inbox.waiting())
    # 10:00 local with the default cap of 3: the four cards go out as one
    # digest notification, the budget's batching rule.
    morning = datetime(2026, 11, 11, 10, 0)
    tally = inbox_service.evaluate(case.inbox, morning)
    assert tally["digest"] is True
    assert all(c.notified_ts is not None for c in case.inbox.waiting())


def test_start_polling_files_cards_off_the_main_thread_and_stop_ends_it(tmp_path):
    """The timer thread must genuinely file: the stores are created
    cross-thread-capable (check_same_thread=False, like production), so
    a timer poll over the fixture mailbox lands its cards, and the
    final state is read after a poll that ran off the main thread."""
    case = WatchCase(tmp_path, mailbox=FIXTURES)
    case.watch.start_polling(interval_s=0.05)
    deadline = time.monotonic() + 5.0
    while len(case.inbox.waiting()) < 4 and time.monotonic() < deadline:
        time.sleep(0.01)
    case.watch.stop_polling()
    assert len(case.inbox.waiting()) == 4  # filed from the timer thread, deduped
    assert case.watch.status()["state"] == STATE_WATCHING
    assert case.reads >= 1
    reads_after_stop = case.reads
    time.sleep(0.12)
    assert case.reads == reads_after_stop  # the timer is cancelled, not paused
    assert len(case.inbox.waiting()) == 4  # no stray poll after the stop


def test_start_polling_survives_a_failing_read(tmp_path):
    case = WatchCase(tmp_path)

    def boom(_folder):
        case.reads += 1
        raise OSError("locked")

    case.watch.adapters = Adapters(read_folder=boom, clock=lambda: case.now)
    case.watch.start_polling(interval_s=0.02)
    deadline = time.monotonic() + 2.0
    while case.reads < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    case.watch.stop_polling()
    assert case.reads >= 2  # the loop keeps polling after a failed read
    assert case.watch.status()["state"] == STATE_ERROR


def test_harness_never_boots_a_mail_watch_by_default():
    """The suite's inert default: mail off means no watcher object at all,
    so no test can poll a real folder by accident."""
    booted = server_harness.Booted()
    try:
        assert booted.server.mail is None
        assert booted.server.mail_store is not None
        assert booted.server.outbox_dir.is_dir()  # tmp-owned, not the real outbox
    finally:
        booted.close()
