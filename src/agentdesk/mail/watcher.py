"""The mail folder watcher: poll the folder, file digest and follow-ups.

The calendar bridge's timer pattern, with the mail specifics: injectable
adapters (the folder read and the clock) so every state runs in tests
against fixtures, a poll that re-reads the folder (the folder is the
source of truth; messages are never persisted), computes the digest and
follow-up deltas against the handled threads, and files inbox cards that
land under the interruption budget like any other card. One waiting
digest at a time, one follow-up card per thread, ever: polls do not
spray. There is no model adapter here and no body access anywhere: the
cards carry header metadata only.
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agentdesk.inbox.core import KIND_MAIL_DIGEST, KIND_MAIL_FOLLOW_UP
from agentdesk.inbox.store import InboxStore
from agentdesk.mail.core import (
    DIGEST_HOURS,
    FOLLOW_UP_DAYS,
    MAIL_USER,
    digest_details,
    follow_up_details,
    read_eml_folder_reported,
    recent_threads,
    with_threads,
)
from agentdesk.mail.store import MailStore

LOG = logging.getLogger("agentdesk.mail")

# Watch states, one plain-language story each.
STATE_UNCONFIGURED = "unconfigured"  # no folder chosen yet: the enable state
STATE_WATCHING = "watching"          # the folder reads, cards are current
STATE_ERROR = "error"                # the folder is missing or unreadable

POLL_INTERVAL_S = 1800.0  # the calendar cadence: every half hour

DIGEST_ORIGIN = (
    "Threads with a message in the last 24 hours. Headers only: message"
    " bodies are never read, and nothing here is sent anywhere."
)
FOLLOW_UP_ORIGIN = (
    "No message from you on this thread in {days} days. Deciding this"
    " card marks the thread handled."
)


@dataclass
class Adapters:
    """The side effects a poll needs; swap for fakes in tests. The
    reader returns the parsed messages (headers only) and how many
    files it had to skip, so a malformed export is visible without
    being fatal."""

    read_folder: Callable[[Path], "tuple[list, int]"]
    clock: Callable[[], float]


def default_adapters() -> Adapters:
    return Adapters(read_folder=read_eml_folder_reported, clock=time.time)


def resolve_folder(settings_value: str) -> Path | None:
    """The folder a poll reads: the settings choice first, then the
    AGENTDESK_MAIL_FOLDER environment override, else nothing. An empty
    or whitespace-only value counts as unset, in either place."""
    text = (settings_value or "").strip()
    if text:
        return Path(text)
    env = os.environ.get("AGENTDESK_MAIL_FOLDER", "").strip()
    if env:
        return Path(env)
    return None


class MailWatch:
    """One watched mail folder; poll reads it, the inbox shows the deltas."""

    def __init__(
        self,
        inbox: InboxStore,
        store: MailStore,
        adapters: Adapters | None = None,
        folder_provider: Callable[[], str] | None = None,
        audit_hook: Callable[[str, str, str], None] | None = None,
        follow_up_days: float = FOLLOW_UP_DAYS,
        digest_hours: float = DIGEST_HOURS,
        self_address: str = MAIL_USER,
    ) -> None:
        self.inbox = inbox
        self.store = store
        self.adapters = adapters if adapters is not None else default_adapters()
        self.folder_provider = folder_provider or (lambda: "")
        self.audit_hook = audit_hook
        self.follow_up_days = follow_up_days
        self.digest_hours = digest_hours
        self.self_address = self_address
        self._state = STATE_UNCONFIGURED
        self._cause = ""
        self._folder: str | None = None
        self._message_count = 0
        self._unparsed = 0
        self._digest: list[str] = []
        self._follow_ups: list[str] = []

    # -- the poll ---------------------------------------------------------

    def poll(self) -> dict:
        """One poll: resolve the folder, read it, compute the deltas,
        file the new cards. Every outcome returns the same shape: the
        status dict plus `created`, so callers never branch on which
        path answered."""
        folder = resolve_folder(self.folder_provider())
        if folder is None:
            self._state, self._cause = STATE_UNCONFIGURED, ""
            return self._settled()
        # The folder is known before the read: a failed first contact is
        # audited exactly like a successful one (the calendar's rule).
        self._folder = str(folder)
        try:
            messages, unparsed = self.adapters.read_folder(folder)
        except OSError as exc:
            self._state = STATE_ERROR
            self._cause = (
                "The mail folder could not be read: "
                f"{exc}. Check the path in settings."
            )
            self._audit("mail.poll", "error")
            return self._settled()
        self._unparsed = unparsed
        self._message_count = len(messages)
        self._audit("mail.poll", "ok")
        messages = with_threads(messages)
        now = self.adapters.clock()
        handled = self.store.handled()
        self._digest = recent_threads(messages, now, hours=self.digest_hours)
        self._follow_ups = [
            d["thread"] for d in follow_up_details(
                messages, handled, now, days=self.follow_up_days,
                self_address=self.self_address,
            )
        ]
        created = self._file_cards(messages, handled, now)
        self._state = STATE_WATCHING
        status = self.status()
        status["created"] = created
        return status

    def _settled(self) -> dict:
        """The non-watching outcomes, in the same shape as a watching
        one: status plus created (always 0 there, nothing was filed)."""
        status = self.status()
        status["created"] = 0
        return status

    def retest(self) -> dict:
        return self.poll()

    def _file_cards(self, messages: list, handled: set[str], now: float) -> int:
        """The card deltas: at most one waiting digest, one follow-up per
        thread ever (waiting or decided counts), so polls never spray."""
        created = 0
        if self._digest and not self._digest_exists(self._digest):
            self.inbox.add(
                kind=KIND_MAIL_DIGEST,
                origin=DIGEST_ORIGIN,
                title=f"Mail digest: {len(self._digest)} threads active today",
                body="\n".join(self._digest),
                action_label="Got it",
                meta={
                    "threads": list(self._digest),
                    "messageCount": self._message_count,
                },
            )
            created += 1
        for detail in follow_up_details(
            messages, handled, now, days=self.follow_up_days,
            self_address=self.self_address,
        ):
            if self._card_for_thread_exists(detail["thread"]):
                continue
            self.inbox.add(
                kind=KIND_MAIL_FOLLOW_UP,
                origin=FOLLOW_UP_ORIGIN.format(days=self.follow_up_days),
                title=detail["thread"],
                body=f"Latest from {detail['from']} on this thread; nothing from you since.",
                action_label="Handled",
                meta={
                    "thread": detail["thread"],
                    "messageId": detail["messageId"],
                    "latestFrom": detail["from"],
                    "latestTs": detail["dateTs"],
                },
            )
            created += 1
        return created

    def _digest_exists(self, digest: list[str]) -> bool:
        wanted = sorted(digest)
        # One waiting digest at a time, whatever set it carries: a second
        # would only spend the user's attention twice.
        if any(c.kind == KIND_MAIL_DIGEST for c in self.inbox.waiting(include_snoozed=True)):
            return True
        # The exact rule: a WAITING digest suppresses any successor, and
        # a DISMISSED digest suppresses its own set (hiding one must not
        # mint a twin, the briefs rule). An ACCEPTED digest does not
        # suppress: its threads are still active, so the next poll
        # re-files the digest while the 24-hour window holds.
        return any(
            c.kind == KIND_MAIL_DIGEST and sorted(c.meta.get("threads", [])) == wanted
            for c in self.inbox.dismissed()
        )

    def _card_for_thread_exists(self, thread: str) -> bool:
        cards = self.inbox.waiting(include_snoozed=True) + self.inbox.dismissed()
        return any(
            c.kind == KIND_MAIL_FOLLOW_UP and c.meta.get("thread") == thread
            for c in cards
        )

    # -- reads ------------------------------------------------------------

    def view(self) -> dict:
        """Everything the mail page shows, from one read-only folder read.
        Files nothing and audits nothing: reading is not polling."""
        folder = resolve_folder(self.folder_provider())
        payload = {
            "state": STATE_UNCONFIGURED,
            "cause": "",
            "folder": None,
            "messages": [],
            "digest": [],
            "followUps": [],
            "handled": sorted(self.store.handled()),
            "followUpDays": self.follow_up_days,
        }
        if folder is None:
            return payload
        try:
            raw_messages, _unparsed = self.adapters.read_folder(folder)
        except OSError as exc:
            payload["state"] = STATE_ERROR
            payload["cause"] = f"The mail folder could not be read: {exc}"
            return payload
        messages = with_threads(raw_messages)
        now = self.adapters.clock()
        handled = self.store.handled()
        payload.update({
            "state": STATE_WATCHING,
            "folder": str(folder),
            "messages": messages,
            "digest": digest_details(messages, now, hours=self.digest_hours),
            "followUps": follow_up_details(
                messages, handled, now, days=self.follow_up_days,
                self_address=self.self_address,
            ),
            "handled": sorted(handled),
        })
        return payload

    def status(self) -> dict:
        """The watcher payload: state, folder, last poll's thread sets."""
        return {
            "configured": self._folder is not None or self._state != STATE_UNCONFIGURED,
            "state": self._state,
            "cause": self._cause,
            "folder": self._folder,
            "messageCount": self._message_count,
            "unparsedFiles": self._unparsed,
            "digestThreads": list(self._digest),
            "followUps": list(self._follow_ups),
            "handledCount": len(self.store.handled()),
        }

    # -- the audit hook ----------------------------------------------------

    def _audit(self, action: str, status: str) -> None:
        """Record a brokered touch when the hook is wired. The target is
        the folder's own name, never a message: the log names the touch,
        not the mail."""
        if self.audit_hook is None or self._folder is None:
            return
        name = self._folder.replace("\\", "/").rsplit("/", 1)[-1]
        try:
            self.audit_hook(action, name, status)
        except Exception:  # noqa: BLE001 - auditing must never break the watcher
            LOG.exception("audit hook failed")

    # -- the timer, the calendar bridge's pattern --------------------------

    def start_polling(self, interval_s: float = POLL_INTERVAL_S) -> None:
        """Poll on a daemon timer; the folder changes itself, this keeps up."""
        self.stop_polling()
        self._stop = threading.Event()
        self._timer = threading.Timer(interval_s, self._loop, args=(interval_s,))
        self._timer.daemon = True
        self._timer.start()

    def _loop(self, interval_s: float) -> None:
        if self._stop.is_set():
            return
        try:
            self.poll()
        except Exception:  # noqa: BLE001 - the loop survives anything
            LOG.exception("mail poll failed")
        if not self._stop.is_set():
            self._timer = threading.Timer(interval_s, self._loop, args=(interval_s,))
            self._timer.daemon = True
            self._timer.start()

    def stop_polling(self) -> None:
        stop = getattr(self, "_stop", None)
        if stop is not None:
            stop.set()
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.cancel()
            self._timer = None
