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
from agentdesk.memory.core import UnknownFact
from agentdesk.repetition.cluster import pattern_hash
from agentdesk.repetition.skills import SkillError

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
        redo_kind = {
            "card-added": "card-dismissed",
            "card-dismissed": "card-added",
            "inbox-rows": "inbox-rows-deleted",
            "inbox-rows-deleted": "inbox-rows",
        }.get(entry.undo_kind, entry.undo_kind)
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


# -- desk-check set-aside rows -------------------------------------------


def _rows_payload(entry: Entry, before: bytes | None) -> list[dict]:
    """The captured raw inbox rows a set-aside change removed, or a refusal."""
    if before is None:
        raise LedgerError("That change's earlier state was not captured, so it cannot be undone.")
    try:
        data = json.loads(before)
    except ValueError:
        data = None
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise LedgerError("That change's earlier state was not captured, so it cannot be undone.")
    return data


@register("inbox-rows")
def _undo_inbox_rows(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """Put the set-aside inbox rows back exactly as they were stored.

    The rows are re-inserted with their ids and every column, so this build
    detects them again and the next check offers to set them aside again.
    """
    rows = _rows_payload(entry, before)
    inbox = getattr(server, "inbox", None)
    if inbox is None:
        raise LedgerError("The inbox is not available, so the rows cannot be put back.")
    inbox.insert_raw(rows)
    return _capture_current(server, before)


@register("inbox-rows-deleted")
def _undo_inbox_rows_deleted(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """The inverse used when undoing the undo: remove the rows again."""
    rows = _rows_payload(entry, before)
    inbox = getattr(server, "inbox", None)
    if inbox is None:
        raise LedgerError("The inbox is not available, so the rows cannot be put back.")
    inbox.delete_rows([row["id"] for row in rows])
    return _capture_current(server, before)


# -- source wiring --------------------------------------------------------


@register("version-pointer")
def _undo_version_pointer(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """Point the launcher back at the version the update replaced."""
    _payload(entry, before)
    from agentdesk.server.app import default_data_dir
    from agentdesk.update import rollback_now, stage

    data_dir = default_data_dir()
    pointer = stage.read_pointer(data_dir) or {}
    current = _capture_current(
        server, json.dumps(pointer, sort_keys=True).encode("utf-8")
    )
    # The same rollback a failed first start gets: pointer back, corrupt
    # SQLite files restored from the snapshot, and the state names it.
    rollback_now(server, data_dir)
    return current


@register("wiring")
def _undo_wiring(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """Point the workbook watch and calendar back at the paths it replaced.

    The current paths are captured before anything is touched; a None path
    means that source was not wired, so the reverse clears it (only through
    the watcher's own clear call, never by guessing at stored rows).
    """
    data = _payload(entry, before)
    excel = getattr(server, "excel", None)
    calendar = getattr(server, "calendar", None)
    current = {
        "excel": excel.registered_path if excel is not None else None,
        "calendar": calendar.explicit_path() if calendar is not None else None,
    }
    current_bytes = _capture_current(
        server, json.dumps(current, sort_keys=True).encode("utf-8")
    )
    if "excel" in data:
        path = data["excel"]
        if excel is None and path is not None:
            raise LedgerError("The workbook watch is not available, so the wiring cannot be put back.")
        if excel is not None:
            if path:
                excel.register(str(path))
            else:
                excel.clear_registered_path()
    if "calendar" in data:
        path = data["calendar"]
        if calendar is None and path is not None:
            raise LedgerError("The calendar is not available, so the wiring cannot be put back.")
        if calendar is not None:
            if path:
                calendar.set_explicit_path(str(path))
            else:
                calendar.clear_explicit_path()
            calendar.retest()
    return current_bytes


# -- the learned profile (spec 016 ticket 08) ------------------------------


@register("learned-profile")
def _undo_learned_profile(server: "AgentDeskServer", entry: Entry,
                          before: bytes | None) -> bytes | None:
    """Put the whole learned profile document back, exactly as captured.

    The capture is the store's own raw() bytes, so the restore rewrites
    the document wholesale and no line or topic is reassembled by hand.
    The latch written when the topic was learned is not touched, which
    is what keeps a removed topic from ever coming back."""
    store = getattr(server, "learned_profile", None)
    if store is None:
        raise LedgerError("The learned profile is not available, so nothing was changed.")
    _payload(entry, before)  # a capture that is not an object fails closed
    current = _capture_current(server, store.raw())
    store.restore(before)
    return current


# -- memory auto-save (spec 016 ticket 08) ----------------------------------


@register("memory-fact")
def _undo_memory_fact(server: "AgentDeskServer", entry: Entry,
                      before: bytes | None) -> bytes | None:
    """The reverse of one auto-saved fact: delete exactly that fact.

    The capture names the fact id and nothing else, and the deletion is
    the memory store's own fact removal: remove_facts cleans the entity
    edges, the observation citations, the orphaned observations and the
    entities left with no mentions, which the store's plain delete
    leaves dangling (it drops only the fact row and its observation
    citations). A fact that is already gone refuses the undo instead of
    guessing."""
    data = _payload(entry, before)
    memory = getattr(server, "memory", None)
    fact_id = data.get("id")
    if memory is None or isinstance(fact_id, bool) or not isinstance(fact_id, int):
        raise LedgerError("That change's fact was not captured, so it cannot be undone.")
    try:
        stored = memory.get(fact_id)
    except UnknownFact:
        raise LedgerError(
            "That fact is no longer in memory, so it cannot be undone.") from None
    current = _capture_current(
        server, json.dumps({"id": fact_id, "text": getattr(stored, "text", "")},
                           ensure_ascii=False).encode("utf-8")
    )
    memory.remove_facts([fact_id])


# -- skills ----------------------------------------------------------------


def _skill_blob(skill: dict) -> bytes:
    """One skill's undoable state as the capture both skill kinds share."""
    return json.dumps({
        "id": skill["id"],
        "name": skill["name"],
        "description": skill["description"],
        "prompt": skill["prompt"],
        "active": bool(skill["active"]),
        "created_by": skill.get("created_by", "user"),
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _skill_for_undo(server: "AgentDeskServer", data: dict):
    """The skill a capture names, or the refusal when it is not there."""
    skills = getattr(server, "skills", None)
    skill_id = data.get("id")
    if skills is None or not isinstance(skill_id, int):
        raise LedgerError("The skills store is not available, so the skill cannot be undone.")
    skill = skills.get(skill_id)
    if skill is None:
        raise LedgerError("That skill is no longer in the store, so it cannot be undone.")
    return skills, skill


@register("skill-version")
def _undo_skill_version(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """Restore the prompt and the active flag a skill change replaced.

    The reverse runs through the store's own version-writing calls, so the
    undo is a new version row, never a rewrite: deactivate for a change
    that activated, activate for one that deactivated, and refine for a
    prompt change (the before blob holds the earlier prompt).
    """
    data = _payload(entry, before)
    skills, skill = _skill_for_undo(server, data)
    current = _capture_current(server, _skill_blob(skill))
    target_active = bool(data.get("active", True))
    try:
        if target_active and not skill["active"]:
            skills.activate(
                name=data.get("name") or skill["name"],
                description=data.get("description") or skill["description"],
                prompt=data.get("prompt") or skill["prompt"],
                created_by=data.get("created_by", "user"),
            )
        elif not target_active and skill["active"]:
            skills.deactivate(skill["id"])
            # A deactivating undo is a declined pattern, the run surface's
            # own rule: cool the pattern down or the next consolidation
            # run re-creates the identical skill at once.
            consolidator = getattr(server, "consolidator", None)
            if consolidator is not None:
                consolidator.dismiss_cooldown(pattern_hash(skill["prompt"]))
        skill_now = skills.get(skill["id"])
        target_prompt = data.get("prompt")
        if (skill_now is not None and isinstance(target_prompt, str)
                and target_prompt and skill_now["prompt"] != target_prompt):
            skills.refine(skill["id"], target_prompt,
                          note="restored the earlier prompt (undo)")
    except SkillError as exc:
        raise LedgerError(f"The skill refused the undo: {exc}") from None
    return current


@register("skill-state")
def _undo_skill_state(server: "AgentDeskServer", entry: Entry, before: bytes | None) -> bytes | None:
    """Put one skill back on the state and active flag a curator change
    replaced.

    The pair is restored together, never just the state word: a capture
    that says stale and running must come back running (stale keeps the
    flag it finds, so re-deriving it from the post-change row would leave
    an archived-then-undone skill off the dashboard), and one that says a
    state with active=0 (a deactivated skill the curator marked stale)
    must not be resurrected by set_state's active=1 rule.
    """
    data = _payload(entry, before)
    skills, skill = _skill_for_undo(server, data)
    state = data.get("state")
    if not isinstance(state, str) or not isinstance(data.get("active"), bool):
        raise LedgerError("That change's earlier skill state was not captured, so it cannot be undone.")
    current = _capture_current(
        server,
        json.dumps({"id": skill["id"], "state": skill["state"],
                    "active": bool(skill["active"])}, sort_keys=True).encode("utf-8"),
    )
    try:
        skills.set_state(skill["id"], state, active=data["active"])
    except SkillError as exc:
        raise LedgerError(f"The skill refused the undo: {exc}") from None
    return current
