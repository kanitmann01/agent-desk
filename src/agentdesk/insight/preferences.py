"""The user's stated preferences: one small typed document, nothing inferred.

A preference is only ever what the user typed on Settings. The store
refuses unknown keys and values outside a vocabulary with a named code, so
a typo cannot become a silent no-op, and every read merges defaults so a
half-written file still yields a complete document.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

VERSION = 1

CHART = ("auto", "bar", "line", "table")
REPLY_TONES = ("direct", "warm", "formal")
REPLY_LENGTHS = ("one-line", "short", "paragraph")
DENSITIES = ("quiet", "normal", "chatty")

MAX_TOPICS = 10
MAX_TOPIC_CHARS = 40
PREP_MINUTES = (0, 120)

FIELDS = ("chart", "replyTone", "replyLength", "insightDensity", "focusTopics", "prepMinutes")

_VOCABULARY = {
    "chart": CHART,
    "replyTone": REPLY_TONES,
    "replyLength": REPLY_LENGTHS,
    "insightDensity": DENSITIES,
}


class PreferencesError(Exception):
    """A refused write. `code` is what a client may branch on; `message`
    is the sentence shown next to the Settings field."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        """Carry the stable code a client branches on, the sentence shown
        beside the Settings field, and the HTTP status to answer with."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def defaults() -> dict:
    """A fresh defaults document. A function, not a constant: the topics
    list is mutable and one shared list would leak between readers."""
    return {
        "version": VERSION,
        "chart": "auto",
        "replyTone": "direct",
        "replyLength": "short",
        "insightDensity": "normal",
        "focusTopics": [],
        "prepMinutes": 15,
        "updatedAt": 0.0,
    }


def _problem(key: str, value: object) -> str:
    """Why this value cannot be stored under this key, or "" when it can."""
    if key in _VOCABULARY:
        allowed = _VOCABULARY[key]
        if value not in allowed:
            return f"{key} must be one of {', '.join(allowed)}."
        return ""
    if key == "focusTopics":
        if not isinstance(value, list):
            return "focusTopics must be a list of short lines."
        if len(value) > MAX_TOPICS:
            return f"at most {MAX_TOPICS} focus topics."
        for topic in value:
            if not isinstance(topic, str) or not topic.strip():
                return "a focus topic must be a non-empty line."
            if len(topic.strip()) > MAX_TOPIC_CHARS:
                return f"a focus topic must be at most {MAX_TOPIC_CHARS} characters."
        return ""
    if key == "prepMinutes":
        low, high = PREP_MINUTES
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            return f"prepMinutes must be a whole number from {low} to {high}."
        return ""
    return f"{key} is not a preference."


def _topics(value: object) -> list[str]:
    """The topics as stored: trimmed, empties dropped, no repeats."""
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for topic in value:
        if not isinstance(topic, str):
            continue
        line = topic.strip()
        if line and line.lower() not in {item.lower() for item in seen}:
            seen.append(line)
    return seen[:MAX_TOPICS]


class PreferenceStore:
    """Reads and writes <data>/preferences.json. One file, one user."""

    def __init__(self, root: str | Path) -> None:
        """Bind the store to <root>/preferences.json; nothing is read yet."""
        self.path = Path(root) / "preferences.json"

    def read(self) -> dict:
        """The stored document over defaults, judged field by field.

        A missing, unparsable or non-object file reads as pure defaults,
        and one field the vocabulary refuses is skipped rather than
        refusing the document, so a half-written file still yields a
        complete preference set."""
        document = defaults()
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return document
        if not isinstance(stored, dict):
            return document
        for key in FIELDS:
            if key not in stored or _problem(key, stored[key]):
                continue
            document[key] = _topics(stored[key]) if key == "focusTopics" else stored[key]
        updated = stored.get("updatedAt")
        if isinstance(updated, (int, float)) and not isinstance(updated, bool):
            document["updatedAt"] = float(updated)
        return document

    def write(self, patch: object) -> dict:
        """Merge one partial document over what is stored and save it."""
        if not isinstance(patch, dict):
            raise PreferencesError(
                "preferences:not-an-object",
                "Expected a JSON object of preferences.",
            )
        if "version" in patch and patch["version"] != VERSION:
            raise PreferencesError(
                "preferences:unsupported-version",
                f"This desk stores preference version {VERSION}.",
            )
        unknown = sorted(set(patch) - set(FIELDS) - {"version"})
        if unknown:
            raise PreferencesError(
                "preferences:unknown-key",
                f"{unknown[0]} is not a preference.",
            )
        cleaned = {}
        for key in FIELDS:
            if key not in patch:
                continue
            problem = _problem(key, patch[key])
            if problem:
                raise PreferencesError("preferences:invalid-value", problem)
            cleaned[key] = _topics(patch[key]) if key == "focusTopics" else patch[key]
        document = self.read()
        document.update(cleaned)
        document["version"] = VERSION
        document["updatedAt"] = time.time()
        self._save(document)
        return document

    def reset(self) -> dict:
        """Back to defaults, with an updatedAt so a client can see it."""
        document = defaults()
        document["updatedAt"] = time.time()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return document

    def _save(self, document: dict) -> None:
        """Write the document atomically: a .tmp sibling, then os.replace.

        A reader mid-write sees either the whole previous file or the
        whole new one, never a truncated mix; keys are sorted so the
        file's own history stays diffable."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)


def changed(document: dict) -> list[str]:
    """The keys the user actually set, in a stable order."""
    fresh = defaults()
    keys = []
    for key in FIELDS:
        if document.get(key) != fresh[key]:
            keys.append(key)
    return keys


def prompt_lines(document: dict) -> list[str]:
    """The preferences as bounded prompt lines, defaults left out.

    This is the only place preferences become prose, so what a model may
    read about the user has one definition and one length."""
    lines: list[str] = []
    chart = document.get("chart")
    if chart in CHART and chart != "auto":
        lines.append(f"Chart: prefers a {chart} when a chart is drawn.")
    tone = document.get("replyTone")
    length = document.get("replyLength")
    if tone in REPLY_TONES and length in REPLY_LENGTHS:
        if tone != "direct" or length != "short":
            lines.append(f"Replies: {tone} tone, {length}.")
    topics = document.get("focusTopics")
    if isinstance(topics, list) and topics:
        lines.append("Focus topics: " + ", ".join(str(topic) for topic in topics[:MAX_TOPICS]) + ".")
    minutes = document.get("prepMinutes")
    if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes != 15:
        lines.append(f"Meeting prep: {minutes} minutes before.")
    density = document.get("insightDensity")
    if density in DENSITIES and density != "normal":
        lines.append(f"Card readings: {density}.")
    return [line[:160] for line in lines[:6]]
