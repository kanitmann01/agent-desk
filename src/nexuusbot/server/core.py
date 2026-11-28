"""Shared data model and constants for the local web app skeleton.

The walking skeleton answers three questions before any real widget exists:
can the app boot from one double-click, is the localhost surface hardened
from the first request, and does the shell already speak the design
language. Everything decisive here is a pure data structure so the request
guard, session store and page renderer stay testable without a browser.
"""

import re
from dataclasses import dataclass
from pathlib import Path

SPA_DIR = Path(__file__).resolve().parent / "static" / "spa"

COOKIE_NAME = "agentdesk_session"
SESSION_MAX_AGE = 12 * 60 * 60  # 12 hours, then a fresh auth exchange

# Preferred listen port; when taken the server falls back to an ephemeral
# one so two copies never fight (the auth URL always names the real port).
PREFERRED_PORT = 8765

# The only hostnames the surface answers to. The bind itself is pinned to
# 127.0.0.1 in app.py; this tuple is what Host/Origin validation allows.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")

# Source identifiers (stable keys used by health and the later data tickets)
SRC_EXCEL = "excel-watch"
SRC_CALENDAR = "calendar-bridge"
SRC_RESEARCH = "research-endpoint"
SOURCE_IDS = (SRC_EXCEL, SRC_CALENDAR, SRC_RESEARCH)

# Health statuses, computed live at request time (see app.live_sources):
# a source is connected when its real watch says so, never by default. A
# source wired to the labelled sample set is "sample": it keeps the cards
# alive, and it is never counted as live.
STATUS_CONNECTED = "connected"
STATUS_NOT_CONNECTED = "not_connected"
STATUS_SAMPLE = "sample"

# Widget freshness states (the contract the shell renders on every card).
FRESH = "fresh"          # green dot, data is current
ATTENTION = "attention"  # amber dot, refresh blocked or stale (see PRD)
SAMPLE = "sample"        # demo data, labeled as such, never mistaken for live

FRESHNESS_STATUSES = (FRESH, ATTENTION, SAMPLE)


def _active_version_dir(record: dict) -> Path:
    """The directory of the version the user actually runs (the same
    rule the runtime applies: after rollback that is not the newest)."""
    active = record.get("active_version")
    for version in record.get("versions", []):
        if version["version"] == active:
            return Path(version["dir"])
    return Path(record["versions"][-1]["dir"])


def plain_preview(text: str, limit: int = 140) -> str:
    """A one-line plain-text preview of a draft for the audit log: the
    donor approvals module's plainText. Tags and entities out, whitespace
    collapsed, capped, so the log never carries markup."""
    stripped = re.sub(r"<[^>]*>", " ", text)
    stripped = re.sub(r"&[a-zA-Z]+;", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()[:limit]


def count_noun(value: int, noun: str) -> str:
    """One counted noun, plural s unless the count is exactly one.

    Zero takes the plural, as English does.
    """
    return f"{value} {noun}" + ("" if value == 1 else "s")


def bounded_text(text: str, limit: int) -> str:
    """One value cut to a character budget on a single line.

    Whitespace runs, newlines included, collapse to one space before measuring, and an
    over-long value keeps limit - 1 characters plus an ellipsis, so the result never
    exceeds the budget.
    """
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


@dataclass(frozen=True)
class SourceStatus:
    """One data source's health entry: who it is and whether it is wired."""

    id: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class Freshness:
    """The freshness contract every widget card carries in its header.

    The shell renders the status dot and the stamp from these fields and
    exposes them as data attributes, so tests and later live-refresh code
    can assert the contract from rendered HTML alone.
    """

    status: str
    stamp: str
    updated_iso: str

    def __post_init__(self) -> None:
        """Reject a status the shell has no dot for.

        Freshness is built from watcher state strings, so a state that arrives here
        without a FRESHNESS_STATUSES entry fails at construction instead of rendering a
        dot no renderer can label.
        """
        if self.status not in FRESHNESS_STATUSES:
            raise ValueError(f"unknown freshness status: {self.status!r}")
