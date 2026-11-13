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
from agentdesk.server.demo_data import is_sample_card
from agentdesk.server.pages import page_shell

_KIND_LABEL = {
    "suggestion": "Suggestion",
    "skill_proposal": "Pattern noticed",
    "update_consent": "Update needs your OK",
    "brief": "Before your meeting",
    "feature_request": "Feature request",
    "mail_digest": "Mail digest",
    "mail_follow_up": "Needs a reply",
}


def _sample_tag(card: Card) -> str:
    """The Sample tag, shared by the waiting card and the recovery
    shelf, so a dismissed sample card cannot surface unlabelled."""
    return " <span class='tag-sample'>Sample</span>" if is_sample_card(card) else ""


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
    card_id = html.escape(card.id)
    # The no-JS actions: edit the draft, snooze, ask for more info. Plain
    # forms, the wizard's style; each POSTs urlencoded and lands back on
    # the inbox via redirect. One grouping head and one shared grid keep
    # the three forms proportional and their buttons on one baseline.
    forms = (
        "<div class='cardrow cardforms'>"
        "<div class='subhead subhead-tight'>Ask the agent to follow up</div>"
        f"<form method='post' action='/inbox/cards/{card_id}/edit' class='cardform'>"
        f"<label class='empty' for='draft-{card_id}'>Draft</label>"
        f"<textarea id='draft-{card_id}' name='draft' rows='2'>"
        f"{html.escape(card.draft)}</textarea>"
        "<button class='btn btn-secondary' type='submit'>Save draft</button>"
        "</form>"
        f"<form method='post' action='/inbox/cards/{card_id}/snooze' class='cardform'>"
        f"<label class='empty' for='snooze-{card_id}'>Snooze</label>"
        f"<select id='snooze-{card_id}' name='choice'>"
        "<option value='1h'>One hour</option>"
        "<option value='tomorrow'>Tomorrow morning</option>"
        "</select>"
        "<button class='btn btn-secondary' type='submit'>Snooze</button>"
        "</form>"
        f"<form method='post' action='/inbox/cards/{card_id}/more-info' class='cardform'>"
        f"<label class='empty' for='info-{card_id}'>More info</label>"
        f"<input id='info-{card_id}' type='text' name='instruction' "
        "placeholder='What should the agent clarify?'>"
        "<button class='btn btn-secondary' type='submit'>Ask for more info</button>"
        "</form>"
    )
    if card.kind == "update_consent":
        # The scope choice the consents store keys on: accepting with the
        # box checked allows this exact widening for this plugin forever
        # (process lifetime), so identical re-asks never re-prompt. The
        # wide form takes its own full-width band under the grid.
        forms += (
            f"<form method='post' action='/inbox/cards/{card_id}/accept' class='cardform cardform-wide'>"
            "<label class='empty'>"
            "<input type='checkbox' name='for_plugin' value='1'>"
            " Also allow this exact widening for this plugin"
            "</label>"
            "<button class='btn btn-primary' type='submit'>Accept</button>"
            "</form>"
        )
    forms += "</div>"
    # A seeded card says Sample twice: the tag beside its kind, and the
    # origin line's own "Sample data:" opener. It can never read as live.
    return (
        f"<article class='widget{expired_class}' id='card-{html.escape(card.id)}' "
        f"data-freshness-status='{'attention' if expired else 'fresh'}'>"
        "<div class='w-head'>"
        f"<span class='origin-line'>{html.escape(_KIND_LABEL.get(card.kind, card.kind))}</span>"
        f"{_sample_tag(card)}"
        f"<span class='stamp'><span class='dot{' amber' if expired else ''}' aria-hidden='true'></span>"
        f"{html.escape(age)}</span></div>"
        f"<h3>{html.escape(card.title)}</h3>"
        f"{body_html}"
        f"<p class='origin-why'>{html.escape(card.origin)}{window}</p>"
        "<div class='cardrow'>"
        f"{action}"
        f"<button class='btn btn-secondary' data-dismiss='{html.escape(card.id)}'>Dismiss</button>"
        "</div>"
        f"{forms}"
        "</article>"
    )


def render_inbox_page(
    waiting: list[Card],
    dismissed: list[Card],
    version: str,
    now_ts: float,
    sample_data_on: bool = False,
) -> str:
    """The full inbox document, with the good empty and the recovery shelf."""
    if waiting:
        # The spaced stack: the audit measured 0px between consecutive
        # cards, so they read as one merged block.
        cards_html = (
            "<div class='card-stack'>"
            + "".join(card_html(c, now_ts) for c in waiting)
            + "</div>"
        )
        empty = ""
    else:
        cards_html = ""
        # The fresh desk's one offer: see the inbox working with labelled
        # sample data. A plain no-JS form post, the page's own style; the
        # switch also lives in Settings for later.
        offer = (
            "<form method='post' action='/settings/toggle' class='cardform'>"
            "<input type='hidden' name='key' value='sample_data'>"
            "<button class='btn btn-secondary' type='submit'>"
            "Show me what this looks like with sample data</button>"
            "</form>"
            "<p class='empty'>Sample data is labelled Sample everywhere it "
            "appears and is removed the moment the switch goes off. The "
            "switch also lives in <a href='/settings'>Settings</a>.</p>"
            if not sample_data_on
            else ""
        )
        empty = (
            "<div class='widget' id='inbox-empty'>"
            "<div class='w-head'><h2>Nothing needs your attention</h2></div>"
            "<p>When the agent notices a pattern, an update, or a brief worth "
            "seeing, it lands here as a card. It never interrupts you otherwise.</p>"
            f"{offer}"
            "<p><a href='/what-this-touches'>See what the app has been doing</a></p>"
            "</div>"
        )
    if dismissed:
        shelf = "".join(
            f"<div class='ask'><b>{html.escape(c.title)}</b>{_sample_tag(c)} "
            f"<span class='empty'>dismissed {c.dismissed_for_days(now_ts):.0f} days ago,"
            " recoverable for 30 days total</span> "
            f"<button class='btn btn-secondary btn-start' data-restore='{html.escape(c.id)}'>"
            "Restore</button></div>"
            for c in dismissed
        )
        shelf = f"<h2>Dismissed</h2>{shelf}"
    else:
        shelf = "<p class='empty'>Dismissed cards stay recoverable here for 30 days. Nothing expires silently.</p>"
    content = f"""<h1>Inbox</h1>
<p>Everything the agent initiates waits here under your interruption
budget: quiet hours 18:00-08:00, at most three notifications a day.</p>
{empty}
{cards_html}
{shelf}"""
    return page_shell("Inbox", "/inbox", content, version, inbox_count=len(waiting))
