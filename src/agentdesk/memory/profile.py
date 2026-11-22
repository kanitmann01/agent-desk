"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, tools/memory_tool_store.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The learned profile: what the desk can honestly say it learned about
you, kept in `<data>/profile.learned.json` beside the stated preferences
and never merged into the file they live in. Two things are learned
today: focus topics, when five or more similar asks name a memory entity
(ticket 08), and profile lines from reviewed activity (ticket 09).

The budget is Hermes' bounded-memory idea ported: the entry texts joined
with the `\\n§\\n` delimiter (`ENTRY_DELIMITER`) must stay within
`BUDGET_CHARS` (the USER-profile `user_char_limit` of 1375), and a write
that would exceed it is refused with the current entries listed so the
caller can consolidate. Topics follow the stated store's own limits
(`MAX_TOPICS`, `MAX_TOPIC_CHARS`). Every read merges the stated and
learned topics, stated first, deduped case-insensitively.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

VERSION = 1

# The topic limits, kept equal to insight/preferences.py's MAX_TOPICS and
# MAX_TOPIC_CHARS (a test pins the two together, the way settings.py and
# memory/embed.py pin their shared model default). They live here rather
# than imported because insight/__init__ imports this module's readers,
# and a memory module importing back would close a circle.
MAX_TOPICS = 10
MAX_TOPIC_CHARS = 40

# The user-profile budget and entry delimiter, ported from Hermes'
# tools/memory_tool_store.py (user_char_limit 1375, ENTRY_DELIMITER).
BUDGET_CHARS = 1375
ENTRY_DELIMITER = "\n§\n"


class OverBudget(Exception):
    """A learned line that would not fit. `entries` lists the current
    entry texts, the way Hermes' over-budget failure carried them, so
    the caller can merge or shorten instead of retrying blind."""

    def __init__(self, entries: list[str], message: str | None = None) -> None:
        """Carry the current texts and a sentence naming both sizes."""
        self.entries = list(entries)
        if message is None:
            message = (
                f"The learned profile is over its {BUDGET_CHARS} character "
                "budget; merge or shorten the current entries."
            )
        super().__init__(message)


def _empty_document() -> dict:
    """The document a fresh desk answers: nothing learned, nothing guessed."""
    return {"version": VERSION, "updatedAt": 0.0, "entries": [], "focusTopics": []}


def _texts(document: dict) -> list[str]:
    """The stored entry texts in order, the list the budget is counted over."""
    return [str(entry.get("text", "")) for entry in document.get("entries", [])]


class LearnedProfileStore:
    """Reads and writes `<data>/profile.learned.json`; one file, one desk.

    Every mutating method holds one lock across its read-mutate-write:
    the loop thread learns while request threads remove (the removal
    route, Undo), and without it a removal landing between one writer's
    document read and its save is silently overwritten. The tmp then
    os.replace save already keeps a concurrent reader on the whole old
    or whole new file; the lock is for the writers.

    `seal` and `unseal` are accepted for the open question this ticket
    leaves unverified (whether the file itself should be sealed when the
    memory bank is) and stay unused: the ledger already seals the
    captures recorded under a `learned` subject, which is the Undo path
    this store actually feeds.
    """

    def __init__(self, path: Path, *, clock=time.time, seal=None, unseal=None) -> None:
        """Bind the store to its file; nothing is read yet."""
        self.path = Path(path)
        self.clock = clock
        self.seal = seal
        self.unseal = unseal
        # Held across every read-mutate-write below; reads (document,
        # raw) stay outside it, since the atomic replace already gives
        # them a whole file.
        self._lock = threading.Lock()

    def document(self) -> dict:
        """The stored document over defaults, judged field by field.

        A missing or unparsable file reads as the empty document, the
        same tolerance `PreferenceStore.read` shows."""
        document = _empty_document()
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return document
        if not isinstance(stored, dict):
            return document
        if stored.get("version") != VERSION:
            return document
        merged = _empty_document()
        entries = stored.get("entries")
        if isinstance(entries, list):
            merged["entries"] = [e for e in entries if isinstance(e, dict)]
        topics = stored.get("focusTopics")
        if isinstance(topics, list):
            merged["focusTopics"] = [t for t in topics if isinstance(t, dict)]
        updated = stored.get("updatedAt")
        if isinstance(updated, (int, float)) and not isinstance(updated, bool):
            merged["updatedAt"] = float(updated)
        return merged

    def raw(self) -> bytes:
        """The document as JSON bytes, the shape a ledger capture takes."""
        return json.dumps(self.document(), ensure_ascii=False).encode("utf-8")

    def restore(self, raw: bytes) -> None:
        """Write a captured document back, exactly as it was stored.

        The bytes come from this store's own captures, so a document
        that does not parse is a failure, not a guess."""
        stored = json.loads(bytes(raw).decode("utf-8"))
        if not isinstance(stored, dict):
            raise ValueError("a learned profile capture must be an object")
        with self._lock:
            self._save(stored)

    # -- focus topics -------------------------------------------------------

    def add_topic(self, topic: str, asks: int) -> bool:
        """Learn one focus topic; False when present, over the shared
        topic cap, or longer than the stated store allows."""
        line = str(topic or "").strip()
        with self._lock:
            document = self.document()
            topics = document["focusTopics"]
            if not line or len(line) > MAX_TOPIC_CHARS:
                return False
            if any(str(t.get("topic", "")).lower() == line.lower() for t in topics):
                return False
            if len(topics) >= MAX_TOPICS:
                return False
            topics.append({"topic": line, "learnedFrom": {"asks": int(asks)},
                           "ts": self.clock()})
            document["updatedAt"] = self.clock()
            self._save(document)
            return True

    def remove_topic(self, topic: str) -> bool:
        """Drop one learned topic, case-insensitively; True when it went."""
        line = str(topic or "").strip().lower()
        with self._lock:
            document = self.document()
            kept = [t for t in document["focusTopics"]
                    if str(t.get("topic", "")).lower() != line]
            if len(kept) == len(document["focusTopics"]):
                return False
            document["focusTopics"] = kept
            document["updatedAt"] = self.clock()
            self._save(document)
            return True

    # -- learned lines (used by ticket 09) ----------------------------------

    def add_entry(self, text: str, learned_from: dict, by: str) -> dict:
        """Append one learned line, refusing when the budget would break.

        The refusal carries the current entries, the shape Hermes' add
        returns over budget, so ticket 09's apply step can merge."""
        line = str(text or "").strip()
        with self._lock:
            document = self.document()
            current = _texts(document)
            if not line:
                raise ValueError("a learned line cannot be empty")
            if len(ENTRY_DELIMITER.join(current + [line])) > BUDGET_CHARS:
                raise OverBudget(current)
            entry = {
                "id": f"p-{os.urandom(2).hex()}",
                "text": line,
                "learnedFrom": dict(learned_from or {}),
                "ts": self.clock(),
                "by": str(by or "review"),
            }
            document["entries"].append(entry)
            document["updatedAt"] = self.clock()
            self._save(document)
            return entry

    def patch_entry(self, entry_id: str, text: str, learned_from: dict) -> dict:
        """Replace one line's text and provenance, budget checked first."""
        line = str(text or "").strip()
        with self._lock:
            document = self.document()
            index = self._index_of(document, entry_id)
            if index is None:
                raise LookupError(f"no learned line {entry_id!r}")
            if not line:
                raise ValueError("a learned line cannot be empty")
            patched = _texts(document)
            patched[index] = line
            if len(ENTRY_DELIMITER.join(patched)) > BUDGET_CHARS:
                raise OverBudget(_texts(document))
            entry = document["entries"][index]
            entry["text"] = line
            entry["learnedFrom"] = dict(learned_from or {})
            document["updatedAt"] = self.clock()
            self._save(document)
            return entry

    def remove_entry(self, entry_id: str) -> bool:
        """Drop one learned line; True when it went."""
        with self._lock:
            document = self.document()
            index = self._index_of(document, entry_id)
            if index is None:
                return False
            del document["entries"][index]
            document["updatedAt"] = self.clock()
            self._save(document)
            return True

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _index_of(document: dict, entry_id: str) -> int | None:
        """The position of one entry id, or None when it never existed."""
        for index, entry in enumerate(document.get("entries", [])):
            if entry.get("id") == entry_id:
                return index
        return None

    def _save(self, document: dict) -> None:
        """Write the document atomically: a .tmp sibling, then os.replace,
        the same discipline PreferenceStore._save uses."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)


def merged_topics(stated: list, learned: list) -> list[str]:
    """The topics a reading sees: the stated ones, then the learned ones,
    deduped case-insensitively, capped the way the stated store caps."""
    merged: list[str] = []
    for topic in list(stated or []) + [t.get("topic") for t in (learned or [])
                                       if isinstance(t, dict)]:
        if not isinstance(topic, str):
            continue
        line = topic.strip()
        if not line:
            continue
        if line.lower() in {seen.lower() for seen in merged}:
            continue
        merged.append(line)
        if len(merged) >= MAX_TOPICS:
            break
    return merged


def learned_lines(document: dict) -> list[str]:
    """The learned lines as prompt lines: the texts, in stored order."""
    texts = _texts(document or {})
    return [line for text in texts if (line := str(text).strip())]
