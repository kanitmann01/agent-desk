"""The agents page: the roster with its run forms, and the run history
with each run's receipt, rendered server-side.

Mapping only; every dynamic value is escaped here, and the model's own
words are printed as text and structure, never as markup. Every action
is a plain form POST that lands back on the page, so the surface works
without JavaScript like the rest of the desk.
"""

from __future__ import annotations

import html
from datetime import datetime

from agentdesk.agents.registry import AgentKind, find_agent
from agentdesk.agents.runner import STATUS_DEGRADED, slides_text
from agentdesk.server.pages import page_shell

USED_NOTHING = "used nothing"


def _brief_form(agent: AgentKind) -> str:
    """One roster entry's run form: the agent's id rides in a hidden
    field, the brief in a textarea, both posted to the run route."""
    agent_id = _esc(agent.id)
    return (
        f'<article class="card" id="agent-{agent_id}">'
        f"<h3>{_esc(agent.name)}</h3>"
        f"<p>{_esc(agent.blurb)}</p>"
        '<form method="post" action="/agents/run" class="cardform">'
        f'<input type="hidden" name="agent" value="{agent_id}">'
        f'<label class="empty" for="brief-{agent_id}">Brief</label>'
        f'<textarea id="brief-{agent_id}" name="brief" rows="2" required '
        f'placeholder="e.g. the Q3 business review"></textarea>'
        f'<button class="btn btn-primary" type="submit">Run {_esc(agent.name)}</button>'
        "</form></article>"
    )


def _receipt_html(run: dict) -> str:
    """The run's receipt: the exact facts it used, or the plain words
    that it used nothing (so silence is never mistaken for a hidden
    read of the memory bank)."""
    facts = run.get("facts") or []
    if not facts:
        return f'<p class="empty">This run {USED_NOTHING} from memory.</p>'
    lines = "".join(
        f"<li>{_esc(row.get('text', ''))}</li>" for row in facts
    )
    return f"<p class='empty'>This run used these facts from memory:</p><ul>{lines}</ul>"


def _presentation_card(packs, endpoint_ready: bool, sentence: str,
                       research_ready: bool = False, research_sentence: str = "") -> str:
    """The template picker under the topic box.

    A plain form: one radio per pack, dark or light, one recipe. When
    the endpoint is off or unconfigured the controls are disabled and
    the page shows the same sentence the rest of the desk uses.
    """
    if not packs:
        return ""
    disabled = "" if endpoint_ready else " disabled"
    tiles = []
    recipes: list[str] = []
    variants: list[str] = []
    for pack in packs:
        checked = " checked" if not tiles else ""
        thumbs = ""
        for variant in ("dark", "light"):
            if pack.thumb_path(variant) is None and variant not in pack.thumbs:
                continue
            if variant not in variants:
                variants.append(variant)
            src = f"/agents/templates/{_esc(pack.id)}/{variant}.png"
            thumbs += (
                f'<img src="{src}" alt="{_esc(pack.name)}, {variant}" width="320" height="180">'
            )
        tiles.append(
            f'<label class="template-tile">'
            f'<input type="radio" name="template" value="{_esc(pack.id)}"{checked}{disabled}>'
            f'<span class="thumbs">{thumbs}</span>'
            f"<b>{_esc(pack.name)}</b></label>"
        )
        for path in pack.recipes:
            recipe_id = path.rsplit("/", 1)[-1].removesuffix(".json")
            if recipe_id not in recipes:
                recipes.append(recipe_id)
    labels = {
        "briefing": "Generic briefing",
        "qbr": "QBR",
        "competitor-brief": "Competitor brief",
    }
    options = "".join(
        f'<option value="{_esc(recipe)}">{_esc(labels.get(recipe, recipe))}</option>'
        for recipe in recipes
    )
    variant_rows = "".join(
        f'<label><input type="radio" name="variant" value="{variant}"'
        f'{" checked" if variant == "dark" else ""}{disabled}> {variant.title()}</label>'
        for variant in variants
    )
    note = f'<p class="empty">{_esc(sentence)}</p>' if sentence else ""
    if research_ready:
        research_html = (
            '<label><input type="checkbox" name="use_research" value="1"> Web research</label>'
        )
    else:
        research_html = (
            f'<p class="empty">{_esc(research_sentence)}</p>'
            '<label><input type="checkbox" name="use_research" value="1" disabled> Web research</label>'
        )
    return (
        '<article class="card" id="agent-presentation">'
        "<h3>Presentation</h3>"
        "<p>A deck from a template you pick. The topic is one short brief.</p>"
        f"{note}"
        '<form method="post" action="/agents/run" class="cardform presentation-form">'
        '<input type="hidden" name="agent" value="presentation">'
        '<label class="empty" for="brief-presentation">Topic</label>'
        f'<textarea id="brief-presentation" name="brief" rows="2" required{disabled} '
        'placeholder="e.g. the Q3 business review"></textarea>'
        f'<fieldset class="template-tiles"{disabled}><legend class="empty">Template</legend>'
        f'{"".join(tiles)}</fieldset>'
        f'<fieldset class="variant-row"{disabled}><legend class="empty">Variant</legend>'
        f"{variant_rows}</fieldset>"
        f'<label class="empty" for="recipe-presentation">Recipe</label>'
        f'<select id="recipe-presentation" name="recipe"{disabled}>{options}</select>'
        '<fieldset class="source-row"><legend class="empty">Use</legend>'
        '<input type="hidden" name="sources_form" value="1">'
        f'<label><input type="checkbox" name="use_memory" value="1" checked{disabled}> Memory</label>'
        f'<label><input type="checkbox" name="use_workbook" value="1" checked{disabled}> Workbook tracker</label>'
        f'<label><input type="checkbox" name="use_watch" value="1" checked{disabled}> Page watch</label>'
        '</fieldset>'
        f"{research_html}"
        f'<button class="btn btn-primary" type="submit"{disabled}>Run Presentation</button>'
        "</form>"
        '<details class="deck-tools"><summary>Deck tools (for agents and scripts)</summary>'
        '<p class="empty">These run without a model endpoint. Create, inspect and render '
        "return a file and a download address; outline returns text.</p>"
        "<ul>"
        "<li><code>presentation_outline</code> turns a one-line brief into slide text.</li>"
        "<li><code>presentation_create</code> writes a valid .pptx from that outline.</li>"
        "<li><code>presentation_inspect</code> reads a deck back as text and package checks.</li>"
        "<li><code>presentation_render</code> makes a PDF and slide images when PowerPoint "
        "or LibreOffice is installed.</li>"
        "</ul>"
        '<p class="empty">HTTP: <code>POST /api/presentation/tools</code> with '
        '<code>{"tool": "presentation_create", "brief": "the Q3 review"}</code>. '
        "Live schemas at <code>GET /api/presentation/tools</code>.</p>"
        '<p class="empty">CLI: <code>python -m agentdesk.presentations.cli create '
        '--brief "the Q3 review" --out deck.pptx</code></p>'
        "</details></article>"
    )


def _artifact_html(run: dict) -> str:
    """The artifact as text. Nothing the model returned is markup.

    A current outline is its text. An old slides row, from before the
    outline-only agent was removed, is the same: plain lines in a pre,
    never a list the page builds from the model's structure.
    """
    artifact = run.get("artifact")
    if not artifact:
        return ""
    run_id = _esc(str(run["id"]))
    if artifact.get("kind") == "slides":
        text = slides_text(artifact)
    elif artifact.get("kind") == "presentation":
        text = (
            f"Template {artifact.get('templateId', '')} "
            f"({artifact.get('variant', '')}), "
            f"recipe {artifact.get('recipe', '')}."
        )
        if artifact.get("phase") == "awaiting-review":
            rows = []
            for source in artifact.get("webSources") or []:
                rows.append(
                    "<label><input type='checkbox' name='keep' "
                    f"value='{_esc(source.get('id'))}' checked> "
                    f"{_esc(source.get('title') or '')} "
                    f"{_esc(source.get('url') or '')} "
                    f"{_esc(source.get('snippet') or '')}</label>"
                )
            form = (
                f'<form method="post" action="/agents/runs/{run_id}/sources" class="cardform">'
                + "".join(rows)
                + '<button class="btn btn-primary" type="submit">Build the deck</button></form>'
                f'<form method="post" action="/agents/runs/{run_id}/sources" class="cardform">'
                '<input type="hidden" name="continue" value="desk">'
                '<button class="btn" type="submit">Continue with desk sources only</button></form>'
                f'<form method="post" action="/agents/runs/{run_id}/sources" class="cardform">'
                '<input type="hidden" name="continue" value="cancel">'
                '<button class="btn" type="submit">Cancel</button></form>'
            )
            return f"<pre>{_esc(text)}</pre>" + form
        if artifact.get("phase") == "research-failed":
            return (
                f"<pre>{_esc(text)}</pre>"
                f'<form method="post" action="/agents/runs/{run_id}/sources" class="cardform">'
                '<input type="hidden" name="continue" value="desk">'
                '<button class="btn" type="submit">Continue with desk sources only</button></form>'
            )
        if artifact.get("file"):
            text_html = f"<pre>{_esc(text)}</pre>"
            href = f"/agents/runs/{run_id}/download"
            extra = _sources_html(artifact)
            if artifact.get("fit"):
                items = "".join(f"<li>{_esc(item)}</li>" for item in artifact["fit"])
                extra += "<p class='empty'>Slides adjusted to fit:</p><ul>" + items + "</ul>"
            if artifact.get("previewNote"):
                extra += f"<p class='empty'>{_esc(artifact['previewNote'])}</p>"
            if artifact.get("pdf"):
                extra += f'<p><a href="/agents/runs/{run_id}/download?part=pdf">Download PDF</a></p>'
            for image in artifact.get("images") or []:
                name = str(image).rsplit("/", 1)[-1]
                extra += (
                    f'<p><img src="/agents/runs/{run_id}/download?part={_esc(name)}" '
                    f'alt="Slide preview" width="320"></p>'
                )
            return text_html + extra + f'<p><a href="{href}">Download .pptx</a></p>'
    else:
        text = str(artifact.get("text", ""))
    if not text:
        return ""
    return f"<pre>{_esc(text)}</pre>"


def _sources_html(artifact: dict) -> str:
    """The receipt lines for a presentation: what was read, and when."""
    rows = artifact.get("sources") or []
    if not rows:
        return ""
    items = []
    for row in rows:
        when = f" ({_esc(row.get('at') or '')})" if row.get("at") else ""
        items.append(
            f"<li>{_esc(row.get('label', ''))}: {_esc(row.get('text', ''))}{when}</li>"
        )
    return "<p class='empty'>This run used these sources:</p><ul>" + "".join(items) + "</ul>"


def _feedback_html(run: dict) -> str:
    """The run's "how did it land?" form, or the feedback once it landed.

    A plain form POST per run, so the page keeps the no-JavaScript
    promise; a recorded feedback renders with its own timestamp and the
    form steps aside, because the run carries one record, the latest.
    """
    run_id = _esc(str(run["id"]))
    if run.get("feedback"):
        when = datetime.fromtimestamp(run["feedbackTs"]).strftime("%Y-%m-%d %H:%M")
        return (
            f'<p class="empty">Feedback ({when}): {_esc(run["feedback"])}</p>'
        )
    return (
        f'<form method="post" action="/agents/runs/{run_id}/feedback" class="cardform">'
        f'<label class="empty" for="feedback-{run_id}">How did it land?</label>'
        f'<textarea id="feedback-{run_id}" name="feedback" rows="2" required '
        f'placeholder="e.g. my manager liked it and wants it concise"></textarea>'
        f'<button class="btn" type="submit">Send feedback</button>'
        "</form>"
    )


def _run_html(run: dict) -> str:
    """One run row of the history: what was asked, what happened, what
    it used, what it produced, and how it landed. A degraded run keeps
    its cause and renders no artifact, because none existed."""
    agent = find_agent(run.get("agentId", ""))
    agent_name = agent.name if agent is not None else run.get("agentId", "")
    ran_at = datetime.fromtimestamp(run["createdTs"]).strftime("%Y-%m-%d %H:%M")
    if run["status"] == STATUS_DEGRADED:
        state = f"degraded: {_esc(run['cause'])}"
    else:
        state = "ok"
    return (
        f'<article class="card">'
        f"<h3>{_esc(agent_name)}</h3>"
        f'<p class="empty mono">{ran_at}, {state}</p>'
        f"<p>Brief: {_esc(run['brief'])}</p>"
        f"{_receipt_html(run)}"
        f"{_artifact_html(run)}"
        f"{_feedback_html(run)}"
        "</article>"
    )


def _esc(value: str) -> str:
    """Escape one dynamic string for the page.

    The single seam every model-derived and user-derived value passes
    through before it reaches the document.
    """
    return html.escape(str(value), quote=True)


def render_agents_page(agents, runs, version: str, inbox_count: int = 0,
                       history_available: bool = True, packs=(),
                       endpoint_ready: bool = False, endpoint_sentence: str = "",
                       research_ready: bool = False, research_sentence: str = "") -> str:
    """The full agents document: the roster with a run form per agent,
    then the run history newest first with receipts and artifacts.

    `runs` carries the store's shaped rows; `history_available` False is
    the honest state of a store that could not open (the roster still
    renders, the history says why it is absent).
    """
    roster = _presentation_card(
        packs, endpoint_ready, endpoint_sentence, research_ready, research_sentence,
    )
    roster += "".join(_brief_form(agent) for agent in agents)
    if not history_available:
        history = (
            '<p class="empty">The run history is not available right now: '
            "the runs store could not be opened. Nothing was lost.</p>"
        )
    elif runs:
        history = "".join(_run_html(run) for run in runs)
    else:
        history = "<p class='empty'>No runs yet. Give one of the agents above a brief.</p>"
    content = f"""<h1>Agents</h1>
<p>Task the desk with a brief. Each run recalls what the memory bank
knows about the topic, sends one prompt through the company endpoint,
and prints its receipt: the exact facts it used, or that it used
nothing.</p>
<h2>The roster</h2>
{roster}
<h2>Run history</h2>
{history}"""
    return page_shell("Agents", "/agents", content, version, inbox_count=inbox_count)
