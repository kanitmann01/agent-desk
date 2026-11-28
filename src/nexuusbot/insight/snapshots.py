"""Per-tile last-seen snapshots and the one-line perceptual delta.

The store keeps what every tile showed when the user last explicitly
viewed the dashboard, as one JSON document in the desk data directory.
Reads never write it, so a background poll cannot erase what changed
since the last visit; only the explicit view endpoint records a new
watermark. On each read the current tile is signed again and diffed
against that watermark, and one quiet sentence names the most noticeable
change, or says nothing when nothing moved and nothing was ever viewed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from nexuusbot.insight.digest import thread_facts

VERSION = 1
FILE_NAME = "insight_snapshots.json"

# The one prefix every delta line carries, and the bounds that keep a
# signature a glance rather than a copy of the tile.
PREFIX = "Since you last looked: "
MAX_THREADS = 10
SUMMARY_CHARS = 120
MAX_HEADERS = 20
MAX_NAMED_COLUMNS = 3

# The tile families, by plugin id: one signature shape each, and any
# other tile signs itself generically.
_WORKBOOK_FAMILIES = ("excel-report",)
_DIGEST_FAMILIES = ("outlook-digest", "waiting-on-you")
_CALENDAR_FAMILIES = ("calendar-today", "meeting-prep")
_RESEARCH_FAMILIES = ("research-brief",)

# The card-face text lines a workbook signature skips: they name the
# file and its pace, never a finding about the rows.
_FACE_LABELS = ("workbook", "pace")


def card_signature(card: dict) -> dict:
    """The compact, deterministic perceptual signature of one tile.

    Freshness and cause always ride along; the rest is the tile family's
    own summary (workbook tracker, digest threads, next meeting, stored
    answer) or, for any other tile, the metric values and the status and
    list counts it shows. Every value is JSON-serialisable and capped, so
    the same tile always signs the same way.
    """
    plugin_id = str(card.get("pluginId") or card.get("id") or "")
    payload = card.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    signature: dict = {
        "freshness": str(card.get("freshness") or ""),
        "cause": str(card.get("cause") or ""),
    }
    if plugin_id in _WORKBOOK_FAMILIES:
        signature["workbook"] = _workbook_signature(payload)
    elif plugin_id in _DIGEST_FAMILIES:
        signature["digest"] = _digest_signature(payload)
    elif plugin_id in _CALENDAR_FAMILIES:
        signature["calendar"] = _calendar_signature(payload)
    elif plugin_id in _RESEARCH_FAMILIES:
        signature["research"] = _research_signature(payload)
    else:
        signature["generic"] = _generic_signature(payload)
    return signature


def perceptual_delta(previous: dict | None, current: dict) -> str:
    """One sentence on what moved since the last view, or "".

    No watermark, or nothing meaningful changed, says nothing: the desk
    never invents movement on an empty history. The checks run in the
    spec's priority order and the first match wins, so the sentence
    always names the most noticeable change.
    """
    if not isinstance(previous, dict):
        return ""
    for check in (_freshness_delta, _workbook_delta, _digest_delta,
                  _calendar_delta, _research_delta, _generic_delta):
        line = check(previous, current)
        if line:
            return PREFIX + line
    return ""


class SnapshotStore:
    """Reads and writes <data_dir>/insight_snapshots.json. One file, one desk."""

    def __init__(self, root: str | Path) -> None:
        """Bind the store to <root>/insight_snapshots.json; nothing is read yet."""
        self.path = Path(root) / FILE_NAME

    def read(self) -> dict:
        """The stored watermark document, or the empty version 1 shape.

        A missing, unparsable or non-object file reads as empty, so a
        desk that has never been viewed behaves like one, never crashes.
        """
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty()
        if not isinstance(stored, dict):
            return _empty()
        version = stored.get("version")
        viewed_at = stored.get("viewedAt")
        cards = stored.get("cards")
        return {
            "version": version if isinstance(version, int) else VERSION,
            "viewedAt": viewed_at if isinstance(viewed_at, (int, float))
            and not isinstance(viewed_at, bool) else 0.0,
            "cards": {str(key): value for key, value in cards.items()}
            if isinstance(cards, dict) else {},
        }

    def record(self, cards: list[dict]) -> dict:
        """Sign every tile as it shows right now and store the watermark.

        Only the explicit view endpoint calls this, so a GET or a poll
        never moves the baseline the deltas are read against. The
        document is the version 1 schema, written atomically.
        """
        now = time.time()
        entries: dict = {}
        for card in cards or []:
            if not isinstance(card, dict):
                continue
            card_id = str(card.get("id") or card.get("pluginId") or "").strip()
            if not card_id:
                continue
            entries[card_id] = {
                "seenAt": now,
                "pluginId": str(card.get("pluginId") or card.get("id") or ""),
                "signature": card_signature(card),
            }
        document = {"version": VERSION, "viewedAt": now, "cards": entries}
        self._save(document)
        return document

    def _save(self, document: dict) -> None:
        """Write the document atomically: a .tmp sibling, then os.replace.

        A reader mid-write sees either the whole previous file or the
        whole new one, never a truncated mix; keys are sorted so the
        file's own history stays diffable.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)


def _empty() -> dict:
    """The version 1 document a desk with no views yet reads."""
    return {"version": VERSION, "viewedAt": 0.0, "cards": {}}


# -- the signatures -------------------------------------------------------


def _elements(payload: dict) -> list:
    """The tile's payload elements that are dictionaries, in its order."""
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        return []
    return [element for element in elements if isinstance(element, dict)]


def _text_of(element: dict) -> str:
    """One element's text, trimmed."""
    return str(element.get("text") or "").strip()


def _fold(label: object) -> str:
    """A label or title in the folded form the label matches read."""
    return str(label or "").strip().lower()


def _side(previous: dict, current: dict, family: str) -> tuple[dict, dict]:
    """Both sides' family section as dictionaries, empty when absent."""
    before = previous.get(family)
    after = current.get(family)
    return (before if isinstance(before, dict) else {},
            after if isinstance(after, dict) else {})


def _workbook_signature(payload: dict) -> dict:
    """What the tracker tile shows: the figure, its unit and change, the
    sheet shape it read, and the finding the reading leads with."""
    tracker = payload.get("tracker")
    tracker = tracker if isinstance(tracker, dict) else {}
    table = tracker.get("table")
    table = table if isinstance(table, dict) else {}
    rows_seen = tracker.get("rowsSeen")
    return {
        "value": str(tracker.get("value") or ""),
        "unit": str(tracker.get("unit") or ""),
        "delta": str(tracker.get("delta") or ""),
        "headers": [str(header) for header in (table.get("headers") or [])][:MAX_HEADERS],
        "rowsSeen": rows_seen if isinstance(rows_seen, int)
        and not isinstance(rows_seen, bool) else 0,
        "finding": _top_finding(payload),
    }


def _top_finding(payload: dict) -> str:
    """The first text element that names a finding about the rows.

    The card face's own file and pace lines are skipped; the first text
    left over is the reading's top sentence.
    """
    for element in _elements(payload):
        if element.get("kind") != "text":
            continue
        if _fold(element.get("label")) in _FACE_LABELS:
            continue
        text = _text_of(element)
        if text:
            return text
    return ""


def _digest_signature(payload: dict) -> dict:
    """The threads the tile names, up to ten, each subject, sender, age."""
    threads = thread_facts(payload)[:MAX_THREADS]
    return {"threads": [
        [str(thread.get("subject") or ""),
         str(thread.get("sender") or ""),
         str(thread.get("age") or "")]
        for thread in threads
    ]}


def _calendar_signature(payload: dict) -> dict:
    """The next meeting as the tile names it: title, time, place and how
    many prep items sit under it.

    A label the tile never prints leaves that part empty; a tile with no
    "Next" line signs its first text as the title, because that is where
    a meeting tile shows it.
    """
    title = time = meta = ""
    prep = 0
    for element in _elements(payload):
        label = _fold(element.get("label")) or _fold(element.get("title"))
        kind = element.get("kind")
        if kind == "text":
            text = _text_of(element)
            if not text:
                continue
            if not title and "next" in label:
                title = text
            elif not time and "time" in label:
                time = text
            elif not meta and any(word in label for word in ("where", "location", "room")):
                meta = text
        elif kind == "checklist":
            items = element.get("items")
            count = len(items) if isinstance(items, list) else 0
            if not prep and ("prep" in label or count):
                prep = count
    if not title:
        for element in _elements(payload):
            if element.get("kind") == "text" and _text_of(element):
                title = _text_of(element)
                break
    return {"title": title, "time": time, "meta": meta, "prep": prep}


def _research_signature(payload: dict) -> dict:
    """The stored answer as the tile shows it: when it landed, what it
    opens with and how many sources it cites."""
    answered = ""
    sources = ""
    summary = ""
    summary_key = payload.get("summary") if isinstance(payload.get("summary"), str) else ""
    if summary_key.strip():
        summary = summary_key.strip()
    for element in _elements(payload):
        label = _fold(element.get("label"))
        if not answered and "answered" in label:
            answered = _text_of(element)
        elif not sources and element.get("kind") == "metric" and "source" in label:
            sources = str(element.get("value") or "")
        elif not summary and element.get("kind") in ("text", "status") and "answer" in label:
            summary = _text_of(element)
    return {
        "answered": answered,
        "summary": summary[:SUMMARY_CHARS],
        "sources": sources,
    }


def _generic_signature(payload: dict) -> dict:
    """What any other tile shows: each metric's label and value, the
    status lines, and how many rows each list carries."""
    metrics: list = []
    statuses: list = []
    lists: list = []
    for element in _elements(payload):
        kind = element.get("kind")
        if kind == "metric":
            metrics.append([str(element.get("label") or ""), str(element.get("value") or "")])
        elif kind == "status":
            statuses.append(_text_of(element))
        elif kind == "list":
            rows = element.get("rows")
            lists.append(len(rows) if isinstance(rows, list) else 0)
    return {"metrics": metrics, "statuses": statuses, "lists": lists}


# -- the delta checks, in the spec's priority order -----------------------


def _freshness_delta(previous: dict, current: dict) -> str:
    """The freshness story: attention earned, attention cleared, a state
    the tile moved between, or a new reason under the same state."""
    was = str(previous.get("freshness") or "")
    now = str(current.get("freshness") or "")
    if was == now:
        if str(previous.get("cause") or "") != str(current.get("cause") or ""):
            return "this tile's reason changed."
        return ""
    if now == "attention":
        return "this tile needs attention."
    if was == "attention":
        return "this tile has fresh data again."
    return f"this tile moved from {was or 'unknown'} to {now or 'unknown'}."


def _workbook_delta(previous: dict, current: dict) -> str:
    """The workbook story: a column that appeared or went away first,
    then the tracked figure, the change figure, the row count and the
    top finding."""
    before, after = _side(previous, current, "workbook")
    if not before and not after:
        return ""
    was_headers = [str(header) for header in (before.get("headers") or [])]
    now_headers = [str(header) for header in (after.get("headers") or [])]
    appeared = [header for header in now_headers if header not in was_headers]
    removed = [header for header in was_headers if header not in now_headers]
    if appeared:
        return "a column appeared: " + ", ".join(appeared[:MAX_NAMED_COLUMNS]) + "."
    if removed:
        return "a column is gone: " + ", ".join(removed[:MAX_NAMED_COLUMNS]) + "."
    if before.get("value") != after.get("value"):
        unit = str(after.get("unit") or "").strip()
        return ("your tracked figure moved from " + str(before.get("value") or "?")
                + " to " + str(after.get("value") or "?")
                + ((" " + unit) if unit else "") + ".")
    if before.get("delta") != after.get("delta"):
        return ("the change figure moved from " + str(before.get("delta") or "?")
                + " to " + str(after.get("delta") or "?") + ".")
    if before.get("rowsSeen") != after.get("rowsSeen"):
        return (f"the tile now reads {after.get('rowsSeen')} rows "
                f"(was {before.get('rowsSeen')}).")
    if before.get("finding") != after.get("finding"):
        return "the top finding changed."
    return ""


def _digest_delta(previous: dict, current: dict) -> str:
    """The digest story: a thread that arrived first, then one that went
    quiet, then one that has been waiting longer."""
    was = {thread["subject"]: thread for thread in _threads(previous.get("digest"))}
    now = {thread["subject"]: thread for thread in _threads(current.get("digest"))}
    for subject, thread in now.items():
        if subject not in was:
            return "a new thread arrived: " + subject + "."
    for subject in was:
        if subject not in now:
            return "a thread went quiet: " + subject + "."
    for subject, thread in now.items():
        older = was.get(subject)
        if older is not None and older["age"] != thread["age"]:
            return f"a waiting thread aged: {subject} is now {thread['age']}."
    return ""


def _threads(section: object) -> list:
    """The stored digest threads as subject, sender, age records."""
    threads = section.get("threads") if isinstance(section, dict) else None
    out: list = []
    for thread in threads or []:
        if isinstance(thread, (list, tuple)) and len(thread) == 3:
            out.append({"subject": str(thread[0]), "sender": str(thread[1]),
                        "age": str(thread[2])})
    return out


def _calendar_delta(previous: dict, current: dict) -> str:
    """The calendar story: the next meeting's time first, then its
    title, its place, and the prep list under it."""
    before, after = _side(previous, current, "calendar")
    if not before and not after:
        return ""
    if before.get("time") != after.get("time"):
        was, now = str(before.get("time") or ""), str(after.get("time") or "")
        if was and now:
            return f"your next meeting moved from {was} to {now}."
        return f"your next meeting is at {now or was} now."
    if before.get("title") != after.get("title"):
        return "your next meeting is now " + str(after.get("title") or "unnamed") + "."
    if before.get("meta") != after.get("meta"):
        return "your next meeting changed place: " + str(after.get("meta") or "not set") + "."
    if before.get("prep") != after.get("prep"):
        return "the prep list for your next meeting changed."
    return ""


def _research_delta(previous: dict, current: dict) -> str:
    """The research story: a newer answer first, then an answer whose
    text or source count moved."""
    before, after = _side(previous, current, "research")
    if not before and not after:
        return ""
    if before.get("answered") != after.get("answered"):
        return "a newer research answer landed."
    if before.get("summary") != after.get("summary"):
        return "the stored answer changed."
    if before.get("sources") != after.get("sources"):
        return (f"the answer now cites {after.get('sources') or '?'} sources "
                f"(was {before.get('sources') or '?'}).")
    return ""


def _generic_delta(previous: dict, current: dict) -> str:
    """Anything else: a moved figure, a new status line, or a list whose
    length moved is one change worth one line."""
    before, after = _side(previous, current, "generic")
    if not before and not after:
        return ""
    if before.get("metrics") != after.get("metrics"):
        return "the figures on this tile changed."
    if before.get("statuses") != after.get("statuses"):
        return "this tile carries a new status line."
    if before.get("lists") != after.get("lists"):
        return "a list on this tile changed length."
    return ""
