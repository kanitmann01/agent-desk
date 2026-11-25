"""The capabilities page: the environment gates, the endpoint, the sources.

Ported from the teammate's capabilities page and probe module: status
cards with a plain cause each. Divergences by design: the gate cards
render the cached probe results with their age (their panel probes on
view; this page never probes on render, only on the explicit Re-test
POST), and there is no model listing in v1 (the chat adapter is
chat-only, the chassis is bring-your-own OpenAI-compatible
endpoint, so their Ollama checks are not adopted). The endpoint card and
the source cards read the same live connection table the dashboard and
/health read, plus the truth about the last model call: a down endpoint
names its error, it never reads green.
"""

import html
from datetime import datetime

from agentdesk.server.pages import page_shell, status_line
from agentdesk.calendar.watcher import (
    STATE_CLEAR as CALENDAR_CLEAR,
    STATE_HEALTHY as CALENDAR_HEALTHY,
    STATE_STALE as CALENDAR_STALE,
    STATE_UNREADABLE as CALENDAR_UNREADABLE,
)
from agentdesk.capabilities import GATES, CachedGate
from agentdesk.excel.core import (
    STATE_FIRST_SNAPSHOT,
    STATE_HEALTHY as EXCEL_HEALTHY,
    STATE_LOCKED,
    STATE_STALE as EXCEL_STALE,
    STATE_UNREADABLE,
)
from agentdesk.server.core import (
    SRC_CALENDAR,
    SRC_EXCEL,
    SRC_RESEARCH,
    STATUS_CONNECTED,
    SourceStatus,
)

# The watch state words the cards render: unconfigured, watching, error.
# The word can never contradict the connection table (a source health
# calls connected is at least watching), the watch's own error states
# name themselves with their cause, and the tuples are the constants the
# watches export, never re-spelled literals (a copy already drifted once).
# Anything else degrades to watching rather than a guess.
_EXCEL_WATCHING = (EXCEL_HEALTHY, STATE_FIRST_SNAPSHOT)
_EXCEL_ERROR = (STATE_LOCKED, STATE_UNREADABLE, EXCEL_STALE)
_CALENDAR_WATCHING = (CALENDAR_HEALTHY, CALENDAR_CLEAR)
_CALENDAR_ERROR = (CALENDAR_STALE, CALENDAR_UNREADABLE)


def _watch_word(
    row_status: str,
    status: dict | None,
    watching: tuple[str, ...],
    error: tuple[str, ...],
) -> str:
    """The word a source card shows, from the connection table and the watch state.

    unconfigured wins over any watch state because a source health calls disconnected
    has no watch to read; a state listed in error names itself, and anything else reads
    as watching rather than a guess.
    """
    if row_status != STATUS_CONNECTED:
        return "unconfigured"
    if status is not None:
        state = status.get("state") or ""
        if state in error:
            return "error"
        if state in watching:
            return "watching"
    return "watching"


def _age_text(now_ts: float, updated_ts: float) -> str:
    """How old a stored result reads, in plain words. The stamp on every
    card is the honesty rule: a stored pass is never presented as the
    current answer, only as the last answer and its age."""
    seconds = max(0, int(now_ts - updated_ts))
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 60:
        return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    return "1 day ago" if days == 1 else f"{days} days ago"


def _gate_cards(cached: dict[str, CachedGate | None], now_ts: float) -> str:
    """One card per P0 gate: status, plain cause, evidence, the stored
    time, and the re-test action. A never-tested gate says so."""
    cards = []
    for key, number, title in GATES:
        esc_key = html.escape(key)
        entry = cached.get(key)
        if entry is None:
            body = (
                "<p><b>Not tested</b> on this machine yet. Re-test runs the "
                "real probe once and stores the answer here with its time.</p>"
            )
        else:
            result = entry.result
            cause = html.escape(result.note)
            head = f"<p><b class='mono'>{html.escape(result.status)}</b>"
            body = head + (f" {cause}</p>" if result.note else "</p>")
            if result.evidence:
                lines = "".join(f"<li>{html.escape(line)}</li>" for line in result.evidence)
                body += f"<ul class='empty mono'>{lines}</ul>"
            stamp = datetime.fromtimestamp(entry.updated_ts).strftime("%m-%d %H:%M")
            body += (
                f"<p class='empty'>Tested {stamp} "
                f"({_age_text(now_ts, entry.updated_ts)}).</p>"
            )
        cards.append(
            f"<article class='widget' id='gate-{esc_key}'>"
            f"<div class='w-head'><h2>Gate {number}: {html.escape(title)}</h2></div>"
            f"{body}"
            f"<form method='post' action='/capabilities/{esc_key}/retest' class='cardform' "
            f"data-wait='#gate-{esc_key}' data-wait-shape='card' "
            f"data-wait-label='Running gate {number}. The probe reads this machine once.' "
            f"data-busy='Testing...'>"
            f"<button class='btn btn-secondary' type='submit'>Re-test gate {number}</button>"
            "</form>"
            "</article>"
        )
    return "".join(cards)


def _endpoint_card(sources: list[SourceStatus], endpoint: dict) -> str:
    """The company endpoint from the live connection table plus the truth
    about the last model call (the settings page's honesty rules). The
    table is the only source of the state and its detail: live_sources
    always emits both, and a private copy here would drift."""
    row = next(s for s in sources if s.id == SRC_RESEARCH)
    detail = html.escape(row.detail)
    line = (
        f"<p><b>Connected.</b> {detail}</p>"
        if row.status == STATUS_CONNECTED
        else f"<p><b>Not connected.</b> {detail}</p>"
    )
    last = str(endpoint.get("last", "never"))
    last_line = (
        f"<p class='empty'>Last call: <b class='mono'>{html.escape(last)}</b>"
        + (" (research and the assistant are running at reduced capacity)"
           if last == "error" else "")
        + "</p>"
    )
    base = html.escape(str(endpoint.get("base", "")))
    model = html.escape(str(endpoint.get("model", "")))
    target = f"<p class='empty mono'>{base} / {model}</p>" if base else ""
    return (
        "<article class='widget' id='card-endpoint'>"
        "<div class='w-head'><h2>Company endpoint</h2></div>"
        + line
        + last_line
        + target
        + "<p class='empty'>No model listing: the chat adapter is chat-only "
        "in this version, pointed at one endpoint you configure.</p>"
        + "</article>"
    )


def _source_card(title: str, word: str, detail: str, cause: str = "",
                 card_id: str = "") -> str:
    """One source card: title, the watch word as a stamp, detail and an optional cause.

    Every value is escaped; the cause line appears only for an error that carries a
    cause. `card_id` names the DOM id when a card is addressed from elsewhere (the
    mail card is).
    """
    cause_line = (
        f" <span class='empty'>{html.escape(cause)}</span>"
        if word == "error" and cause
        else ""
    )
    id_attr = f" id='{card_id}'" if card_id else ""
    return (
        f"<article class='widget'{id_attr}>"
        f"<div class='w-head'><h2>{html.escape(title)}</h2>"
        f"<span class='stamp'>{html.escape(word)}</span></div>"
        f"<p>{html.escape(detail)}{cause_line}</p>"
        "</article>"
    )


def _source_cards(
    sources: list[SourceStatus],
    excel_status: dict | None,
    calendar_status: dict | None,
) -> str:
    """The workbook and calendar cards from the same live table health
    reads. (The research endpoint is the endpoint card above; the mail
    card is separate, because its off state is a settings fact, not a
    connection fact.)"""
    rows = {s.id: s for s in sources}
    excel_row = rows[SRC_EXCEL]
    calendar_row = rows[SRC_CALENDAR]
    excel_word = _watch_word(
        excel_row.status, excel_status, _EXCEL_WATCHING, _EXCEL_ERROR,
    )
    calendar_word = _watch_word(
        calendar_row.status, calendar_status, _CALENDAR_WATCHING, _CALENDAR_ERROR,
    )
    excel_cause = str((excel_status or {}).get("cause", ""))
    calendar_cause = str((calendar_status or {}).get("cause", ""))
    return _source_card("Sales workbook", excel_word, excel_row.detail, excel_cause) + _source_card(
        "Calendar bridge", calendar_word, calendar_row.detail, calendar_cause
    )


def _mail_card(mail: dict) -> str:
    """The mail source card, the source card builder with the mail
    card's DOM id. The word comes straight from the caller:
    off (the settings toggle), unconfigured (no folder chosen),
    watching, or error, and the word can never contradict the toggle
    because the caller read both from the same place."""
    return _source_card(
        "Mail folder", str(mail.get("word", "")), str(mail.get("detail", "")),
        str(mail.get("cause", "")), card_id="card-mail",
    )


def render_capabilities_page(
    cached: dict[str, CachedGate | None],
    sources: list[SourceStatus],
    excel_status: dict | None,
    calendar_status: dict | None,
    endpoint: dict,
    version: str,
    now_ts: float,
    mail: dict | None = None,
    inbox_count: int = 0,
    notice: str = "",
    notice_kind: str = "status",
) -> str:
    """The full capabilities document: gate cards from the cache, the
    endpoint card and source cards from the live table, and the mail
    card when the mail toggle exists. Rendering probes nothing; the
    re-test forms are the only probing path. `notice` names the outcome
    of the last re-test on the page that arrives after it."""
    mail_html = _mail_card(mail) if mail is not None else ""
    content = f"""<h1>Capabilities</h1>
{status_line(notice, notice_kind)}
<p class='empty'><a href="/settings">Back to settings</a></p>
<p>What this laptop offers the agent: the five environment gates the
probe checks, the company endpoint, and the data sources. Gate results
are stored, not probed live: every card names when it was tested, and
Re-test runs the real probe once, right then, and stores the answer. The
command-line probe stays available for IT.</p>
{_gate_cards(cached, now_ts)}
{_endpoint_card(sources, endpoint)}
{_source_cards(sources, excel_status, calendar_status)}
{mail_html}"""
    return page_shell("Capabilities", "/settings", content, version, inbox_count=inbox_count)
