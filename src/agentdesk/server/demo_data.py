"""The demo seed: labelled sample content for a fresh desk (ticket #68).

Turning the Sample data switch on fills the real stores with a small
honest set of sample cards and writes sample fixtures under the app's
own sample folder in the data dir. Everything seeded carries a visible
Sample marker: card ids are prefixed, card meta flags them, every
origin line starts with "Sample data:", and every file lives under
sample/ with Sample in its name. Turning the switch off removes exactly
what those markers identify; nothing the user created is touched, and no
sample content can be mistaken for live data.
"""

import io
import json
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from agentdesk.inbox.core import KIND_BRIEF, KIND_FEATURE_REQUEST, KIND_SUGGESTION, KIND_UPDATE_CONSENT, Card
from agentdesk.inbox.store import InboxStore

CARD_ID_PREFIX = "sample-"
SAMPLE_FLAG = "sample"          # the meta key that flags a seeded card
ORIGIN_MARKER = "Sample data:"  # every seeded origin line starts here
SAMPLE_DIR_NAME = "sample"      # the one folder, under the data dir

# The one honest set: an update the agent noticed, a pre-meeting brief,
# the wizard's feature-request dead-end, and a plugin update asking for
# more access. Fixed ids, so clearing is exact and re-seeding cannot
# mint twins.
SAMPLE_PLUGIN_ID = "sample-demo-plugin"
SAMPLE_PLUGIN_SCOPE = "excel-watch: sample/*.xlsx"

_FIXED_DATE = (2026, 1, 1, 0, 0, 0)  # deterministic zip entries, like the fixtures

_XLSX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
    "</Types>"
)
_XLSX_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)
# The sheet is named Sample: opened in any spreadsheet app, the tab
# itself says what this file is.
_XLSX_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<sheets><sheet name="Sample" sheetId="1" r:id="rId1" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>'
    "</workbook>"
)
_XLSX_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
    "</Relationships>"
)

_SAMPLE_ROWS = [
    ["Product line", "Units", "Revenue"],
    ["Atlas ERP modules", 41.0, 164000.0],
    ["Field services", 12.0, 58000.0],
    ["Care plans", 7.0, 22500.0],
]

# Header-only .eml fixtures: the seven headers the mail path reads, no
# blank line, no body, ever. Subjects say Sample.
_SAMPLE_MAILS = (
    (
        "sample-thread-1.eml",
        "From: sender@example.com\n"
        "To: employee@example.com\n"
        "Subject: Sample: Q4 plan\n"
        "Date: Mon, 28 Sep 2026 12:00:00 GMT\n"
        "Message-ID: <sample-thread-1@example.com>",
    ),
    (
        "sample-thread-2.eml",
        "From: operations@example.com\n"
        "To: employee@example.com\n"
        "Subject: Sample: field services rollout\n"
        "Date: Mon, 28 Sep 2026 15:30:00 GMT\n"
        "Message-ID: <sample-thread-2@example.com>",
    ),
    (
        "sample-thread-3.eml",
        "From: finance@example.com\n"
        "To: employee@example.com\n"
        "Cc: manager@example.com\n"
        "Subject: Sample: care plan pricing\n"
        "Date: Tue, 29 Sep 2026 09:15:00 GMT\n"
        "Message-ID: <sample-thread-3@example.com>",
    ),
)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def sample_workbook_bytes() -> bytes:
    """A minimal but genuine .xlsx, the tests' fixture shape with the
    sheet named Sample. The stdlib parser reads it exactly as it reads
    a real workbook."""
    shared: list[str] = []
    shared_index: dict[str, int] = {}
    for row in _SAMPLE_ROWS:
        for value in row:
            if isinstance(value, str) and value not in shared_index:
                shared_index[value] = len(shared)
                shared.append(value)
    body_rows = []
    for r, row in enumerate(_SAMPLE_ROWS, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_column_letters(c)}{r}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value!r}</v></c>')
            elif isinstance(value, str) and value != "":
                cells.append(f'<c r="{ref}" t="s"><v>{shared_index[value]}</v></c>')
        body_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body_rows)}</sheetData></worksheet>"
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">'
        f"{''.join(f'<si><t>{_xml_escape(s)}</t></si>' for s in shared)}</sst>"
    )
    entries = {
        "[Content_Types].xml": _XLSX_CONTENT_TYPES,
        "_rels/.rels": _XLSX_RELS,
        "xl/workbook.xml": _XLSX_WORKBOOK,
        "xl/_rels/workbook.xml.rels": _XLSX_WORKBOOK_RELS,
        "xl/sharedStrings.xml": shared_xml,
        "xl/worksheets/sheet1.xml": sheet,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=_FIXED_DATE)
            zf.writestr(info, content)
    return buffer.getvalue()


def sample_calendar_bytes(now: datetime) -> bytes:
    """A calendar-sync shaped JSON with Sample in every subject."""
    first = now.replace(second=0, microsecond=0) + timedelta(hours=2)
    second = now.replace(second=0, microsecond=0) + timedelta(hours=4)
    doc = {
        "generatedAt": now.isoformat(),
        "events": [
            {
                "id": "sample-evt-1",
                "subject": "Sample: Q4 pipeline review",
                "start": first.isoformat(),
                "end": (first + timedelta(hours=1)).isoformat(),
                "location": "Room Beaufort (sample)",
                "attendees": 6,
            },
            {
                "id": "sample-evt-2",
                "subject": "Sample: care plan check-in",
                "start": second.isoformat(),
                "end": (second + timedelta(minutes=30)).isoformat(),
                "location": "Call (sample)",
                "attendees": 3,
            },
        ],
    }
    return json.dumps(doc, indent=2).encode("utf-8")


def sample_folder(data_dir: Path) -> Path:
    return Path(data_dir) / SAMPLE_DIR_NAME


def is_sample_card(card: Card) -> bool:
    """The one predicate: the id prefix or the meta flag. Clearing hunts
    by exactly this, so user cards are never a match."""
    return card.id.startswith(CARD_ID_PREFIX) or bool(card.meta.get(SAMPLE_FLAG))


def seed(inbox: InboxStore | None, data_dir: Path) -> dict:
    """Write the labelled sample set into the real stores.

    Cards go into the inbox store with fixed sample- ids (any earlier
    seeding is removed first, so a re-seed cannot mint twins); fixtures
    land under the sample folder in the data dir. Returns the tally for
    the audit row.
    """
    cards = 0
    if inbox is not None:
        for card in list(inbox.all_cards()):
            if is_sample_card(card):
                inbox.delete(card.id)
        now_ts = inbox.now_ts()
        for spec in _card_specs():
            inbox.add(
                kind=spec["kind"],
                origin=spec["origin"],
                title=spec["title"],
                body=spec["body"],
                action_label=spec["action_label"],
                window_hours=spec.get("window_hours"),
                meta=spec["meta"],
                card_id=spec["id"],
                draft=spec.get("draft", ""),
            )
            cards += 1
        now = datetime.fromtimestamp(now_ts).astimezone()
    else:
        now = datetime.now().astimezone()
    folder = sample_folder(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sample-sales.xlsx").write_bytes(sample_workbook_bytes())
    (folder / "sample-calendar.json").write_bytes(sample_calendar_bytes(now))
    mail_dir = folder / "sample-mail"
    mail_dir.mkdir(parents=True, exist_ok=True)
    for name, headers in _SAMPLE_MAILS:
        (mail_dir / name).write_text(headers, encoding="utf-8")
    files = 2 + len(_SAMPLE_MAILS)
    return {
        "cards": cards,
        "files": files,
        "detail": (
            f"{cards} labelled sample cards; the sample folder holds "
            f"{files} fixtures (a workbook, a calendar file, "
            "header-only mail). Everything is marked Sample; none of it is live."
        ),
    }


def clear(inbox: InboxStore | None, data_dir: Path) -> dict:
    """Remove exactly what seed() put there: every card the predicate
    matches, in any status, and the one sample folder. User cards and
    every other file stay untouched."""
    cards = 0
    if inbox is not None:
        for card in list(inbox.all_cards()):
            if is_sample_card(card):
                inbox.delete(card.id)
                cards += 1
    folder = sample_folder(data_dir)
    files = 0
    if folder.exists():
        files = sum(1 for p in folder.rglob("*") if p.is_file())
        shutil.rmtree(folder, ignore_errors=True)
    return {
        "cards": cards,
        "files": files,
        "detail": (
            f"removed {cards} sample cards and the sample folder "
            f"({files} fixtures); nothing created outside the sample set was touched."
        ),
    }


def _card_specs() -> list[dict]:
    """The one honest set, in plain language, every line saying Sample."""
    flag = {SAMPLE_FLAG: True}
    return [
        {
            "id": "sample-update",
            "kind": KIND_SUGGESTION,
            "origin": ORIGIN_MARKER + " an overnight change the agent noticed, "
                                       "demonstrated. Nothing here is live.",
            "title": "Overnight sales update, ready to walk through",
            "body": "This card stands in for the update the agent finds in the "
                    "watched workbook each morning. The sample workbook it "
                    "describes lives in the app's sample folder.",
            "action_label": "Accept update",
            "draft": "Walk me through last night's changes in the sales workbook.",
            "meta": dict(flag),
        },
        {
            "id": "sample-brief",
            "kind": KIND_BRIEF,
            "origin": ORIGIN_MARKER + " the brief the calendar bridge assembles "
                                       "before a meeting, demonstrated. Nothing here is live.",
            "title": "Before your sample meeting: Q4 pipeline review",
            "body": "Three attendees, one open commitment from the last session. "
                    "The sample calendar fixture behind it lives in the app's "
                    "sample folder.",
            "action_label": "Got it",
            "window_hours": 1.5,
            "draft": "Prep: the open commitment first, then the two follow-ups.",
            "meta": dict(flag, meetingId="sample-evt-1"),
        },
        {
            "id": "sample-feature-request",
            "kind": KIND_FEATURE_REQUEST,
            "origin": ORIGIN_MARKER + " the wizard's honest dead-end when a "
                                       "request cannot be built safely, demonstrated. "
                                       "Nothing here is live.",
            "title": "Feature request exported to the owner queue",
            "body": "Your words, preserved: a monthly one-pager of sample numbers. "
                    "The wizard could not compile this one safely, so it hands "
                    "the request to the owner queue.",
            "action_label": "Accept",
            "draft": "Monthly one-pager, sample numbers, one page.",
            "meta": dict(flag, wizardSession="sample-session"),
        },
        {
            "id": "sample-update-consent",
            "kind": KIND_UPDATE_CONSENT,
            "origin": ORIGIN_MARKER + " a plugin update asking for more access, "
                                       "waiting for your OK. Nothing here is live.",
            "title": f"{SAMPLE_PLUGIN_ID} 0.2.0 asks for more access",
            "body": f"New access: {SAMPLE_PLUGIN_SCOPE}",
            "action_label": "Allow update",
            "meta": dict(
                flag,
                pluginId=SAMPLE_PLUGIN_ID,
                scope=SAMPLE_PLUGIN_SCOPE,
                version="0.2.0",
            ),
        },
    ]
