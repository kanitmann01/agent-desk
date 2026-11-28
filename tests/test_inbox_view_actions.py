"""The inbox action does what its label says (spec 020).

A card whose recommendation meta carries a local href is a link to that
page. It must not be rendered as the accept button: accepting consumes
the card and lands nowhere, while the label promised a page.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.inbox.core import KIND_SUGGESTION
from nexuusbot.inbox.store import InboxStore
from nexuusbot.server.inbox_view import card_html

NOW = 1763650000.0


def _card(href, label):
    inbox = InboxStore(
        sqlite3.connect(":memory:", check_same_thread=False), lambda: NOW)
    meta = {"recommendation": {"href": href}} if href else {}
    return inbox.add(
        KIND_SUGGESTION,
        "A meeting is coming.",
        "Prep the Q3 review",
        action_label=label,
        meta=meta,
    )


def test_a_recommendation_with_a_page_renders_a_link():
    markup = card_html(_card("/assistant", "Prep in Assistant"), NOW)
    assert "<a class='btn btn-primary' href='/assistant'>Prep in Assistant</a>" in markup
    assert "data-accept" not in markup


def test_a_card_without_a_page_still_renders_accept():
    markup = card_html(_card(None, "Accept"), NOW)
    assert "data-accept=" in markup
    assert ">Accept</button>" in markup
