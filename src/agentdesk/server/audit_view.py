"""The activity page under Settings: one trail for everything.

The old activity page showed inbox decisions only and sent every other
row to the CSV export. That split made the desk's own record invisible
from inside the app: model calls, file reads, plugin changes and settings
saves were happening but no screen showed them. This page shows the
audit store as one trail, newest first, plus the questions typed into
research and the assistant (which live in their own table). The CSV
export stays byte-identical; it is the same rows in the shape Security
reads.
"""

import html
from datetime import datetime

from agentdesk.server.activity_view import DECISIONS
from agentdesk.server.pages import page_shell

# Every action prefix the audit vocabulary uses, and the plain word the
# trail calls it. Order is stable: the summary line follows it.
KINDS = (
    ("inbox.", "Decision"),
    ("demo.", "Decision"),
    ("memory.", "Memory"),
    ("llm.", "Model call"),
    ("excel.", "File"),
    ("calendar.", "File"),
    ("mail.", "Mail"),
    ("plugin.", "Plugin"),
    ("registry.", "Registry"),
    ("settings.", "Settings"),
    ("peer.", "Peer"),
)


def kind_for(action: str) -> str:
    """The trail's word for an action, from its family prefix."""
    for prefix, label in KINDS:
        if action.startswith(prefix):
            return label
    return "Other"


def word_for(action: str) -> str:
    """A decision's plain word, or the action code for everything else."""
    return DECISIONS.get(action, action)


def when_text(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def kind_counts(entries: list[dict]) -> str:
    """One honest sentence: how many rows of each kind are on the page."""
    counts: dict[str, int] = {}
    for entry in entries:
        label = kind_for(entry.get("action", ""))
        counts[label] = counts.get(label, 0) + 1
    parts: list[str] = []
    seen: set[str] = set()
    for _prefix, label in KINDS:
        if label in seen:
            continue
        seen.add(label)
        count = counts.get(label)
        if count:
            parts.append(f"{count} {label.lower()}")
    if not parts:
        return ""
    return ", ".join(parts)


def _rows(entries: list[dict]) -> str:
    body = []
    for entry in entries:
        action = str(entry.get("action", ""))
        word = word_for(action)
        detail = html.escape(str(entry.get("detail", ""))[:200])
        target = html.escape(str(entry.get("target", "")))
        code = (
            f" <span class='empty mono'>{html.escape(action)}</span>"
            if word != action else ""
        )
        what = detail
        if target and target != action:
            what = f"{what} <span class='empty mono'>{target}</span>" if what else (
                f"<span class='empty mono'>{target}</span>"
            )
        status = str(entry.get("status", "ok"))
        status_html = (
            "<span class='empty'>ok</span>" if status == "ok"
            else f"<b>{html.escape(status)}</b>"
        )
        body.append(
            "<tr><td class='mono'>"
            f"{when_text(float(entry.get('ts', 0)))}</td>"
            f"<td>{html.escape(kind_for(action))}</td>"
            f"<td><b>{html.escape(word)}</b>{code}</td>"
            f"<td>{what}</td><td>{status_html}</td></tr>"
        )
    return (
        "<table class='rows'><thead><tr><th scope='col'>When</th>"
        "<th scope='col'>Kind</th><th scope='col'>Action</th>"
        "<th scope='col'>What</th><th scope='col'>Status</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _questions(questions: list[dict]) -> str:
    if not questions:
        return (
            "<p class='empty'>Nothing asked yet. Research and assistant "
            "questions land here, for you to see.</p>"
        )
    body = "".join(
        "<tr><td class='mono'>"
        f"{when_text(float(q.get('ts', 0)))}</td>"
        f"<td>{html.escape(str(q.get('kind', '')))}</td>"
        f"<td>{html.escape(str(q.get('text', ''))[:200])}</td></tr>"
        for q in reversed(questions)
    )
    return (
        "<table class='rows'><thead><tr><th scope='col'>When</th>"
        "<th scope='col'>Kind</th><th scope='col'>What you asked</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _filter_bar(entries: list[dict], kind: str | None) -> str:
    """The kind filter: one link per family present, plus All."""
    counts: dict[str, int] = {}
    for entry in entries:
        label = kind_for(entry.get("action", ""))
        counts[label] = counts.get(label, 0) + 1
    labels = []
    for _prefix, label in KINDS:
        if label not in labels and counts.get(label):
            labels.append(label)
    links = []
    all_class = "btn btn-secondary" if kind else "btn"
    links.append(f"<a class='{all_class}' href='/settings/activity'>All {len(entries)}</a>")
    for label in labels:
        active = "btn" if label == kind else "btn btn-secondary"
        links.append(
            f"<a class='{active}' href='/settings/activity?kind="
            f"{html.escape(label, quote=True)}'>{html.escape(label)} "
            f"{counts[label]}</a>"
        )
    return "<p class='settings-links'>" + "".join(links) + "</p>"


def render_audit_page(
    entries: list[dict],
    questions: list[dict],
    version: str,
    inbox_count: int = 0,
    kind: str | None = None,
) -> str:
    """The full trail document, newest first, inside the Settings rail."""
    # The filter names a family; an unknown name shows the whole trail
    # rather than an empty screen with no way to tell why.
    known = {label for _prefix, label in KINDS}
    if kind not in known:
        kind = None
    shown = [e for e in entries if kind_for(e.get("action", "")) == kind] if kind else entries
    summary = kind_counts(shown)
    failed = sum(1 for e in shown if str(e.get("status", "ok")) != "ok")
    summary_line = f"{len(shown)} entries"
    if kind:
        summary_line = f"{len(shown)} {kind.lower()} entries"
    if summary:
        summary_line += f": {summary}"
    if failed:
        summary_line += f" · {failed} with a failure status"
    if shown:
        trail = _rows(shown)
    elif kind:
        trail = f"<p class='empty'>Nothing of the {html.escape(kind)} kind yet.</p>"
    else:
        trail = (
            "<p class='empty'>Nothing recorded yet. Approve a card, read a "
            "workbook, install a plugin, change a setting or ask a question "
            "and it lands here, newest first.</p>"
        )
    questions_html = "" if kind else f"""<h2>Questions you asked</h2>
<p>The asks that flowed through research and the assistant. No
keystrokes, no screen, and this list is yours.</p>
{_questions(questions)}
"""
    content = f"""<h1>Activity</h1>
<p class='empty'><a href="/settings">Back to settings</a></p>
<p>Everything the desk recorded, newest first: inbox decisions, model
calls, file reads, mail, plugin and registry changes, settings saves and
peer traffic, plus the questions you typed. This is the screen behind the
<a href="/audit/export.csv">CSV export</a> Security reads; both show the
same rows.</p>
{_filter_bar(entries, kind)}
<p class='empty'>{html.escape(summary_line)}</p>
{trail}
{questions_html}"""
    return page_shell("Activity", "/settings", content, version, inbox_count=inbox_count)
