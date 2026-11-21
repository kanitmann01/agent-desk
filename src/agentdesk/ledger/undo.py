"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, tools/skill_ledger.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

Undo: put the earlier state back, and record having done so.

Hermes' rollback_entry is the shape kept here: read the entry, capture the
current state before touching anything, apply the reverse, and append the
inverse entry so the undo is itself recorded and undoable. The per-kind
work is a registry, so an unregistered kind fails closed with a sentence
instead of a guess.
"""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from agentdesk.inbox.core import UnknownCard
from agentdesk.ledger.store import Entry, Ledger, LedgerError

if TYPE_CHECKING:
    from agentdesk.server.app import AgentDeskServer

UndoFn = Callable[["AgentDeskServer", Entry, "bytes | None"], "bytes | None"]

UNDO: dict[str, UndoFn] = {}


def register(kind: str):
    """Register the reverse of one undo_kind; the function captures the
    current state, applies the reverse and returns the capture."""

    def decorator(fn: UndoFn) -> UndoFn:
        """Remember fn as the reverse of kind."""
        UNDO[kind] = fn
        return fn

    return decorator


def undo(
    server: "AgentDeskServer",
    ledger: Ledger,
    entry_id: str,
    *,
    actor: str = "user",
) -> Entry:
    """Undo one ledger entry and return the inverse entry just recorded.

    Fails closed: the current state is captured and stored before the
    reverse runs, and any failure there raises LedgerError with nothing
    changed. One undo per entry; the undo is itself an entry, so undoing it
    redoes the change. An unknown id raises LookupError (the API's 404).
    """
    with ledger._lock:
        entry = ledger.get(entry_id)
        if entry is None:
            raise LookupError("That change is not in the ledger.")
        if entry.undone_by is not None:
            raise LedgerError("That change was already undone.")
        reverse = UNDO.get(entry.undo_kind)
        if reverse is None:
            raise LedgerError("That change cannot be undone.")
        before = ledger.get_blob(entry.before_sha) if entry.before_sha is not None else None
        if entry.before_sha is not None and before is None:
            raise LedgerError("That change's earlier state was not captured, so it cannot be undone.")
        current = reverse(server, entry, before)
        redo_kind = {"card-added": "card-dismissed", "card-dismissed": "card-added"}.get(
            entry.undo_kind, entry.undo_kind,
        )
        recorded = ledger.record(
            actor=actor,
            action="ledger.undo",
            subject=entry.subject,
            why=f"Undo: {entry.why}",
            undo_kind=redo_kind,
            before=current,
            after=before,
            detail={"undoes": entry.id, "action": entry.action, "subject": entry.subject},
            undoes=entry.id,
        )
        return recorded


def _payload(entry: Entry, before: bytes | None) -> dict:
    """The captured JSON object the reverse needs, or a refusal.

    A change whose capture is missing or not an object cannot be reversed,
    so it raises instead of half-applying something guessed.
    """
    if before is None:
        raise LedgerError("That change's earlier state was not captured, so it cannot be undone.")
    try:
        data = json.loads(before)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise LedgerError("That change's earlier state was not captured, so it cannot be undone.")
    return data


def _capture_current(server: "AgentDeskServer", data: bytes) -> bytes:
    """Store the state as it is now, before the reverse changes it.

    If this capture cannot be written the undo raises and nothing follows:
    an undo that cannot say what it changed is not allowed to change it.
    """
    ledger = getattr(server, "ledger", None)
    if ledger is None:
        raise LedgerError("The ledger is not available, so nothing was changed.")
    try:
        ledger.put_blob(data)
    except LedgerError:
        raise LedgerError("The current state could not be captured, so nothing was changed.") from None
    return data


# -- settings -------------------------------------------------------------


@register("settings-key")
def _undo_settings_key(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """Put one settings key back to the value the change replaced."""
    data = _payload(entry, before)
    key = data.get("key")
    settings = getattr(server, "settings", None)
    if not isinstance(key, str) or "value" not in data or settings is None:
        raise LedgerError("That change's earlier settings were not captured, so it cannot be undone.")
    try:
        current_value = settings.get(key)
    except KeyError:
        raise LedgerError("That setting no longer exists, so it cannot be undone.") from None
    current = _capture_current(
        server, json.dumps({"key": key, "value": current_value}).encode("utf-8")
    )
    settings.set(key, data["value"])
    return current


# -- inbox cards ----------------------------------------------------------


def _card_json(server: "AgentDeskServer", card) -> bytes:
    """One card's payload as JSON, the shape both card kinds capture."""
    return json.dumps(card.to_json(server.inbox.now_ts()), ensure_ascii=False).encode("utf-8")


def _card_for(server: "AgentDeskServer", entry: Entry, before: bytes | None):
    """The card an entry is about, looked up by the id in its capture."""
    data = _payload(entry, before)
    card_id = data.get("id")
    if not isinstance(card_id, str) or not card_id:
        raise LedgerError("That change's card was not captured, so it cannot be undone.")
    try:
        return server.inbox.get(card_id)
    except (UnknownCard, AttributeError):
        raise LedgerError("That card is no longer in the inbox, so it cannot be undone.") from None


@register("card-added")
def _undo_card_added(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """The reverse of adding a card: dismiss it (the card stays visible as
    dismissed, so the history of the change is still there)."""
    card = _card_for(server, entry, before)
    current = _capture_current(server, _card_json(server, card))
    server.inbox.dismiss(card.id)
    return current


@register("card-dismissed")
def _undo_card_dismissed(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """The reverse of dismissing a card: reopen it as waiting.

    Agent dismissals have no 30-day recovery window (that limit belongs to
    the user's own dismiss button), so this uses reopen, not restore.
    """
    card = _card_for(server, entry, before)
    current = _capture_current(server, _card_json(server, card))
    server.inbox.reopen(card.id)
    return current
