"""The closed vocabulary the plugin wizard may offer.

Every question option, every autofilled value, and every composed element is a
member of a table in this module. A label that is not here cannot be offered to
a manager, and a label a model returns that is not here is dropped. That is the
whole confinement story: the questions, the autofill, and the composer all read
these tables, so they cannot drift apart.

The element tables are keyed by source type first, because what a tile can show
depends entirely on which bindings that source's reader actually fills. A figure
source has no "items" and a checklist file has no "target", so neither is ever
offered.
"""

from __future__ import annotations

# ---- questions -----------------------------------------------------------

QUESTION_SOURCE = "source"
QUESTION_DETAIL = "detail"
QUESTION_SHOW = "show"
QUESTION_LOOK = "look"
QUESTION_UPDATE = "update"

SHOW_LATEST = "latest"
SHOW_CHANGE = "change"
SHOW_TREND = "trend"
SHOW_ONTRACK = "ontrack"
SHOW_ROWS = "rows"
SHOW_ITEMS = "items"
SHOW_STATUS = "status"

SHOW_LABELS: dict[str, str] = {
    SHOW_LATEST: "The latest figure",
    SHOW_CHANGE: "How it moved",
    SHOW_TREND: "How it has gone lately",
    SHOW_ONTRACK: "Whether it is on track",
    SHOW_ROWS: "The rows behind it",
    SHOW_ITEMS: "The items that need me",
    SHOW_STATUS: "One status line",
}

# The plain-language names of the ten element kinds a manager may pick.
LOOK_LABELS: dict[str, str] = {
    "metric": "A big number",
    "status": "A colored status",
    "delta": "Up or down",
    "sparkline": "A short trend line",
    "progress": "A bar to a target",
    "table": "A table",
    "list": "A list",
    "timeline": "A timeline",
    "checklist": "A checklist",
    "text": "One sentence",
}

# ---- sources -------------------------------------------------------------

# The manager's words for each source type. This is the only list the wizard
# draws a source from, and the only list an autofilled source may match.
SOURCE_CHOICES: tuple[tuple[str, str], ...] = (
    ("An Excel workbook", "excel-watch"),
    ("A CSV file", "csv-watch"),
    ("A JSON file", "json-watch"),
    ("A notes file", "markdown-watch"),
    ("A web page", "http-get"),
    ("My calendar", "calendar-read"),
    ("My mail", "mail-digest"),
    ("A number I keep", "manual-metric"),
    ("Research already on the desk", "research-brief"),
)

SOURCE_BY_LABEL: dict[str, str] = dict(SOURCE_CHOICES)
SOURCE_LABELS: tuple[str, ...] = tuple(label for label, _ in SOURCE_CHOICES)

# The one follow-up a source needs before it can be read. A workbook has none:
# its file and columns are chosen per instance in setup, as they already are.
FILE_DETAIL: dict[str, tuple[str, ...]] = {
    "csv-watch": ("reports/*.csv", "data/*.csv", "exports/*.csv"),
    "json-watch": ("data/*.json", "cache/*.json", "exports/*.json"),
    "markdown-watch": ("notes/*.md", "docs/*.md"),
}
DEFAULT_FILE_DETAIL = {source: options[0] for source, options in FILE_DETAIL.items()}
WEB_DETAIL_DEFAULT = "https://example.com/data.json"

# ---- shows and looks, per source ----------------------------------------

# Which shows a source can bind, and which element each look becomes for it.
# A look names the element kind and the bindings that kind reads; every binding
# here is one the source's reader in plugins/sources.py or plugins/execute.py
# actually fills, so a composed tile is never blank for want of a binding.
ELEMENTS: dict[str, dict[str, dict[str, dict]]] = {
    "excel-watch": {
        SHOW_LATEST: {"metric": {"binding": "value"}},
        # The workbook's change is the reader's own sentence ("3 new, 1
        # removed rows."), not a number, so it is a status and not a delta.
        SHOW_CHANGE: {"status": {"binding": "delta24h"}},
        SHOW_ROWS: {"table": {"columns": ["Item", "Value", "Note"],
                              "rowsBinding": "rows"},
                    "list": {"rowsBinding": "rows"}},
    },
    "csv-watch": {
        SHOW_LATEST: {"metric": {"binding": "value"}},
        SHOW_TREND: {"sparkline": {"pointsBinding": "points"}},
        SHOW_ROWS: {"table": {"columns": ["Item", "Value", "Note"],
                              "rowsBinding": "rows"},
                    "list": {"rowsBinding": "rows"}},
    },
    "json-watch": {
        SHOW_LATEST: {"metric": {"binding": "value"}},
        SHOW_TREND: {"sparkline": {"pointsBinding": "points"}},
        SHOW_ROWS: {"table": {"columns": ["Item", "Value", "Note"],
                              "rowsBinding": "rows"},
                    "list": {"rowsBinding": "rows"}},
    },
    "markdown-watch": {
        SHOW_ITEMS: {"checklist": {"itemsBinding": "items"},
                     "list": {"rowsBinding": "rows"}},
        SHOW_STATUS: {"status": {"binding": "value", "toneBinding": "tone"},
                      "text": {"binding": "nextDue"}},
    },
    "http-get": {
        SHOW_LATEST: {"metric": {"binding": "value"}},
        SHOW_CHANGE: {"status": {"binding": "changed"}},
        SHOW_ROWS: {"list": {"rowsBinding": "rows"}},
    },
    "calendar-read": {
        SHOW_ITEMS: {"list": {"rowsBinding": "rows"}},
        SHOW_STATUS: {"status": {"binding": "nextEventTitle"}},
    },
    "mail-digest": {
        SHOW_ITEMS: {"list": {"rowsBinding": "waitingRows"}},
        SHOW_STATUS: {"status": {"binding": "messages"}},
    },
    "manual-metric": {
        SHOW_LATEST: {"metric": {"binding": "value"}},
        SHOW_CHANGE: {"delta": {"binding": "delta",
                                "directionBinding": "direction"}},
        SHOW_ONTRACK: {"progress": {"binding": "value",
                                    "targetBinding": "target"}},
        SHOW_TREND: {"sparkline": {"pointsBinding": "points"}},
    },
    "research-brief": {
        SHOW_ITEMS: {"list": {"rowsBinding": "rows"}},
        SHOW_STATUS: {"status": {"binding": "summary"}},
    },
}

# ---- when it updates -----------------------------------------------------

UPDATE_VIEW = "view"
UPDATE_HOOK = "hook"
UPDATE_CLOCK = "clock"

UPDATE_VIEW_LABEL = "When I open the desk"
UPDATE_HOOK_LABEL = "When it changes"

# The clock choices, as (label, cron). A five-field cron, read by the refresh
# tick as "has the most recent scheduled minute passed".
CLOCK_CHOICES: tuple[tuple[str, str], ...] = (
    ("Each morning at 8", "0 8 * * *"),
    ("Every hour", "0 * * * *"),
    ("Monday morning", "0 8 * * 1"),
    ("Friday afternoon", "0 16 * * 5"),
)
CLOCK_BY_LABEL = dict(CLOCK_CHOICES)

# The change topics each source has an event for. A source with no entry is
# never offered "when it changes", because nothing could ever fire it.
HOOK_TOPICS: dict[str, str] = {
    "excel-watch": "workbook",
    "csv-watch": "file",
    "json-watch": "file",
    "markdown-watch": "file",
    "calendar-read": "calendar",
    "mail-digest": "mail",
    "manual-metric": "manual",
    "research-brief": "research",
}

# ---- lookups -------------------------------------------------------------


def shows_for(source_type: str) -> tuple[str, ...]:
    """The shows a source can bind, in the order the question offers them."""
    return tuple(ELEMENTS.get(source_type, {}))


def looks_for(source_type: str, show: str) -> tuple[str, ...]:
    """The looks that fit one show for one source."""
    return tuple(ELEMENTS.get(source_type, {}).get(show, {}))


def element_for(source_type: str, show: str, look: str) -> dict | None:
    """The ui-schema element for a choice, or None when it is not offered."""
    spec = ELEMENTS.get(source_type, {}).get(show, {}).get(look)
    if spec is None:
        return None
    return {"type": look, **spec}


def source_for_label(label: object) -> str:
    """The source type a plain-language source label names, or ""."""
    if not isinstance(label, str):
        return ""
    return SOURCE_BY_LABEL.get(label.strip(), "")


def show_for_label(label: object, source_type: str) -> str:
    """The show key a label names for a source, or "" when it is not offered."""
    if not isinstance(label, str):
        return ""
    wanted = label.strip()
    return next((show for show in shows_for(source_type)
                 if SHOW_LABELS[show] == wanted), "")


def look_for_label(label: object, source_type: str, show: str) -> str:
    """The look key a label names for a source and show, or ""."""
    if not isinstance(label, str):
        return ""
    wanted = label.strip()
    return next((look for look in looks_for(source_type, show)
                 if LOOK_LABELS[look] == wanted), "")


def update_for_label(label: object, source_type: str) -> tuple[str, str]:
    """The update mode a label names, as ("view"|"hook"|"clock", value).

    An unrecognised label, or a change choice for a source with no event, is
    returned as ("", "") so the caller leaves the question for the manager.
    """
    if not isinstance(label, str):
        return "", ""
    wanted = label.strip()
    if wanted == UPDATE_VIEW_LABEL:
        return UPDATE_VIEW, ""
    if wanted == UPDATE_HOOK_LABEL:
        return (UPDATE_HOOK, HOOK_TOPICS[source_type]) if source_type in HOOK_TOPICS else ("", "")
    if wanted in CLOCK_BY_LABEL:
        return UPDATE_CLOCK, CLOCK_BY_LABEL[wanted]
    return "", ""


def update_choices(source_type: str) -> tuple[str, ...]:
    """Every update option a source admits, in question order."""
    labels = [UPDATE_VIEW_LABEL]
    labels.extend(label for label, _ in CLOCK_CHOICES)
    if source_type in HOOK_TOPICS:
        labels.append(UPDATE_HOOK_LABEL)
    return tuple(labels)
