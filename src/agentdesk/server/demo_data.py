"""The demo seed: labelled sample content for a fresh desk (ticket #68).

Turning the Sample data switch on fills the real stores with a small
honest set of sample cards and writes sample fixtures under the app's
own sample folder in the data dir. Everything seeded carries a visible
Sample marker: card ids are prefixed, card meta flags them, every
origin line starts with "Sample data:", and every file lives under
sample/ with Sample in its name. Turning the switch off removes exactly
what was seeded, hunted by the fixed id prefix alone; the meta flag only
ever renders a card as Sample, never marks one for deletion, so nothing
the user created is touched (their cards keep the 30-day recovery), and
no sample content can be mistaken for live data.
"""

import io
import json
import shutil
import zipfile
from datetime import date, datetime, timedelta
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

_CRM_HEADER = ["Deal", "Region", "Stage", "Amount", "Close date", "Owner"]
_REGIONS = ("AMER", "EMEA", "APAC")
_STAGES = ("Prospect", "Qualify", "Propose", "Negotiate", "Closed Won")
_OWNERS = ("Avery Kim", "Jordan Lee", "Riley Chen", "Sam Ortiz")
# Twenty accounts and five kinds of deal. Row i pairs account i % 20
# with kind (i // 20 + i) % 5, so all 100 deal names are different and
# no two rows read as the same deal. The workbook sits in the sample
# folder under a sheet named Sample; the desk marks it SAMPLE DATA once
# per cell, so the names themselves carry no prefix.
_ACCOUNTS = (
    "Halvorsen Freight", "Brightwater Clinics", "Kestrel Foods", "Marlow & Finch",
    "Northgate Utilities", "Pellam Logistics", "Ridgeway Dental", "Sato Instruments",
    "Tamsin Hotels", "Ubeda Textiles", "Corran Mining", "Lindqvist Retail",
    "Oakhurst Schools", "Fenwick Insurance", "Delgado Farms", "Wexford Transit",
    "Ashby Pharma", "Quayle Media", "Iverson Steel", "Galen Health",
)
_DEAL_KINDS = (
    "renewal", "expansion", "pilot", "support retainer", "platform add-on",
)


def _deal_name(idx: int) -> str:
    account = _ACCOUNTS[idx % len(_ACCOUNTS)]
    kind = _DEAL_KINDS[(idx // len(_ACCOUNTS) + idx) % len(_DEAL_KINDS)]
    return f"{account} {kind}"


def _sample_sales_rows() -> list[list]:
    """Header + 100 deterministic CRM deals for the Sample workbook."""
    rows: list[list] = [_CRM_HEADER[:]]
    base = date(2026, 1, 15)
    for i in range(1, 101):
        idx = i - 1
        rows.append([
            _deal_name(idx),
            _REGIONS[idx % len(_REGIONS)],
            _STAGES[idx % len(_STAGES)],
            float(12_000 + round((i * 7_919) % 168_000, -1)),
            (base + timedelta(days=idx * 3)).isoformat(),
            _OWNERS[idx % len(_OWNERS)],
        ])
    return rows


# Header-only .eml fixtures: the seven headers the mail path reads, no
# blank line, no body, ever. File names say sample. The Date headers are
# built at seed time a few hours back: the digest counts the last 24
# hours of headers, so fixtures pinned to authored dates would bind
# zeros forever and the demo card would look broken while behaving
# honestly.
_SAMPLE_MAILS = (
    (
        "sample-thread-1.eml",
        "sender@example.com",
        "Q4 plan",
        3.0,
        False,
    ),
    (
        "sample-thread-2.eml",
        "operations@example.com",
        "Field services rollout",
        6.0,
        False,
    ),
    (
        "sample-thread-3.eml",
        "finance@example.com",
        "Care plan pricing",
        9.0,
        True,
    ),
)


def _sample_mail_headers(name: str, sender: str, subject: str, age_hours: float,
                         cc: bool, now: datetime) -> str:
    """One fixture's headers with its Date stamped from the seed clock."""
    from email.utils import formatdate
    lines = [
        f"From: {sender}",
        "To: employee@example.com",
    ]
    if cc:
        lines.append("Cc: manager@example.com")
    lines += [
        f"Subject: {subject}",
        f"Date: {formatdate(now.timestamp() - age_hours * 3600, usegmt=True)}",
        f"Message-ID: <{name[:-4]}@example.com>",
    ]
    return "\n".join(lines) + "\n"


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
    rows = _sample_sales_rows()
    shared: list[str] = []
    shared_index: dict[str, int] = {}
    for row in rows:
        for value in row:
            if isinstance(value, str) and value not in shared_index:
                shared_index[value] = len(shared)
                shared.append(value)
    body_rows = []
    for r, row in enumerate(rows, start=1):
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
    """A calendar-sync shaped JSON. The file name and folder say Sample."""
    first = now.replace(second=0, microsecond=0) + timedelta(hours=2)
    second = now.replace(second=0, microsecond=0) + timedelta(hours=4)
    doc = {
        "generatedAt": now.isoformat(),
        "events": [
            {
                "id": "sample-evt-1",
                "subject": "Q4 pipeline review",
                "start": first.isoformat(),
                "end": (first + timedelta(hours=1)).isoformat(),
                "location": "Room Beaufort",
                "attendees": 6,
            },
            {
                "id": "sample-evt-2",
                "subject": "Care plan check-in",
                "start": second.isoformat(),
                "end": (second + timedelta(minutes=30)).isoformat(),
                "location": "Call",
                "attendees": 3,
            },
        ],
    }
    return json.dumps(doc, indent=2).encode("utf-8")


def sample_folder(data_dir: Path) -> Path:
    return Path(data_dir) / SAMPLE_DIR_NAME


def is_seed_card(card: Card) -> bool:
    """The deletion predicate: the fixed id prefix, nothing else. Both
    the re-seed purge and clear() hunt by exactly this, so a user card
    that happens to carry the meta flag is never deleted and keeps its
    30-day recovery like every card they made."""
    return card.id.startswith(CARD_ID_PREFIX)


def is_sample_card(card: Card) -> bool:
    """The rendering predicate: the id prefix or the meta flag. Wider
    than is_seed_card on purpose, so anything that claims to be sample
    is labelled Sample wherever it surfaces. It never deletes."""
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
            if is_seed_card(card):
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
    for name, sender, subject, age_hours, cc in _SAMPLE_MAILS:
        headers = _sample_mail_headers(name, sender, subject, age_hours, cc, now)
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
    """Remove exactly what seed() put there: every card with the fixed
    sample- id prefix, in any status, and the one sample folder. User
    cards (including one merely meta-flagged Sample) and every other
    file stay untouched."""
    cards = 0
    if inbox is not None:
        for card in list(inbox.all_cards()):
            if is_seed_card(card):
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


# -- sample memories (the Memory page graph) ---------------------------------
#
# Three retained excerpts about the same sample pipeline the workbook and
# calendar fixtures describe, the facts a retain would extract from them
# with their entities, one fact typed on the Memory page, and one
# observation citing two facts. Every row is labelled: facts carry the
# source "sample seed", excerpts the context "sample seed", and clearing
# removes exactly those (and the observations and entities they leave
# orphaned, through the store's own removeFacts).

SAMPLE_MEMORY_SOURCE = "sample seed"
_DAY = 86_400.0

_SAMPLE_EXCERPTS = (
    {
        "days_ago": 6,
        "text": ("Call with Dana Ortiz at Halvorsen Freight: they want the renewal "
                 "signed before December 15 and asked for a three-year price lock. "
                 "Jordan Lee owns the deal."),
        "facts": (
            ("Halvorsen Freight wants the renewal signed before December 15.",
             "world", (("Halvorsen Freight", "org"),)),
            ("Halvorsen Freight asked for a three-year price lock on the renewal.",
             "world", (("Halvorsen Freight", "org"), ("Dana Ortiz", "person"))),
            ("Jordan Lee owns the Halvorsen Freight renewal.",
             "world", (("Jordan Lee", "person"), ("Halvorsen Freight", "org"))),
        ),
    },
    {
        "days_ago": 3,
        "text": ("Pipeline prep: the Kestrel Foods pilot slipped to January because "
                 "their IT security review is still open. Riley Chen is chasing it."),
        "facts": (
            ("The Kestrel Foods pilot slipped to January.",
             "world", (("Kestrel Foods", "org"),)),
            ("Kestrel Foods' IT security review is still open.",
             "world", (("Kestrel Foods", "org"),)),
            ("Riley Chen is chasing the Kestrel Foods security review.",
             "world", (("Riley Chen", "person"), ("Kestrel Foods", "org"))),
        ),
    },
    {
        "days_ago": 1,
        "text": ("I sent the Q4 pipeline summary to Avery Kim before the review and "
                 "flagged Halvorsen and Kestrel as the two at-risk deals."),
        "facts": (
            ("I sent the Q4 pipeline summary to Avery Kim and flagged two at-risk deals.",
             "experience", (("Avery Kim", "person"), ("Q4 pipeline review", "concept"))),
        ),
    },
)

_SAMPLE_TYPED_FACT = "The sample quarter closes on December 31."
_SAMPLE_OBSERVATION = (
    "Both at-risk Q4 deals are waiting on the customer: a signing deadline at "
    "Halvorsen Freight and a security review at Kestrel Foods."
)


def seed_memory(memory) -> int:
    """Write the labelled sample memories; returns the facts written.
    A locked or missing store is left alone. Any earlier sample rows are
    cleared first, so a re-seed cannot mint twins."""
    if memory is None or memory.locked_cause is not None:
        return 0
    clear_memory(memory)
    now = memory.clock()
    written = []
    for excerpt in _SAMPLE_EXCERPTS:
        when = now - excerpt["days_ago"] * _DAY
        source_id = memory.add_source(excerpt["text"], speaker="You",
                                      context=SAMPLE_MEMORY_SOURCE)
        for text, kind, entities in excerpt["facts"]:
            fact = memory.add(text, source=SAMPLE_MEMORY_SOURCE, kind=kind,
                              occurrence_ts=when, source_id=source_id)
            memory.resolve_and_link(fact.id, list(entities))
            written.append(fact)
    typed = memory.add(_SAMPLE_TYPED_FACT, source=SAMPLE_MEMORY_SOURCE)
    written.append(typed)
    deadline = next(f for f in written if "December 15" in f.text)
    review = next(f for f in written if "security review is still open" in f.text)
    memory.save_observation("sample", _SAMPLE_OBSERVATION, 0.8,
                            [deadline.id, review.id], now=now)
    return len(written)


def clear_memory(memory) -> int:
    """Remove exactly the sample memories: facts written by the sample
    seed (their orphaned observations and entities go with them) and the
    sample excerpts. Returns the facts removed."""
    if memory is None or memory.locked_cause is not None:
        return 0
    ids = [fact.id for fact in memory.all() if fact.source == SAMPLE_MEMORY_SOURCE]
    if ids:
        memory.remove_facts(ids)
    memory.delete_sources(
        [excerpt.id for excerpt in memory.sources()
         if excerpt.context == SAMPLE_MEMORY_SOURCE]
    )
    return len(ids)
