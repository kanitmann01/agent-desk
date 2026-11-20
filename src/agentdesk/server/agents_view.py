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
from agentdesk.agents.runner import STATUS_DEGRADED
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


def _slides_text(artifact: dict) -> str:
    """An old slides artifact as plain lines, so history still reads.

    The structured outline is gone; a stored deck is its title, then
    each slide title and its bullets, one line each.
    """
    lines = []
    title = str(artifact.get("title") or "").strip()
    if title:
        lines.append(title)
    for slide in artifact.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        slide_title = str(slide.get("title") or "").strip()
        if slide_title:
            lines.append(slide_title)
        for bullet in slide.get("bullets") or []:
            text = str(bullet).strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)


def _artifact_html(run: dict) -> str:
    """The artifact as text. Nothing the model returned is markup.

    A current outline is its text. An old slides row, from before the
    outline-only agent was removed, is the same: plain lines in a pre,
    never a list the page builds from the model's structure.
    """
    artifact = run.get("artifact")
    if not artifact:
        return ""
    if artifact.get("kind") == "slides":
        text = _slides_text(artifact)
    else:
        text = str(artifact.get("text", ""))
    if not text:
        return ""
    return f"<pre>{_esc(text)}</pre>"


def _feedback_html(run: dict) -> str:
    """The run's "how did it land?" form, or the feedback once it landed.

    A plain form POST per run, so the page keeps the no-JavaScript
    promise; a recorded feedback renders with its own timestamp and the
    form steps aside, because the run carries one record, the latest.
    """
    run_id = run["id"]
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
                       history_available: bool = True) -> str:
    """The full agents document: the roster with a run form per agent,
    then the run history newest first with receipts and artifacts.

    `runs` carries the store's shaped rows; `history_available` False is
    the honest state of a store that could not open (the roster still
    renders, the history says why it is absent).
    """
    roster = "".join(_brief_form(agent) for agent in agents)
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
