"""Rendered pages for the English-to-plugin wizard (ticket #11).

The wizard walks a manager from a plain-English description to a small
declarative plugin, or stops honestly and exports a feature request.
This module renders the screens only; the server owns the sessions and
the POST endpoints. Every screen is one static document built from
plain HTML forms: no scripts, no inline styles, no external
references, so the strict Content-Security-Policy holds and every step
works with JavaScript turned off.

The server hands the session over as a plain JSON-shaped dict. Every
key is optional; a missing one renders as an honest empty state rather
than an error:

    {
        "id": "wiz-7c2",        # names /wizard/<id>/answer|approve|escalate
        "state": "describing",  # describing | questions | preview
                                # | approved | escalated
        "description": "...",   # the user's own words, echoed back
        "questions": [          # multiple-choice steps, in order
            {"question": "...", "options": ["...", ...], "default": "..."},
        ],
        "draft": {...},         # the plugin draft manifest
        "ui_schema": {...},     # declarative widget shape, see preview_lines
        "sample_rows": [{...}], # rows the preview renders
        "cannot": "...",        # escalated: what the wizard cannot do
    }
"""

import html

STATE_DESCRIBING = "describing"
STATE_QUESTIONS = "questions"
STATE_PREVIEW = "preview"
STATE_APPROVED = "approved"
STATE_ESCALATED = "escalated"

# Copy pinned by the ticket: the consolidated approval always says the
# same three things about capability, in the same words, built from the
# manifest's actual permissions (nothing granted is never claimed away).
NEVER_NO_CODE = "Runs no code"
NEVER_NO_NETWORK = "Opens no network connection"
NEVER_NO_WRITES = "Writes no files"
REMOVE_LINE = "Delete it from the Plugins surface, or delete the app folder."

DEFAULT_CANNOT = (
    "Widgets here read allowed files and draw cards; they cannot run "
    "code, reach the network or send mail, so anything needing that "
    "goes to a person instead."
)


def _esc(value: object) -> str:
    """Escape any dynamic value for HTML text or attribute context."""
    return html.escape("" if value is None else str(value))


def _string_list(value: object) -> list[str]:
    """The strings of a JSON list, or an empty list for anything else."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _draft_of(session_json: dict) -> dict:
    """The session's plugin draft, or an empty draft when absent."""
    draft = session_json.get("draft")
    return draft if isinstance(draft, dict) else {}


def _questions_of(session_json: dict) -> list[dict]:
    """The session's questions, in order, skipping malformed entries."""
    questions = session_json.get("questions")
    if not isinstance(questions, list):
        return []
    return [q for q in questions if isinstance(q, dict)]


def _does_line(draft: dict) -> str:
    """One plain line for what the plugin does: description, then title."""
    for key in ("description", "title"):
        value = draft.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    ui_schema = draft.get("ui_schema")
    if isinstance(ui_schema, dict):
        value = ui_schema.get("title")
        if isinstance(value, str) and value.strip():
            return value.strip()
    contributes = draft.get("contributes")
    if isinstance(contributes, dict):
        widgets = contributes.get("widgets")
        if isinstance(widgets, list):
            for widget in widgets:
                if isinstance(widget, dict):
                    value = widget.get("title") or widget.get("id")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    name = draft.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "a small declarative widget"


def approval_summary(draft: dict) -> dict:
    """The consolidated one-block summary from a plugin draft manifest.

    Returns {"does", "reads", "never", "remove"}: one line for what the
    plugin does, every filesystem read glob it needs, the things it can
    never do (each claim backed by an actual permission: shell "none"
    or absent, an empty network allow list, no write globs; the host is
    deny-by-default, so an absent permission is no capability), and the
    fixed removal line.
    """
    if not isinstance(draft, dict):
        draft = {}
    permissions = draft.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    filesystem = permissions.get("filesystem")
    if not isinstance(filesystem, dict):
        filesystem = {}
    network = permissions.get("network")
    network_allow = network.get("allow") if isinstance(network, dict) else []
    never: list[str] = []
    if permissions.get("shell", "none") == "none":
        never.append(NEVER_NO_CODE)
    if not _string_list(network_allow):
        never.append(NEVER_NO_NETWORK)
    if not _string_list(filesystem.get("write")):
        never.append(NEVER_NO_WRITES)
    return {
        "does": _does_line(draft),
        "reads": _string_list(filesystem.get("read")),
        "never": never,
        "remove": REMOVE_LINE,
    }


def preview_lines(ui_schema: dict, sample_rows: list[dict]) -> list[str]:
    """Plain text lines for the preview card, from a declarative schema.

    Two shapes exist and both render. The compiler's card schema carries
    ``elements`` (text and metric bindings). The table schemas carry
    ``columns`` (one line per row, cells joined by " | ") or ``fields``
    (one "field: value" line per field of the first sample row). Anything
    missing or malformed simply contributes fewer lines.
    """
    if not isinstance(ui_schema, dict):
        ui_schema = {}
    if not isinstance(sample_rows, list):
        sample_rows = []
    lines: list[str] = []
    title = ui_schema.get("title")
    if isinstance(title, str) and title.strip():
        lines.append(title.strip())
    elements = ui_schema.get("elements")
    if isinstance(elements, list):
        first = next((r for r in sample_rows if isinstance(r, dict)), None)
        for element in elements:
            if not isinstance(element, dict):
                continue
            if element.get("type") == "text" and str(element.get("text", "")).strip():
                lines.append(str(element["text"]).strip())
            elif element.get("type") == "metric":
                binding = str(element.get("binding", "value"))
                value = _first_value(sample_rows) or "sample value"
                lines.append(f"{binding}: {value}")
    columns = [c for c in _string_list(ui_schema.get("columns"))]
    fields = _string_list(ui_schema.get("fields"))
    if columns:
        for row in sample_rows:
            if not isinstance(row, dict):
                continue
            cells = [str(row.get(name, "")) for name in columns]
            lines.append(" | ".join(cells))
        return lines
    if fields:
        first = next((r for r in sample_rows if isinstance(r, dict)), None)
        if first is not None:
            lines.extend(f"{name}: {first.get(name, '')}" for name in fields)
    return lines


def _first_value(sample_rows: list[dict]) -> str:
    """A single sample value for a metric binding, or empty."""
    for row in sample_rows:
        if isinstance(row, dict):
            for value in row.values():
                if value not in ("", None):
                    return str(value)
    return ""


def _summary_html(summary: dict) -> str:
    """The consolidated approval block: does, reads, never, remove."""
    chips = "".join(
        f'<span class="src">{_esc(glob)}</span>'
        for glob in summary.get("reads") or []
        if isinstance(glob, str)
    )
    read_html = chips or "<p>No files.</p>"
    never_html = "".join(
        f"<p>{_esc(line)}</p>" for line in summary.get("never") or []
    )
    return (
        '<section class="answer" aria-label="Approval summary">'
        '<p class="subhead">What it does</p>'
        f"<p>{_esc(summary.get('does'))}</p>"
        '<p class="subhead">What it reads</p>'
        f"<div>{read_html}</div>"
        '<p class="subhead">What it can never do</p>'
        f"{never_html}"
        '<p class="subhead">How to remove it</p>'
        f"<p>{_esc(summary.get('remove'))}</p>"
        "</section>"
    )


def _questions_html(session_json: dict) -> str:
    """One plain form per question: radios, default checked, one Ask."""
    sid = _esc(session_json.get("id"))
    blocks: list[str] = []
    for idx, question in enumerate(_questions_of(session_json)):
        options = _string_list(question.get("options"))
        default = question.get("default")
        if options and default not in options:
            default = options[0]
        inputs: list[str] = []
        for option in options:
            checked = " checked" if option == default else ""
            inputs.append(
                '<label class="check"><input type="radio" name="answer" '
                f'value="{_esc(option)}"{checked}>{_esc(option)}</label>'
            )
        if inputs:
            inputs_html = "".join(inputs)
        else:
            inputs_html = '<input type="text" name="answer" class="well-input">'
        blocks.append(
            f'<form class="answer" method="post" action="/wizard/{sid}/answer">'
            f'<input type="hidden" name="question" value="{idx}">'
            f'<p class="aq">{_esc(question.get("question"))}</p>'
            f"{inputs_html}"
            '<div class="cardrow"><button type="submit" class="btn btn-primary">'
            "Ask</button></div></form>"
        )
    return "".join(blocks)


def _conversation_html(session_json: dict) -> str:
    """The describing and questions screen: the echo, then the forms."""
    sid = _esc(session_json.get("id"))
    description = str(session_json.get("description") or "")
    parts: list[str] = [
        "<h1>Describe a plugin</h1>",
        "<p>Plain English only. A few questions, then a preview; "
        "nothing is added until you approve it.</p>",
    ]
    note = str(session_json.get("degradedNote") or "")
    if note:
        # Honest degradation: the standard questions are named as such,
        # never passed off as tailored ones.
        parts.append(f'<div class="alert"><p>{_esc(note)}</p></div>')
    if description.strip():
        parts.append(
            '<section class="answer" aria-label="Your request">'
            '<p class="aq">You asked for</p>'
            f"<p>{_esc(description)}</p></section>"
        )
    parts.append(_questions_html(session_json))
    if not description.strip() and not _questions_of(session_json):
        parts.append(
            f'<form class="answer" method="post" action="/wizard/{sid}/answer">'
            '<p class="aq">What should the plugin do?</p>'
            "<label for=\"wizard-description\">Describe it in one or two "
            "sentences.</label>"
            '<textarea id="wizard-description" name="description" '
            'class="well-input" rows="3"></textarea>'
            '<div class="cardrow"><button type="submit" class="btn btn-primary">'
            "Ask</button></div></form>"
        )
    return "".join(parts)


def _preview_html(session_json: dict) -> str:
    """The dry-run screen: widget preview, approval block, the two actions."""
    sid = _esc(session_json.get("id"))
    lines = preview_lines(
        session_json.get("ui_schema") or {}, session_json.get("sample_rows") or []
    )
    if lines:
        widget_body = "<pre>" + "\n".join(_esc(line) for line in lines) + "</pre>"
    else:
        widget_body = '<p class="empty">Nothing to preview yet.</p>'
    return (
        "<h1>Preview</h1>"
        "<p>This is what you would see every morning. Nothing is added "
        "until you approve it.</p>"
        '<section class="widget" aria-label="Dry-run preview">'
        '<div class="w-head"><h2>Your widget</h2>'
        '<span class="stamp"><span class="dot sample" aria-hidden="true">'
        "</span>Preview, sample data</span></div>"
        f"{widget_body}</section>"
        f"{_summary_html(approval_summary(_draft_of(session_json)))}"
        '<div class="cardrow">'
        f'<form method="post" action="/wizard/{sid}/approve">'
        '<button type="submit" class="btn btn-primary">Add widget</button></form>'
        f'<form method="post" action="/wizard/{sid}/escalate">'
        '<button type="submit" class="btn btn-secondary">Not right? '
        "Escalate it</button></form>"
        "</div>"
    )


def _approved_html(session_json: dict) -> str:
    """The installed screen: summary, pilot-mode removal line, the
    publish step, way back."""
    installed = session_json.get("installed")
    plugin_id = ""
    if isinstance(installed, dict):
        candidate = str(installed.get("id", "")).strip()
        plugin_id = candidate if candidate else ""
    publish_form = ""
    if plugin_id:
        # The create-to-publish loop: a plain form post to the plugins
        # page's publish action, no JavaScript anywhere in it.
        publish_form = (
            f'<form method="post" action="/plugins/{_esc(plugin_id)}/publish">'
            '<button type="submit" class="btn btn-primary">'
            "Publish to the registry</button></form>"
        )
    return (
        "<h1>Added</h1>"
        "<p>The widget is on your dashboard now.</p>"
        '<p><span class="badge-pilot">Pilot</span> It runs in pilot mode. '
        "Remove it from the Plugins surface whenever you want.</p>"
        f"{_summary_html(approval_summary(_draft_of(session_json)))}"
        f'<div class="cardrow">{publish_form}'
        '<a class="btn btn-secondary" href="/">'
        "Back to the dashboard</a></div>"
    )


def _escalated_html(session_json: dict) -> str:
    """The honest dead-end: what cannot be done, the exported request."""
    reason = (
        session_json.get("cannot")
        or session_json.get("cannot_reason")
        or session_json.get("reason")
        or DEFAULT_CANNOT
    )
    request = str(session_json.get("request") or session_json.get("description") or "")
    if request.strip():
        request_html = f"<pre>{_esc(request)}</pre>"
    else:
        request_html = '<p class="empty">No request text was captured.</p>'
    return (
        "<h1>Not buildable yet</h1>"
        f"<p>{_esc(reason)}</p>"
        "<p>I can't build this automatically yet. Your words went to the "
        "technical owner as a feature request, unchanged:</p>"
        f"{request_html}"
        '<div class="cardrow"><a class="btn btn-secondary" href="/">'
        "Back to the dashboard</a></div>"
    )


def _page_shell(title: str, body: str, version: str) -> str:
    """The document shell: the local stylesheet only, nothing else. The
    wizard keeps its focused no-rail shell, but carries the same
    breadcrumb so the way back is never a mystery."""
    esc_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc_title}, Agent Desk</title>
<script src="/static/theme-boot.js"></script>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="doc">
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Agent Desk</a><span class="crumb-sep" aria-hidden="true">/</span><span aria-current="page">{esc_title}</span></nav>
{body}
<footer class="page-foot"><span>Agent Desk <span class="mono">{html.escape(version)}</span>.</span><span>Local only: nothing here reaches the internet.</span></footer>
</div>
</body>
</html>
"""


def render_wizard_page(session_json: dict, version: str) -> str:
    """The wizard screen for one session, rendered by state.

    describing and questions share the conversation screen: the user's
    description echoed back, then one multiple-choice form per question
    (radio options, the default pre-selected, one Ask button per form,
    because a form posts to /wizard/<id>/answer and must work without
    JavaScript). preview shows the dry-run widget from preview_lines,
    labeled as preview, the consolidated approval block, the Approve
    form (POST /wizard/<id>/approve) and the escalate form (POST
    /wizard/<id>/escalate; a plain link cannot POST, so the escape is a
    quiet button). approved shows the summary, the pilot-mode removal
    line, the publish step (POST /plugins/<id>/publish, offered when
    the session recorded its install) and the way back. escalated is
    the honest dead-end: what the wizard cannot do and the feature
    request exported in the user's own words.
    """
    if not isinstance(session_json, dict):
        session_json = {}
    state = session_json.get("state")
    if state == STATE_PREVIEW:
        title, body = "Preview", _preview_html(session_json)
    elif state == STATE_APPROVED:
        title, body = "Added", _approved_html(session_json)
    elif state == STATE_ESCALATED:
        title, body = "Feature request sent", _escalated_html(session_json)
    else:
        # describing, questions, and any unknown state land on the
        # conversation screen and render its honest empty state.
        title, body = "Plugin wizard", _conversation_html(session_json)
    return _page_shell(title, body, version)
