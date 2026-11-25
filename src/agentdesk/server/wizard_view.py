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

from agentdesk.server.pages import document_head, page_footer, status_line
from agentdesk.wizard.core import resolve_choice

# The two waits the wizard shows. The describe step and the answer that
# completes the choice are when the card and its chart are decided, so
# they draw the card sketch; a question that only opens the next one
# keeps the plain panel.
CARD_WAIT_SHAPE = "widget"
CARD_WAIT_LABEL = "Choosing your plugin's card and chart..."
QUESTION_WAIT_LABEL = "Working out your plugin..."

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
# The read line for a config-backed draft (T2): nothing is read at
# approval time, the workbook is picked per instance in setup.
SETUP_READS_LINE = "a workbook you pick in setup"

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


def _is_config_backed(draft: dict) -> bool:
    """True when the manifest declares config kinds: the plugin points
    at its data through instances, so its summary names the setup
    handoff and its manage surface is where setup lives. A glob-shaped
    draft has no setup to offer, and its copy must not claim otherwise."""
    config = draft.get("config")
    if not isinstance(config, dict):
        return False
    kinds = config.get("kinds")
    return isinstance(kinds, list) and bool(kinds)


def _questions_of(session_json: dict) -> list[dict]:
    """The session's questions, in order, skipping malformed entries."""
    questions = session_json.get("questions")
    if not isinstance(questions, list):
        return []
    return [q for q in questions if isinstance(q, dict)]


def _answer_reaches_card(question: dict, answers: dict) -> bool:
    """Whether answering this question completes the choice and builds the card.

    A source answer only opens the next question; it decides no card. A
    show, look, detail or update answer that leaves no other field open
    makes the server compose the card and chart, so that is the answer the
    widget sketch waits on. A free-text answer has no value yet, so any
    usable value stands in to see whether the rest of the choice resolves.
    """
    field = str(question.get("id") or "")
    if not field:
        return False
    candidate = dict(answers or {})
    options = _string_list(question.get("options"))
    if options:
        chosen = str(question.get("default") or "").strip()
        candidate[field] = chosen if chosen in options else options[0]
    else:
        candidate[field] = "a value"
    return resolve_choice(candidate) is not None


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
    reads = _string_list(filesystem.get("read"))
    if _is_config_backed(draft):
        # A config-backed draft grants no glob here (T2): its read line
        # names the setup handoff instead of a path nothing reads yet.
        reads = [SETUP_READS_LINE]
    return {
        "does": _does_line(draft),
        "reads": reads,
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
    """One plain form per open question: radios, or a text field.

    The form whose answer completes the choice draws the card sketch; a
    form that only opens the next question keeps the plain panel.
    """
    sid = _esc(session_json.get("id"))
    answers = session_json.get("answers")
    answers = answers if isinstance(answers, dict) else {}
    blocks: list[str] = []
    for idx, question in enumerate(_questions_of(session_json)):
        reaches = _answer_reaches_card(question, answers)
        shape = CARD_WAIT_SHAPE if reaches else "panel"
        label = CARD_WAIT_LABEL if reaches else QUESTION_WAIT_LABEL
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
            # No options means a free-text answer: the question it sits
            # under is the accessible name, so a screen reader never
            # announces an unnamed field.
            inputs_html = (
                '<input type="text" name="answer" class="well-input" '
                f'aria-label="{_esc(question.get("question"))}">'
            )
        blocks.append(
            f'<form class="answer" method="post" action="/wizard/{sid}/answer" '
            f'data-wait="#wizard-progress" data-wait-shape="{shape}" '
            f'data-wait-label="{label}" data-busy="Working...">'
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
        # A missing AI connection is an invitation, not an error: the
        # questions below work fully without one.
        parts.append(
            '<p class="w-note no-ai">'
            '<a href="/settings#connections">Add an AI connection</a> to fill '
            "these in from your description next time.</p>"
        )
    if session_json.get("autofilled"):
        parts.append(
            '<p class="w-note" role="status" data-autofilled="true">'
            "Filled in from your description. Change anything that is off."
            "</p>"
        )
    if description.strip():
        parts.append(
            '<section class="answer" aria-label="Your request">'
            '<p class="aq">You asked for</p>'
            f"<p>{_esc(description)}</p></section>"
        )
    parts.append(_questions_html(session_json))
    if not description.strip() and not _questions_of(session_json):
        parts.append(
            f'<form class="answer" method="post" action="/wizard/{sid}/answer" '
            f'data-wait="#wizard-progress" data-wait-shape="{CARD_WAIT_SHAPE}" '
            f'data-wait-label="{CARD_WAIT_LABEL}" data-busy="Working...">'
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
    fill_note = ""
    if session_json.get("autofilled"):
        fill_note = (
            '<p class="w-note" role="status" data-autofilled="true">'
            "Filled in from your description. Change anything that is off."
            "</p>"
        )
    return (
        "<h1>Preview</h1>"
        f"{status_line('Your preview is below.')}"
        "<p>This is what you would see every morning. Nothing is added "
        "until you approve it.</p>"
        f"{fill_note}"
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


def _installed_of(session_json: dict) -> dict:
    """The install record a finished session carries, or {} when absent."""
    installed = session_json.get("installed")
    return installed if isinstance(installed, dict) else {}


def _approved_html(session_json: dict) -> str:
    """The installed screen: what was installed (id, version), the pilot
    line, the summary, the honest next step, way back."""
    installed = _installed_of(session_json)
    draft = _draft_of(session_json)
    plugin_id = str(installed.get("id", "")).strip()
    version = str(installed.get("version", "")).strip()
    installed_line = ""
    if plugin_id:
        version_chip = (
            f' <span class="mono">{_esc(version)}</span>' if version else ""
        )
        installed_line = (
            '<section class="answer" aria-label="What was installed">'
            '<p class="subhead">Installed</p>'
            f'<p><span class="mono">{_esc(plugin_id)}</span>{version_chip} '
            '<span class="badge-pilot">Pilot</span></p>'
            "<p>It runs in pilot mode. Remove it from the Plugins surface "
            "whenever you want.</p>"
            "</section>"
        )
    cta = ""
    publish_form = ""
    if plugin_id:
        if _is_config_backed(draft):
            cta = (
                f'<a class="btn btn-primary" '
                f'href="/marketplace/plugin/{_esc(plugin_id)}/manage">'
                "Set up its data</a>"
            )
        else:
            cta = (
                f'<a class="btn btn-primary" '
                f'href="/marketplace/plugin/{_esc(plugin_id)}">'
                "Open in the marketplace</a>"
            )
        # The create-to-publish loop keeps its step: a plain form post to
        # the plugins page's publish action, no JavaScript anywhere in it.
        publish_form = (
            f'<form method="post" action="/plugins/{_esc(plugin_id)}/publish">'
            '<button type="submit" class="btn btn-secondary">'
            "Publish to the registry</button></form>"
        )
    return (
        "<h1>Added</h1>"
        f"{status_line('The widget is added and on your dashboard now.')}"
        "<p>The widget is on your dashboard now.</p>"
        f"{installed_line}"
        f"{_summary_html(approval_summary(draft))}"
        f'<div class="cardrow">{cta}{publish_form}'
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
    answers = session_json.get("answers")
    answers_html = ""
    if isinstance(answers, dict) and answers:
        lines = "".join(
            f"<li>{_esc(value)}</li>" for value in answers.values()
            if isinstance(value, str) and value.strip()
        )
        if lines:
            answers_html = (
                "<p>You chose:</p>"
                f"<ul aria-label='The answers you gave'>{lines}</ul>"
            )
    return (
        "<h1>Not buildable yet</h1>"
        f"<p>{_esc(reason)}</p>"
        f"{answers_html}"
        "<p>I can't build this automatically yet. Your words went to the "
        "technical owner as a feature request, unchanged:</p>"
        f"{request_html}"
        '<div class="cardrow"><a class="btn btn-secondary" href="/">'
        "Back to the dashboard</a></div>"
    )


def _page_shell(title: str, body: str, version: str) -> str:
    """The document shell over the shared head and footer helpers. The
    wizard keeps its focused no-rail shell, but carries the same
    breadcrumb so the way back is never a mystery."""
    esc_title = html.escape(title)
    return f"""{document_head(f"{title}, Agent Desk")}
<main id="main" class="doc">
<p class="page-status" id="page-note" role="status" hidden></p>
<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Agent Desk</a><span class="crumb-sep" aria-hidden="true">/</span><span aria-current="page">{esc_title}</span></nav>
{body}
<div id="wizard-progress"></div>
{page_footer(version, note="Local only: nothing here reaches the internet.", touches=False)}
</main>
<script src="/static/app.js"></script>
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
    quiet button). approved shows what was installed (id, version, the
    pilot badge), the summary, the pilot-mode removal line, and the
    honest next step: a config-backed draft links to its manage surface
    to set up its data, any other links to its marketplace page. The
    publish step (POST /plugins/<id>/publish, offered when the session
    recorded its install) and the way back ride along. escalated is
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
