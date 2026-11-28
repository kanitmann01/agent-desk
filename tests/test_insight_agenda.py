"""The pure helpers behind a reading: prep, memory links and focus topics.

Every rule that decides what a family adds lives in the helpers rather
than in the family, so the rules are pinned here:

- A meeting earns one sizing line from prepMinutes, then its own prep
  items, and never more than three lines in total.
- A remembered fact counts as being about a subject only when it shares a
  distinctive word with it, or when the subject has no such word to share.
- A focus topic is matched as typed, in the user's order, and at most three.
- A memory that is missing, sealed or failing yields no facts and no excuse:
  the context already explains itself in memory_note.

The calendar family is built straight on these helpers and adds nothing of
its own beyond the wording, so its reading is pinned here too.
"""

import pytest

from nexuusbot.insight import agenda, calendar
from nexuusbot.insight.types import InsightContext

NOW = 1_760_000_000.0


def context(**kwargs) -> InsightContext:
    """A context with only the parts a helper reads."""
    preferences = kwargs.pop("preferences", {})
    return InsightContext(preferences=preferences, now=NOW, **kwargs)


def agenda_row(**kwargs) -> dict:
    """The next meeting as context.build_context shapes it."""
    row = {
        "title": "Quarterly pricing review",
        "time": "Today 14:00",
        "meta": "Studio 2",
        "prep": [],
    }
    row.update(kwargs)
    return row


def test_normalise_collapses_case_and_spacing():
    assert agenda.normalise("  Q3   Pricing Review ") == "q3 pricing review"
    assert agenda.normalise(None) == ""


def test_truncate_marks_what_it_cut_and_stays_within_the_cap():
    assert agenda.truncate("pricing review", 20) == "pricing review"
    assert agenda.truncate("pricing review", 10) == "pricing..."
    assert len(agenda.truncate("pricing review", 10)) == 10
    assert agenda.truncate(None, 10) == ""


def test_mentions_needs_a_distinctive_word():
    fact = "Priya pushed the pricing sheet to the shared drive."
    assert agenda.mentions(fact, "Quarterly pricing review") is True
    # "review" is too common to identify a meeting on its own.
    assert agenda.mentions("The review notes are in the folder.", "Quarterly pricing review") is False
    # A subject with no distinctive word cannot filter anything.
    assert agenda.mentions("The review notes are in the folder.", "Weekly review") is True


def test_focus_matches_keeps_the_users_order_and_caps_at_three():
    preferences = {"focusTopics": ["pricing", "renewals", "hiring", "security"]}
    text = "Pricing review with Priya, then renewals and hiring"
    assert agenda.focus_matches(text, preferences) == ["pricing", "renewals", "hiring"]


def test_focus_matches_ignores_topics_too_short_to_mean_anything():
    assert agenda.focus_matches("a review of pricing", {"focusTopics": ["a"]}) == []
    assert agenda.focus_matches("", {"focusTopics": ["pricing"]}) == []
    assert agenda.focus_matches("pricing", {"focusTopics": "pricing"}) == []


def test_focus_overlap_reads_the_title_and_the_meta():
    preferences = {"focusTopics": ["pricing", "studio 2"]}
    assert agenda.focus_overlap(agenda_row(), preferences) == ["pricing", "studio 2"]
    assert agenda.focus_overlap({}, preferences) == []


def test_prep_items_start_with_the_prep_window():
    preferences = {"prepMinutes": 30, "focusTopics": ["pricing"]}
    assert agenda.prep_items(agenda_row(), preferences)[0] == {
        "text": "Set aside 30 minutes before this. Focus: pricing.",
        "done": False,
        "due": "",
    }


def test_prep_items_uses_the_default_window_and_says_so_when_it_is_off():
    assert agenda.prep_items(agenda_row(), {})[0]["text"] == (
        "Set aside 15 minutes before this."
    )
    assert agenda.prep_items(agenda_row(), {"prepMinutes": 0})[0]["text"] == (
        "No prep window is set."
    )
    # A stored value outside the allowed range is not trusted.
    assert agenda.prep_items(agenda_row(), {"prepMinutes": 240})[0]["text"] == (
        "Set aside 15 minutes before this."
    )


def test_prep_items_skip_what_the_card_shows_and_stop_at_three():
    row = agenda_row(
        prep=[
            "Print the pricing sheet",
            "Read the renewal email",
            "Book Studio 2",
            "Update the deck",
        ]
    )
    items = agenda.prep_items(row, {}, skip=["Print the   Pricing Sheet"])
    assert [item["text"] for item in items] == [
        "Set aside 15 minutes before this.",
        "Read the renewal email",
        "Book Studio 2",
    ]
    assert len(items) == agenda.MAX_ITEMS


def test_prep_items_are_offered_undone_rather_than_guessed_at():
    items = agenda.prep_items(agenda_row(prep=["Bring the numbers"]), {})
    assert all(item["done"] is False and item["due"] == "" for item in items)


def test_prep_checklist_is_a_renderable_element():
    element = agenda.prep_checklist(agenda_row(), {"prepMinutes": 10})
    assert element["kind"] == "checklist"
    assert element["title"] == "Before the meeting"
    assert element["items"][0]["text"] == "Set aside 10 minutes before this."


def test_recalled_keeps_only_facts_about_the_subject():
    facts = [
        {"text": "The pricing sheet lives in the drive folder.", "source": "notes"},
        {"text": "Studio booking closes on Friday.", "source": "calendar"},
    ]
    ctx = context(recall=lambda subject, limit: facts)
    assert agenda.recalled(ctx, "Quarterly pricing review") == [
        {"text": "The pricing sheet lives in the drive folder.", "source": "notes"}
    ]


def test_recalled_stops_at_the_limit_and_names_a_missing_source():
    facts = [{"text": f"Pricing note {number}"} for number in range(4)]
    ctx = context(recall=lambda subject, limit: facts)
    rows = agenda.recalled(ctx, "Pricing review", limit=2)
    assert len(rows) == 2
    assert rows[0]["source"] == "memory"


def test_recalled_without_memory_is_empty():
    assert agenda.recalled(context(), "Pricing review") == []
    assert agenda.recalled(context(), "") == []


def test_recalled_survives_a_failing_recall():
    def recall(subject, limit):
        raise RuntimeError("memory is locked")

    assert agenda.recalled(context(recall=recall), "Pricing review") == []


def test_recalled_asks_for_more_than_it_keeps_so_filtering_can_keep_two():
    asked = []

    def recall(subject, limit):
        asked.append(limit)
        return []

    agenda.recalled(context(recall=recall), "Pricing review", limit=2)
    assert asked and asked[0] > 2


def test_memory_lines_carry_the_source():
    ctx = context(
        recall=lambda subject, limit: [{"text": "Priya owns pricing.", "source": "notes"}]
    )
    assert agenda.memory_lines(ctx, "Pricing review") == [
        {"primary": "Last time: Priya owns pricing.", "secondary": "", "meta": "notes"}
    ]


# --- the calendar family, read through the same helpers -------------------


def calendar_payload() -> dict:
    """The elements meeting-prep renders, in the order it renders them."""
    return {
        "elements": [
            {"kind": "text", "label": "Next", "text": "Quarterly pricing review"},
            {"kind": "metric", "label": "Events today", "value": 3},
            {
                "kind": "checklist",
                "title": "Prep",
                "items": [{"text": "Print the pricing sheet", "done": False, "due": ""}],
            },
        ]
    }


def test_meeting_reading_lists_the_prep_and_the_memory():
    ctx = context(
        agenda=agenda_row(prep=["Print the pricing sheet", "Read the renewal email"]),
        recall=lambda subject, limit: [{"text": "Priya owns the pricing model.", "source": "notes"}],
        preferences={"prepMinutes": 20},
    )
    reading = calendar.derive({"pluginId": "meeting-prep"}, calendar_payload(), ctx)
    assert reading.status == "ok"
    assert [element["kind"] for element in reading.elements] == ["checklist", "list"]
    checklist = reading.elements[0]
    assert checklist["title"] == "Before the meeting"
    # The sizing line, then only the prep item the card does not already show.
    assert [item["text"] for item in checklist["items"]] == [
        "Set aside 20 minutes before this.",
        "Read the renewal email",
    ]
    assert "Quarterly pricing review" not in [
        item["text"] for item in checklist["items"]
    ]
    assert reading.elements[1] == {
        "kind": "list",
        "title": "From memory",
        "rows": [
            {
                "primary": "Last time: Priya owns the pricing model.",
                "secondary": "",
                "meta": "notes",
            }
        ],
    }


def test_meeting_reading_without_memory_says_why_and_invents_nothing():
    note = "Memory is not set up on this desk, so nothing was recalled."
    reading = calendar.derive(
        {"pluginId": "meeting-prep"}, calendar_payload(), context(agenda=agenda_row(), memory_note=note)
    )
    assert [element["kind"] for element in reading.elements] == ["checklist", "status"]
    assert reading.elements[1] == {"kind": "status", "text": note, "tone": "attention"}
    assert not any(element["kind"] == "list" for element in reading.elements)


def test_a_quiet_reading_is_one_line_and_puts_the_reason_in_the_note():
    note = "Memory is locked, so nothing was recalled."
    reading = calendar.derive(
        {"pluginId": "meeting-prep"},
        calendar_payload(),
        context(
            agenda=agenda_row(prep=["Print the pricing sheet", "Read the renewal email"]),
            memory_note=note,
            preferences={"insightDensity": "quiet"},
        ),
    )
    # Quiet folds the checklist into one text line rather than a list of one.
    assert reading.elements == [
        {"kind": "text", "label": "Prep", "text": "Set aside 15 minutes before this."}
    ]
    assert reading.note == note


def test_a_card_for_no_meeting_shows_the_reason_and_nothing_else():
    reason = "The calendar bridge is not available."
    reading = calendar.derive(
        {"pluginId": "meeting-prep"},
        calendar_payload(),
        context(agenda=None, agenda_note=reason),
    )
    assert reading.elements == []
    assert reading.status == "empty"
    assert reading.note == reason

