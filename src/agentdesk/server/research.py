"""The research panel and the assistant page, rendered server-side.

Mapping only; every dynamic value is escaped here. The research card is
an action surface: its stamp says Ready or shows when it last answered,
and progress is stated in words while the endpoint is being asked.
"""

import html
from datetime import datetime

from agentdesk.server.core import FRESH, Freshness
from agentdesk.server.pages import page_shell
from agentdesk.server.demo import Widget

RESEARCH_BUSY = "Asking the company endpoint for a sourced summary"

# The save-to-memory excerpt's bound (ticket #91): a few thousand
# characters of the visible conversation, recent turns kept first.
RETAIN_EXCERPT_MAX_CHARS = 4000


def _retain_excerpt(turns: list) -> str:
    """The visible conversation as plain text, turn structure kept
    ("You: ..." / "Assistant: ..." lines), newest turn last. Recent
    turns fill the cap from the end, so an older turn is dropped whole
    rather than cut."""
    lines = [
        ("You" if turn["role"] == "user" else "Assistant") + ": " + turn["text"]
        for turn in turns
    ]
    excerpt = ""
    for line in reversed(lines):
        candidate = line if not excerpt else line + "\n" + excerpt
        if len(candidate) > RETAIN_EXCERPT_MAX_CHARS:
            break
        excerpt = candidate
    return excerpt


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


def render_assistant_page(
    turns: list, version: str, inbox_count: int = 0, retain_error: str = ""
) -> str:
    """The assistant page: the thread so far, one input, one button,
    and the save-to-memory action (ticket #91). `retain_error` is the
    plain-language cause a failed retain shows on its re-render."""
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
    error_line = (
        f'<p class="empty">{html.escape(retain_error)}</p>' if retain_error else ""
    )
    retain_form = ""
    if turns:
        excerpt = html.escape(_retain_excerpt(turns), quote=True)
        retain_form = (
            '<form class="cardrow" method="post" action="/memory/retain">'
            f'<input type="hidden" name="excerpt" value="{excerpt}">'
            '<button class="btn btn-secondary" type="submit">Save to memory</button>'
            "</form>"
            '<p class="empty">Saving sends the visible conversation to the '
            "endpoint to be turned into candidate facts. Nothing is written "
            "until you accept a card in the inbox.</p>"
        )
    content = f"""<h1>Assistant</h1>
<p>One thread with your dashboard's context attached. Requests go to the
company endpoint; every call is logged.</p>
<div class="thread" aria-label="Conversation">
{thread}
</div>
{error_line}
<form class="cardrow" method="post" action="/assistant/ask">
<textarea class="well-input grow" name="question" rows="2" required
 aria-label="Ask the assistant" placeholder="What changed, and what should I do about it?"></textarea>
<button class="btn btn-primary" type="submit">Ask</button>
</form>
{retain_form}
<p class="empty">Answers lean on the connected widgets when they can; they
say so when they cannot.</p>"""
    return page_shell("Assistant", "/assistant", content, version, inbox_count=inbox_count)
