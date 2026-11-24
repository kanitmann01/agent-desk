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
            # The fixture mailbox's user, as the settings field configures it.
            self_address="employee@example.com",
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


def test_without_a_configured_address_no_follow_up_cards_and_the_status_says_so(tmp_path):
    """Self-detection off is honest: the digest still works, the
    follow-up set stays empty (it cannot know which threads the user
    answered), and the status names the missing configuration."""
    case = WatchCase(tmp_path)
    case.watch._self_address = ""  # as an unset settings field reads
    write_message(case.folder, "<f1@example.com>", "Thread one", "Thu, 05 Nov 2026 12:00:00 GMT")
    write_message(case.folder, "<f2@example.com>", "Re: Thread one", "Fri, 06 Nov 2026 12:00:00 GMT",
                  in_reply_to="<f1@example.com>")
    # A thread active today, so the digest has something to file.
    write_message(case.folder, "<f3@example.com>", "Today", "Wed, 11 Nov 2026 08:00:00 GMT")
    status = case.watch.poll()
    assert status["state"] == STATE_WATCHING
    assert status["selfDetection"] is False
    assert status["followUps"] == []
    kinds = [c.kind for c in case.inbox.waiting()]
    assert KIND_MAIL_FOLLOW_UP not in kinds
    assert KIND_MAIL_DIGEST in kinds  # the digest never needed the address


def test_the_self_address_is_re_read_from_the_provider_each_poll(tmp_path):
    """A settings save applies without a restart, like the folder."""
    case = WatchCase(tmp_path)
    case.watch._self_address = ""
    case.watch.self_address_provider = lambda: "employee@example.com"
    write_message(case.folder, "<f2@example.com>", "Re: Thread one", "Fri, 06 Nov 2026 12:00:00 GMT")
    case.watch.poll()
    case.watch.self_address_provider = lambda: ""
    assert case.watch.self_address == ""
    status = case.watch.status()
    assert status["selfDetection"] is False


# -- the Outlook alert feeder, injected before the folder read -------------


def test_the_feeder_runs_once_before_the_folder_read_and_lands_in_status(tmp_path):
    case = WatchCase(tmp_path)
    write_message(case.folder, "<a1@example.com>", "Alert", "Wed, 11 Nov 2026 08:00:00 GMT")
    calls = []

    def feeder():
        calls.append(case.reads)  # 0 means the folder has not been read yet
        return {
            "collector": "notification-store",
            "platform": "test-os",
            "lastRunTs": case.now,
            "lastResult": "ok",
            "lastError": "",
            "written": 1,
        }

    case.watch.feeder = feeder
    status = case.watch.poll()
    assert calls == [0]
    assert status["fetch"]["collector"] == "notification-store"
    assert status["fetch"]["written"] == 1
    assert case.watch.view()["fetch"] == status["fetch"]
    assert case.audit == [("mail.fetch", "mail", "ok"), ("mail.poll", "mail", "ok")]


def test_a_failing_feeder_never_stops_the_folder_read(tmp_path):
    case = WatchCase(tmp_path)
    write_message(case.folder, "<a1@example.com>", "Alert", "Wed, 11 Nov 2026 08:00:00 GMT")

    def feeder():
        raise RuntimeError("the notification store is locked")

    case.watch.feeder = feeder
    status = case.watch.poll()
    assert status["state"] == STATE_WATCHING
    assert status["messageCount"] == 1  # the folder was read anyway
    assert status["fetch"]["lastResult"] == "error"
    assert "the notification store is locked" in status["fetch"]["lastError"]
    assert case.audit == [("mail.fetch", "mail", "error"), ("mail.poll", "mail", "ok")]


def test_no_feeder_runs_without_a_folder_and_status_says_so(tmp_path):
    case = WatchCase(tmp_path, mailbox=None)
    case.watch.folder_provider = lambda: ""
    calls = []
    case.watch.feeder = lambda: calls.append(1) or {"lastResult": "ok"}
    status = case.watch.poll()
    assert status["state"] == STATE_UNCONFIGURED
    assert calls == []
    assert status["fetch"] is None


def test_the_feeder_path_imports_no_network_or_model_client():
    """The structural half of the privacy promise: the watcher and the
    feeder core cannot reach a socket or the model client."""
    import agentdesk.feeder.runner as runner
    import agentdesk.mail.watcher as watcher

    for module in (runner, watcher):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for banned in ("import socket", "import urllib", "import requests",
                       "http.client", "agentdesk.llm"):
            assert banned not in source, (module.__name__, banned)


def test_a_seeded_fetch_status_survives_a_restart(tmp_path):
    """The runner's status file is passed back at construction, so the
    Settings card does not read Not run yet after a restart."""
    case = WatchCase(tmp_path)
    seeded = {
        "collector": "notification-store",
        "platform": "test-os",
        "lastRunTs": 1700000000.0,
        "lastResult": "ok",
        "lastError": "",
        "written": 2,
        "coverageFromTs": None,
        "coverageToTs": None,
    }
    watch = MailWatch(
        inbox=case.inbox,
        store=case.store,
        adapters=case.watch.adapters,
        folder_provider=lambda: str(case.folder),
        fetch_status=seeded,
    )
    assert watch.status()["fetch"] == seeded


def test_a_corrupt_feeder_status_file_is_ignored(monkeypatch, tmp_path):
    from agentdesk.server.app import _read_feeder_status

    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path))
    assert _read_feeder_status() is None  # no file yet
    (tmp_path / "outlook-feeder.json").write_text("{not json", encoding="utf-8")
    assert _read_feeder_status() is None


def _fetch_once(tmp_path, result):
    """One fetch-now before the first poll, with the feeder faked."""
    case = WatchCase(tmp_path)
    case.watch.feeder = lambda: dict(result)
    case.watch.fetch_now()
    return case


def test_an_ok_fetch_is_audited_against_the_resolved_folder(tmp_path):
    case = _fetch_once(tmp_path, {
        "lastResult": "ok", "collector": "notification-store",
        "written": 1, "lastError": "",
    })
    # No poll ran yet, so the target comes from the folder provider.
    assert case.audit == [("mail.fetch", "mail", "ok")]


def test_an_error_fetch_is_audited_as_an_error(tmp_path):
    case = _fetch_once(tmp_path, {
        "lastResult": "error", "collector": "", "written": 0,
        "lastError": "The pass failed.",
    })
    assert case.audit == [("mail.fetch", "mail", "error")]


def test_unavailable_and_busy_fetches_are_not_audited(tmp_path):
    """Nothing was touched in either outcome, so no audit row claims a touch."""
    for name, result in (
        ("unavailable", {"lastResult": "unavailable"}),
        ("busy", {"lastResult": "busy"}),
    ):
        folder = tmp_path / name
        folder.mkdir()
        case = _fetch_once(folder, result)
        assert case.audit == [], result


def test_a_fetch_with_no_folder_configures_no_audit_target(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTDESK_MAIL_FOLDER", raising=False)
    case = WatchCase(tmp_path)
    case.watch.folder_provider = lambda: ""
    case.watch.feeder = lambda: {"lastResult": "ok"}
    case.watch.fetch_now()
    assert case.audit == []
