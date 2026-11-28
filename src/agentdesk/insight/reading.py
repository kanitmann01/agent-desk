"""The reading's presentation: what a card says about its own reading.

A family computes an InsightReading; this module turns it into the lines
every surface prints, so the authored HTML and the SPA never keep a phrase
table of their own. It also owns the structured press and its labels: the
one place a request kind becomes the sentence on a button.

The card's payload carries the resolved lines as blocks, not the names they
came from. A surface prints block["text"] verbatim, so adding a kind of line
is a change here and nowhere else, and a name the vocabulary does not hold
never reads as a raw identifier.
"""

from __future__ import annotations

from agentdesk.insight.agenda import truncate
from agentdesk.insight.preferences import FIELDS
from agentdesk.insight.types import InsightReading

# The input names a receipt may carry, fixed so the line prints a phrase this
# module already knows instead of echoing whatever a family wrote.
INPUT_NAMES = ("rows", "memory", "calendar")

# How a receipt reads: the seam names preference keys and input names, and
# this is the only place a key becomes a phrase a person would say. An
# unknown name draws nothing rather than a raw identifier, so the line can
# never read like a changelog.
RECEIPT_PHRASES = {
    "chart": "your chart preference",
    "replyTone": "your reply tone",
    "replyLength": "your reply length",
    "insightDensity": "your density setting",
    "focusTopics": "your focus topics",
    "prepMinutes": "your prep window",
}
INPUT_PHRASES = {
    "rows": "this card's rows",
    "memory": "memory",
    "calendar": "this calendar",
}
DEFAULTS_RECEIPT = "Used the defaults; read only this card's rows."

# The press page's heading, taken from the kind the card carried, so the page
# a press lands on repeats the sentence the person just pressed. The default
# is what an unknown kind reads as; it never falls back to a raw identifier.
PRESS_LABELS = {"reply-draft": "Draft a reply", "explain-range": "Explain this range"}
DEFAULT_PRESS_LABEL = "Ask the model"

# The request-shaped fields a press may carry: what the action needs, and
# nothing about how a surface draws it. A client posts these verbatim.
PRESS_KEYS = ("label", "route", "kind", "thread", "text")
THREAD_KEYS = ("subject", "sender", "last")

# The why drilldown's bounds: a claim or rule short enough to read at a
# glance, short column and cell strings, six cells at most, and fact
# citations that name ids and sources and never a fact's text.
WHY_CLAIM_CHARS = 200
WHY_RULE_CHARS = 160
WHY_TEXT_CHARS = 40
WHY_MAX_CELLS = 6
WHY_MAX_COLUMNS = 6


def press_label(kind: object) -> str:
    """The heading a press of this kind lands under.

    An unknown or missing kind reads as the default sentence rather than a raw
    identifier, because this label is shown to the person who pressed.
    """
    key = str(kind or "").strip()
    return PRESS_LABELS.get(key, DEFAULT_PRESS_LABEL)


def receipts(reading: InsightReading) -> dict:
    """What this reading used, filtered to the vocabulary a surface prints.

    A name outside the vocabulary is dropped rather than printed, and a
    repeat survives once, in the order it was first declared, so a family
    cannot turn the line into a changelog. Counts ride only on an input that
    was declared: the card never says "memory (2 notes)" about a reading
    that did not consult memory.
    """
    inputs = _named(reading.inputs, INPUT_NAMES)
    receipt: dict = {
        "preferences": _named(reading.used, FIELDS),
        "inputs": inputs,
    }
    notes = reading.memory_notes
    counted = isinstance(notes, int) and not isinstance(notes, bool) and notes > 0
    if "memory" in inputs and counted:
        receipt["counts"] = {"memory": notes}
    return receipt


def receipt_line(receipt: object) -> str:
    """One reading's receipt as the sentence under its card, or "".

    A reading that read nothing at all says nothing: a line under an empty
    card would invent a consultation that did not happen. The names arrive as
    the seam's keys, so this is where they become phrases; a key or input the
    vocabulary does not hold is skipped rather than echoed.
    """
    if not isinstance(receipt, dict):
        return ""
    chosen: list[str] = []
    for key in receipt.get("preferences") or []:
        phrase = RECEIPT_PHRASES.get(str(key))
        if phrase:
            chosen.append(phrase)
    counts = receipt.get("counts") if isinstance(receipt.get("counts"), dict) else {}
    notes = counts.get("memory")
    read: list[str] = []
    for name in receipt.get("inputs") or []:
        phrase = INPUT_PHRASES.get(str(name))
        if not phrase:
            continue
        if name == "memory" and isinstance(notes, int) and notes > 0:
            phrase = f"memory ({notes} note)" if notes == 1 else f"memory ({notes} notes)"
        read.append(phrase)
    if chosen:
        return "Used: " + " · ".join(chosen + read) + "."
    if not read:
        return ""
    if read == ["this card's rows"]:
        return DEFAULTS_RECEIPT
    return "Used the defaults; read " + " and ".join(read) + "."


def press(value: object) -> dict | None:
    """The card's press as the one structured object a surface may draw.

    Returns None unless the value carries a kind, because a button that
    cannot say what it will do must not be drawn. The label is resolved here
    from the kind when the family did not spell one, so both surfaces show
    the same sentence; the thread keeps only the bounded facts the action
    sends, and the text is the one sentence an explanation explains.
    """
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind") or "").strip()
    if not kind:
        return None
    label = str(value.get("label") or "").strip() or press_label(kind)
    route = str(value.get("route") or "").strip()
    resolved: dict = {"label": label, "route": route, "kind": kind}
    thread = value.get("thread")
    if isinstance(thread, dict):
        facts = {
            key: str(thread.get(key) or "").strip()
            for key in THREAD_KEYS
            if str(thread.get(key) or "").strip()
        }
        if facts:
            resolved["thread"] = facts
    text = str(value.get("text") or "").strip()
    if text:
        resolved["text"] = text
    return resolved


def blocks(reading: InsightReading) -> list[dict]:
    """The resolved lines under a card, in the order a surface prints them.

    A receipt block comes first because it is the card's record of what the
    reading consulted; a note block follows only when the reading has
    something to explain, so a reading that used nothing and says nothing
    still sends no empty line. Each text is final: surfaces print it as it
    came and never look a name up. The reading's why provenance, when it has
    any, is resolved onto the receipts block so the drilldown travels with
    the line it explains; a reading that declares no receipts has nothing
    for provenance to explain, so its why is left off.
    """
    lines: list[dict] = []
    line = receipt_line(receipts(reading))
    if line:
        lines.append({"kind": "receipts", "text": line})
    note = str(reading.note or "").strip()
    if note:
        lines.append({"kind": "note", "text": note})
    why = _why(reading.why)
    if why and lines and lines[0].get("kind") == "receipts":
        lines[0]["why"] = why
    return lines


def _why(entries: object) -> list[dict]:
    """The bounded provenance a receipts block may carry, or [] for none.

    Each entry keeps only the five fields a surface may draw: the claim and
    rule clipped, short column names, at most six cell references, and fact
    citations that name ids and sources (or a desk entity's id, name and
    fact count) and never a fact's text. Anything else a family wrote, an
    unknown field included, is dropped here, so a mistake cannot leak
    private prose into the trust payload."""
    resolved: list[dict] = []
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        item: dict = {}
        claim = truncate(entry.get("claim"), WHY_CLAIM_CHARS)
        if claim:
            item["claim"] = claim
        columns = _short_strings(entry.get("columns"), WHY_MAX_COLUMNS)
        if columns:
            item["columns"] = columns
        cells = _short_strings(entry.get("cells"), WHY_MAX_CELLS)
        if cells:
            item["cells"] = cells
        rule = truncate(entry.get("rule"), WHY_RULE_CHARS)
        if rule:
            item["rule"] = rule
        facts = _citations(entry.get("facts"))
        if facts:
            item["facts"] = facts
        if item:
            resolved.append(item)
    return resolved


def _short_strings(values: object, cap: int) -> list[str]:
    """At most `cap` short strings: a non-string or empty value is dropped,
    every kept string is clipped, and nothing kept reads as no field."""
    kept: list[str] = []
    for value in values or ():
        text = truncate(value, WHY_TEXT_CHARS)
        if text:
            kept.append(text)
        if len(kept) >= cap:
            break
    return kept


def _citations(values: object) -> list[dict]:
    """The fact citations that survive: an integer fact id with its source,
    or a desk entity's id, name and fact count.

    A bool is not an id, and a fact's text is never carried, so a family
    that passes whole rows cannot leak prose into the payload."""
    kept: list[dict] = []
    for value in values or ():
        if not isinstance(value, dict):
            continue
        fact_id = value.get("id")
        if isinstance(fact_id, int) and not isinstance(fact_id, bool):
            kept.append({"id": fact_id, "source": str(value.get("source") or "")})
            continue
        entity_id = value.get("entityId")
        name = truncate(value.get("name"), WHY_TEXT_CHARS)
        count = value.get("factCount")
        if (
            isinstance(entity_id, int)
            and not isinstance(entity_id, bool)
            and name
            and isinstance(count, int)
            and not isinstance(count, bool)
        ):
            kept.append({"entityId": entity_id, "name": name, "factCount": count})
    return kept


def _named(names: tuple[str, ...], vocabulary: tuple[str, ...]) -> list[str]:
    """The declared names the vocabulary holds, once each, in declared order."""
    kept: list[str] = []
    for name in names or ():
        if name in vocabulary and name not in kept:
            kept.append(name)
    return kept
