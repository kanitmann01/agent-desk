"""The inbox page: cards, their age, their way back.

Server-rendered in the design language. The empty state is a good empty:
it names the object, says what will appear, and links to the recent
activity, because an empty inbox should still tell you where to look.
"""

import html
from datetime import datetime

from agentdesk.inbox.core import STATUS_DISMISSED, Card
from agentdesk.server.core import ATTENTION, FRESH, Freshness
from agentdesk.server.demo import Widget  # noqa: F401  (contract reference)

_KIND_LABEL = {
    "suggestion": "Suggestion",
    "skill_proposal": "Pattern noticed",
    "update_consent": "Update needs your OK",
    "brief": "Before your meeting",
}


def card_html(card: Card, now_ts: float) -> str:
    """One card: origin line, title, body, actions, visible aging."""
    created = datetime.fromtimestamp(card.created_ts)
    age = f"Waiting since {created.strftime('%H:%M')}"
    expired = card.is_expired(now_ts)
    window = ""
    if card.window_hours is not None:
        window = f"<span class='empty'> Time window: {card.window_hours:g}h.</span>"
        if expired:
            age += ", window passed"
    expired_class = " amber" if expired else ""
    body_html = f"<p>{html.escape(card.body)}</p>" if card.body else ""
    action = (
        f"<button class='btn btn-primary' data-accept='{html.escape(card.id)}'>"
        f"{html.escape(card.action_label or 'Accept')}</button>"
    )
    return (
        f"<article class='widget{expired_class}' id='card-{html.escape(card.id)}' "
        f"data-freshness-status='{'attention' if expired else 'fresh'}'>"
        "<div class='w-head'>"
        f"<span class='origin-line'>{html.escape(_KIND_LABEL.get(card.kind, card.kind))}</span>"
        f"<span class='stamp'><span class='dot{' amber' if expired else ''}' aria-hidden='true'></span>"
        f"{html.escape(age)}</span></div>"
        f"<h3>{html.escape(card.title)}</h3>"
        f"{body_html}"
        f"<p class='origin-why'>{html.escape(card.origin)}{window}</p>"
        "<div class='cardrow'>"
        f"{action}"
        f"<button class='btn btn-secondary' data-dismiss='{html.escape(card.id)}'>Dismiss</button>"
        "</div></article>"
    )


def render_inbox_page(waiting: list[Card], dismissed: list[Card], version: str, now_ts: float) -> str:
    """The full inbox document, with the good empty and the recovery shelf."""
    esc_version = html.escape(version)
    if waiting:
        cards_html = "".join(card_html(c, now_ts) for c in waiting)
        empty = ""
    else:
        cards_html = ""
        empty = (
            "<div class='widget' id='inbox-empty'>"
            "<div class='w-head'><h2 style='font-size:16px'>Nothing needs your attention</h2></div>"
            "<p>When the agent notices a pattern, an update, or a brief worth "
            "seeing, it lands here as a card. It never interrupts you otherwise.</p>"
            "<p><a href='/what-this-touches'>See what the app has been doing</a></p>"
            "</div>"
        )
    if dismissed:
        shelf = "".join(
            f"<div class='ask'><b>{html.escape(c.title)}</b> "
            f"<span class='empty'>dismissed {c.dismissed_for_days(now_ts):.0f} days ago,"
            " recoverable for 30 days total</span> "
            f"<button class='btn btn-secondary btn-start' data-restore='{html.escape(c.id)}'>"
            "Restore</button></div>"
            for c in dismissed
        )
        shelf = f"<h1 style='margin-top:28px'>Dismissed</h1>{shelf}"
    else:
        shelf = "<p class='empty' style='margin-top:18px'>Dismissed cards stay recoverable here for 30 days. Nothing expires silently.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inbox, Agent Desk</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="doc">
<h1>Inbox</h1>
<p>Everything the agent initiates waits here under your interruption
budget: quiet hours 18:00-08:00, at most three notifications a day.</p>
{empty}
{cards_html}
{shelf}
<p class="empty"><a href="/">Back to the dashboard</a> <span class="mono">{esc_version}</span></p>
</div>
<script src="/static/app.js"></script>
</body>
</html>
"""
