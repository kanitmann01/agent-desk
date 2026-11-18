"""Tests for the workbook family: two findings, one chart sentence, no guessing."""

from __future__ import annotations

import pytest

from agentdesk.insight import workbook
from agentdesk.insight.preferences import defaults
from agentdesk.insight.service import attach_cards
from agentdesk.insight.types import InsightContext

PRESS = {
    "label": "Explain this range",
    "route": "/api/insight/draft",
    "kind": "explain-range",
}


def _context(**preferences) -> InsightContext:
    document = defaults()
    document.update(preferences)
    return InsightContext(preferences=document, now=1_700_000_000.0)


def _tracker(headers, rows, **extra) -> dict:
    tracker = {
        "name": "Q3 bookings.xlsx",
        "value": "91",
        "unit": "",
        "delta": "+4",
        "direction": "up",
        "points": [],
        "file": "Q3 bookings.xlsx",
        "rowsSeen": len(rows),
        "table": {"headers": list(headers), "rows": [list(row) for row in rows]},
        "readAt": 1_700_000_000.0,
    }
    tracker.update(extra)
    return tracker


def _payload(headers=None, rows=None, **extra) -> dict:
    payload = {"elements": [{"kind": "metric", "label": "Total", "value": "91"}], "status": "fresh"}
    if headers is not None:
        payload["tracker"] = _tracker(headers, rows, **extra)
    return payload


def _card(payload: dict, plugin_id: str = "excel-report") -> dict:
    return {"id": plugin_id, "pluginId": plugin_id, "payload": payload}


def _mixed_rows():
    rows = []
    regions = ["A"] * 7 + ["B"] * 3 + ["C"] * 2
    # Alternating on purpose: a second trend would out-rank the share and
    # make the ordering test say nothing about the ranking.
    booked = [10, 4, 10, 4, 10, 4, 10, 4, 10, 4, 10, 4]
    for index in range(12):
        rows.append([f"2026-{index + 1:02d}-01", 10 + index, regions[index], booked[index]])
    return ["when", "amount", "region", "booked"], rows


# -- refusals --------------------------------------------------------------


def test_a_card_without_a_tracker_gets_one_plain_sentence():
    reading = workbook.derive(_card(_payload()), _payload(), _context())
    assert reading.elements == []
    assert reading.press is None
    assert reading.note == "This workbook card has no rows to read yet."


def test_a_card_without_a_table_gets_one_plain_sentence():
    payload = _payload(["a", "b"], [["1", "2"]], table=None)
    reading = workbook.derive(_card(payload), payload, _context())
    assert reading.elements == []
    assert "no table" in reading.note


def test_a_table_of_strings_yields_a_note_rather_than_a_claim():
    payload = _payload(["name", "note"], [["Dana", "paid"], ["Sam", "late"], ["Jo", "paid"]])
    reading = workbook.derive(_card(payload), payload, _context())
    assert reading.elements == []
    assert reading.press is None
    assert reading.note == (
        "Nothing in this range reads as a number, so there is no relationship to state."
    )


def test_one_numeric_column_without_a_finding_says_why():
    payload = _payload(["region", "amount"], [["A", 45], ["B", 28], ["C", 27]])
    reading = workbook.derive(_card(payload), payload, _context())
    assert reading.elements == []
    assert reading.note == (
        "Only one column here reads as a number, so there is nothing to hold it against."
    )


def test_a_single_numeric_column_can_still_carry_a_share():
    # The label column is the other half of the relationship, so this is not
    # a one-column table.
    payload = _payload(["region", "amount"], [["A", 51], ["B", 30], ["C", 19]])
    reading = workbook.derive(_card(payload), payload, _context())
    assert reading.elements[0]["label"] == "Share"
    assert {key: reading.press[key] for key in PRESS} == PRESS
    assert reading.press["text"] == reading.elements[0]["text"]


def test_a_table_that_clears_no_threshold_gets_a_note():
    # 45/28/27: the leader is under half, and the top two are more than 1.5x
    # apart, so neither a share nor a split may be claimed.
    payload = _payload(
        ["region", "amount", "cost"],
        [["A", 45, 5], ["B", 28, 5], ["C", 27, 5]],
    )
    reading = workbook.derive(_card(payload), payload, _context())
    assert reading.elements == []
    assert "too small or too flat" in reading.note


# -- findings --------------------------------------------------------------


def test_derive_states_the_strongest_two_and_the_chart():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    reading = workbook.derive(_card(payload), payload, _context())
    assert [element["kind"] for element in reading.elements] == ["text", "text", "text"]
    assert reading.elements[0]["label"] == "Trend"
    assert reading.elements[1]["label"] == "Share"
    assert reading.elements[2]["label"] == "Chart"
    assert reading.elements[2]["text"].startswith("A line chart fits this:")
    assert {key: reading.press[key] for key in PRESS} == PRESS
    assert reading.press["text"] == reading.elements[0]["text"]
    assert reading.note == ""


def test_two_findings_is_the_cap_even_when_more_hold():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    reading = workbook.derive(_card(payload), payload, _context())
    labels = [element["label"] for element in reading.elements]
    assert labels.count("Chart") == 1
    assert len([label for label in labels if label != "Chart"]) == workbook.MAX_FINDINGS == 2


def test_a_stated_chart_preference_is_honoured_and_explained():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    reading = workbook.derive(_card(payload), payload, _context(chart="bar"))
    chart = reading.elements[-1]
    assert chart["label"] == "Chart"
    assert "Your chart setting asks for a bar chart" in chart["text"]
    assert "line chart" in chart["text"]


def test_an_unknown_chart_preference_falls_back_to_auto():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    reading = workbook.derive(_card(payload), payload, _context(chart="pie"))
    chart = reading.elements[-1]
    assert "chart setting" not in chart["text"]
    assert chart["text"].startswith("A line chart fits this:")


def test_one_numeric_column_with_a_date_still_reads():
    values = [10, 11, 12, 13, 14, 15]
    rows = [[f"2026-0{index + 1}-01", value] for index, value in enumerate(values)]
    payload = _payload(["when", "amount"], rows)
    reading = workbook.derive(_card(payload), payload, _context())
    assert reading.elements[0]["label"] == "Trend"
    assert {key: reading.press[key] for key in PRESS} == PRESS
    assert reading.press["text"] == reading.elements[0]["text"]


# -- checklist and density -------------------------------------------------


def test_chatty_density_offers_the_rows_behind_the_findings():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    reading = workbook.derive(_card(payload), payload, _context(insightDensity="chatty"))
    checklist = reading.elements[-1]
    assert checklist["kind"] == "checklist"
    assert checklist["title"] == "Rows worth selecting"
    assert len(checklist["items"]) == 5
    assert checklist["items"][0]["text"].startswith("Row 1: 2026-01-01")
    assert checklist["items"][0]["done"] is False


def test_normal_density_carries_no_checklist():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    reading = workbook.derive(_card(payload), payload, _context())
    assert all(element["kind"] == "text" for element in reading.elements)


# -- through the seam ------------------------------------------------------


def test_attach_cards_adds_the_reading_and_the_press_offer():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    card = _card(payload)
    attach_cards([card], _context())
    kinds = [element["kind"] for element in payload["elements"]]
    assert kinds[0] == "metric"
    assert kinds[1:] == ["text", "text", "text"]
    assert payload["insight"]["press"]["kind"] == PRESS["kind"]
    assert payload["insight"]["press"]["text"] == payload["elements"][1]["text"]
    assert payload["insight"]["source"] == "local"
    assert payload["insight"]["status"] == "ok"


def test_attach_cards_leaves_a_string_table_untouched_and_says_why():
    payload = _payload(["name", "note"], [["Dana", "paid"], ["Sam", "late"], ["Jo", "paid"]])
    card = _card(payload)
    attach_cards([card], _context())
    assert payload["elements"] == [{"kind": "metric", "label": "Total", "value": "91"}]
    assert payload["insight"]["press"] is None
    assert "reads as a number" in payload["insight"]["note"]


def test_quiet_density_keeps_only_the_first_element():
    headers, rows = _mixed_rows()
    payload = _payload(headers, rows)
    card = _card(payload)
    attach_cards([card], _context(insightDensity="quiet"))
    assert len(payload["elements"]) == 2
    assert payload["elements"][1]["label"] == "Trend"


def test_suggested_rows_are_the_best_finding_capped_at_five():
    headers = ["Region", "Booked"]
    rows = [["A", 100], ["A", 100], ["A", 100], ["A", 100], ["A", 100],
            ["A", 100], ["B", 10], ["B", 10], ["C", 5]]
    payload = _payload(headers, rows)
    card = _card(payload)
    reading = workbook.derive(card, payload, _context())
    assert reading.suggested == (0, 1, 2, 3, 4)

    attach_cards([card], _context())
    assert card["payload"]["insight"]["suggested"] == [0, 1, 2, 3, 4]


def test_a_thin_table_suggests_no_rows():
    payload = _payload(["Region", "Booked"], [["A", 10], ["B", 12]])
    card = _card(payload)
    assert workbook.derive(card, payload, _context()).suggested == ()

    attach_cards([card], _context())
    assert card["payload"]["insight"]["suggested"] == []
