"""The research panel and the assistant page, rendered server-side.

Mapping only; every dynamic value is escaped here. The research card is
an action surface: its stamp says Ready or shows when it last answered,
and progress is stated in words while the endpoint is being asked.
"""

import html
from datetime import datetime

from agentdesk.server.core import FRESH, Freshness
from agentdesk.server.demo import Widget

RESEARCH_BUSY = "Asking the company endpoint for a sourced summary"


def render_research_widget(last_answered_ts: float | None, now: datetime) -> Widget:
    """The research card: the ask well, the answer area, honest stamp."""
    if last_answered_ts is not None:
        answered = datetime.fromtimestamp(last_answered_ts)
        fresh = Freshness(FRESH, f"Answered {answered.strftime('%H:%M')}",
                          answered.strftime("%Y-%m-%dT%H:%M:%S"))
    else:
        # An action surface, not a data widget: Ready, and never quiet.
        fresh = Freshness(FRESH, "Ready", now.strftime("%Y-%m-%dT%H:%M:%S"))
    return Widget(
        id="research",
        title="Research",
        col="col-8",
        freshness=fresh,
        body_html=(
            '<div class="well"><textarea id="research-question" class="well-input" '
            'rows="2" placeholder="Ask anything, or paste what you did and ask '
            'what to look for." aria-label="Research question"></textarea>'
            '<button class="btn btn-secondary" id="research-ask">Research</button></div>'
            '<div class="answer" id="research-answer" hidden></div>'
            f'<p class="empty" id="research-status" data-busy-text="{RESEARCH_BUSY}"></p>'
        ),
        foot_html="Searches run through the company endpoint. Every call is logged: what was asked, never file contents.",
    )


def render_assistant_page(turns: list, version: str) -> str:
    """The assistant page: the thread so far, one input, one button."""
    esc_version = html.escape(version)
    if turns:
        blocks = []
        for turn in turns:
            role = "You" if turn["role"] == "user" else "Assistant"
            body_class = "ask" if turn["role"] == "user" else "answer reply"
            blocks.append(
                f'<div class="{body_class}"><div class="who">{role}</div>'
                f"<p>{html.escape(turn['text'])}</p></div>"
            )
        thread = "".join(blocks)
    else:
        thread = (
            '<div class="answer"><p>Ask about your numbers, your day, or '
            "anything you pasted. I already know what the connected widgets "
            "know; you never have to re-explain it.</p></div>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Assistant, Agent Desk</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="doc">
<h1>Assistant</h1>
<p>One thread with your dashboard's context attached. Requests go to the
company endpoint; every call is logged.</p>
<div class="thread" aria-label="Conversation">
{thread}
</div>
<form class="cardrow" method="post" action="/assistant/ask">
<textarea class="well-input grow" name="question" rows="2" required
 aria-label="Ask the assistant" placeholder="What changed, and what should I do about it?"></textarea>
<button class="btn btn-primary" type="submit">Ask</button>
</form>
<p class="empty">Version <span class="mono">{esc_version}</span>. Answers lean on the connected widgets when they can; they say so when they cannot.</p>
<p class="empty"><a href="/">Back to the dashboard</a></p>
</div>
<script src="/static/app.js"></script>
</body>
</html>
"""
