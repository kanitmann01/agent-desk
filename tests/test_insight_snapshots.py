"""Last-seen snapshots and the one-line perceptual delta.

The store keeps what every tile showed when the user last explicitly
viewed the dashboard, and each read diffs the current tile against that
watermark. These tests walk the signature per family, the store's
tolerant read and atomic write, the attach seam's invariance when no
snapshot map is handed in, and the HTTP split the whole feature stands
on: repeated GET polls preserve the delta, the explicit view report
advances the watermark, a first-ever read invents nothing.
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from plugins_fixtures import VALID_PLUGIN_DIR, build_zip
from agentdesk.insight.service import attach_cards
from agentdesk.insight.snapshots import (
    PREFIX,
    SnapshotStore,
    card_signature,
    perceptual_delta,
)
from agentdesk.insight.types import InsightContext

NOW = 1_760_000_000.0

STORE_FILE = "insight_snapshots.json"


def _context() -> InsightContext:
    """A context with no stated preferences, at a fixed clock."""
    return InsightContext(preferences={}, now=NOW)


def _card(plugin_id: str, payload=None, freshness: str = "fresh",
          cause: str = "") -> dict:
    """One tile as the runtime shapes it, keyed like a confirmed main."""
    return {
        "id": f"{plugin_id}~main",
        "pluginId": plugin_id,
        "freshness": freshness,
        "cause": cause,
        "payload": payload,
    }


def _workbook_payload(value="120", headers=("Product line", "Units", "Revenue")) -> dict:
    """A tracker tile's payload: face elements plus the tracker block."""
    return {
        "elements": [
            {"kind": "metric", "label": "Value", "value": value},
            {"kind": "delta", "label": "Change", "value": "+4", "direction": "up"},
            {"kind": "text", "label": "Workbook", "text": "Q4 sales.xlsx"},
        ],
        "status": "fresh",
        "tracker": {
            "value": value,
            "unit": "deals",
            "delta": "+4",
            "rowsSeen": 2,
            "table": {
                "headers": list(headers),
                "rows": [["Atlas ERP modules", 44.0, 176000.0],
                         ["Beacon CRM", 22.0, 88000.0]],
            },
        },
    }


# -- signatures per family ------------------------------------------------


def test_workbook_signature_tracks_the_tracker_and_the_top_finding():
    """The workbook signature carries figure, unit, change, sheet shape
    and the finding sentence, and skips the file line of the card face."""
    payload = _workbook_payload()
    payload["elements"].append(
        {"kind": "text", "label": "Range", "text": "Atlas leads the range."})
    signature = card_signature(_card("excel-report", payload))
    assert signature["freshness"] == "fresh"
    assert signature["workbook"] == {
        "value": "120",
        "unit": "deals",
        "delta": "+4",
        "headers": ["Product line", "Units", "Revenue"],
        "rowsSeen": 2,
        "finding": "Atlas leads the range.",
    }


def test_digest_signature_keeps_ten_threads_of_subject_sender_age():
    """A digest tile signs at most ten threads, each as three lines."""
    rows = [{"primary": f"Thread {index}", "secondary": f"Sender {index}",
             "meta": f"{index} h ago"} for index in range(12)]
    payload = {"elements": [
        {"kind": "list", "title": "Active threads", "rows": rows},
    ]}
    signature = card_signature(_card("outlook-digest", payload))
    threads = signature["digest"]["threads"]
    assert len(threads) == 10
    assert threads[0] == ["Thread 0", "Sender 0", "0 h ago"]
    assert threads[9] == ["Thread 9", "Sender 9", "9 h ago"]


def test_calendar_signature_reads_title_time_meta_and_prep_count():
    """The calendar signature is the next meeting and its prep list."""
    payload = {"elements": [
        {"kind": "text", "label": "Next", "text": "Q4 pipeline review"},
        {"kind": "text", "label": "Time", "text": "14:00"},
        {"kind": "text", "label": "Where", "text": "Room Beaufort"},
        {"kind": "metric", "label": "Events today", "value": 3},
        {"kind": "checklist", "title": "Prep", "items": [
            {"text": "Print the sheet", "done": False, "due": ""},
            {"text": "Read the notes", "done": False, "due": ""},
        ]},
    ]}
    signature = card_signature(_card("calendar-today", payload))
    assert signature["calendar"] == {
        "title": "Q4 pipeline review",
        "time": "14:00",
        "meta": "Room Beaufort",
        "prep": 2,
    }


def test_research_signature_reads_answered_summary_prefix_and_sources():
    """The research signature is when the answer landed, how it opens
    and how many sources it cites, with the summary kept a prefix."""
    payload = {"elements": [
        {"kind": "text", "label": "Latest answer", "text": "Churn tracks onboarding. " * 12},
        {"kind": "metric", "label": "Sources", "value": "5"},
        {"kind": "text", "label": "Answered", "text": "2026-11-13 09:41"},
    ]}
    signature = card_signature(_card("research-brief", payload))
    research = signature["research"]
    assert research["answered"] == "2026-11-13 09:41"
    assert research["sources"] == "5"
    assert research["summary"].startswith("Churn tracks onboarding.")
    assert len(research["summary"]) <= 120


def test_generic_signature_counts_and_values_with_freshness_and_cause():
    """Any other tile signs its metric values, status lines and list row
    counts, beside the freshness and cause every tile carries."""
    payload = {"elements": [
        {"kind": "metric", "label": "Value", "value": "12"},
        {"kind": "status", "text": "waiting a day", "tone": "attention"},
        {"kind": "list", "title": "Rows", "rows": [{"primary": "a"}, {"primary": "b"}]},
    ]}
    card = _card("plugin-health", payload, freshness="stale", cause="older-than-window")
    signature = card_signature(card)
    assert signature["freshness"] == "stale"
    assert signature["cause"] == "older-than-window"
    assert signature["generic"] == {
        "metrics": [["Value", "12"]],
        "statuses": ["waiting a day"],
        "lists": [2],
    }
    assert card_signature(card) == signature


# -- the perceptual delta -------------------------------------------------


def test_no_delta_on_first_ever_snapshot():
    """A tile with no watermark says nothing: the desk invents no move."""
    signature = card_signature(_card("excel-report", _workbook_payload()))
    assert perceptual_delta(None, signature) == ""


def test_no_delta_on_identical_state():
    """The same tile twice says nothing."""
    signature = card_signature(_card("excel-report", _workbook_payload()))
    assert perceptual_delta(signature, card_signature(_card("excel-report", _workbook_payload()))) == ""


def test_a_freshness_transition_wins_over_everything_else():
    """Attention earned and attention cleared are the loudest change."""
    payload = {"elements": [{"kind": "metric", "label": "Value", "value": "12"}]}
    fresh = card_signature(_card("plugin-health", payload))
    amber = card_signature(_card("plugin-health", payload, freshness="attention",
                                 cause="No file matches"))
    assert perceptual_delta(fresh, amber) == PREFIX + "this tile needs attention."
    assert perceptual_delta(amber, fresh) == PREFIX + "this tile has fresh data again."


def test_a_workbook_column_appearance_beats_a_moved_value():
    """A structural sheet edit names the column before any figure."""
    before = card_signature(_card("excel-report", _workbook_payload()))
    after = card_signature(_card("excel-report", _workbook_payload(
        value="999", headers=("Product line", "Units", "Revenue", "Margin"))))
    assert perceptual_delta(before, after) == PREFIX + "a column appeared: Margin."


def test_a_moved_workbook_figure_names_the_move():
    """A moved tracker figure reads as a move, with its unit."""
    before = card_signature(_card("excel-report", _workbook_payload(value="120")))
    after = card_signature(_card("excel-report", _workbook_payload(value="150")))
    assert perceptual_delta(before, after) == (
        PREFIX + "your tracked figure moved from 120 to 150 deals.")


def test_a_new_digest_thread_is_named_before_a_quiet_or_aged_one():
    """New first, then quiet, then aged, one thread per sentence."""
    def payload(rows):
        return {"elements": [{"kind": "list", "title": "Active threads", "rows": rows}]}

    rows = [{"primary": "Pricing review", "secondary": "Priya", "meta": "2 h ago"}]
    before = card_signature(_card("outlook-digest", payload(rows)))

    grown = rows + [{"primary": "Renewal question", "secondary": "Tom", "meta": "1 h ago"}]
    assert perceptual_delta(before, card_signature(
        _card("outlook-digest", payload(grown)))) == (
        PREFIX + "a new thread arrived: Renewal question.")

    quiet = card_signature(_card("outlook-digest", payload([])))
    assert perceptual_delta(before, quiet) == PREFIX + "a thread went quiet: Pricing review."

    aged = [{"primary": "Pricing review", "secondary": "Priya", "meta": "6 h ago"}]
    assert perceptual_delta(before, card_signature(
        _card("outlook-digest", payload(aged)))) == (
        PREFIX + "a waiting thread aged: Pricing review is now 6 h ago.")


def test_a_moved_meeting_names_the_time_then_the_title():
    """A shifted meeting reads as a move first, a rename second."""
    elements = lambda title, time_: [  # noqa: E731
        {"kind": "text", "label": "Next", "text": title},
        {"kind": "text", "label": "Time", "text": time_},
    ]
    before = card_signature(_card("calendar-today", {"elements": elements("Q4 review", "14:00")}))
    moved = card_signature(_card("calendar-today", {"elements": elements("Q4 review", "15:30")}))
    assert perceptual_delta(before, moved) == PREFIX + "your next meeting moved from 14:00 to 15:30."
    renamed = card_signature(_card("calendar-today", {"elements": elements("Board review", "14:00")}))
    assert perceptual_delta(before, renamed) == PREFIX + "your next meeting is now Board review."


def test_a_newer_research_answer_is_named():
    """A research tile whose answer timestamp moved says a newer answer."""
    def payload(answered):
        return {"elements": [
            {"kind": "text", "label": "Latest answer", "text": "Churn tracks onboarding."},
            {"kind": "text", "label": "Answered", "text": answered},
        ]}

    before = card_signature(_card("research-brief", payload("2026-11-13 09:41")))
    after = card_signature(_card("research-brief", payload("2026-11-14 10:02")))
    assert perceptual_delta(before, after) == PREFIX + "a newer research answer landed."


def test_a_generic_tile_change_says_its_figures_moved():
    """Any other tile gets one honest line about its figures."""
    def payload(value):
        return {"elements": [{"kind": "metric", "label": "Value", "value": value}]}

    before = card_signature(_card("plugin-health", payload("12")))
    after = card_signature(_card("plugin-health", payload("14")))
    assert perceptual_delta(before, after) == PREFIX + "the figures on this tile changed."


# -- the store ------------------------------------------------------------


def test_the_store_round_trips_the_version_one_schema(tmp_path):
    """One record writes the spec's document, atomically, and reads back."""
    store = SnapshotStore(tmp_path)
    document = store.record([
        _card("excel-report", _workbook_payload()),
        _card("plugin-health", None, cause="older-than-window"),
    ])
    assert document["version"] == 1
    assert isinstance(document["viewedAt"], float)
    stored = json.loads((tmp_path / STORE_FILE).read_text(encoding="utf-8"))
    assert stored == document
    entry = stored["cards"]["excel-report~main"]
    assert set(entry) == {"seenAt", "pluginId", "signature"}
    assert entry["pluginId"] == "excel-report"
    assert SnapshotStore(tmp_path).read() == document
    assert not (tmp_path / (STORE_FILE + ".tmp")).exists()


def test_a_missing_corrupt_or_non_object_file_reads_empty(tmp_path):
    """Three broken states, one answer: the empty version 1 document."""
    empty = {"version": 1, "viewedAt": 0.0, "cards": {}}
    assert SnapshotStore(tmp_path).read() == empty
    (tmp_path / STORE_FILE).write_text("{ not json", encoding="utf-8")
    assert SnapshotStore(tmp_path).read() == empty
    (tmp_path / STORE_FILE).write_text("[1, 2]", encoding="utf-8")
    assert SnapshotStore(tmp_path).read() == empty


# -- the attach seam ------------------------------------------------------


def test_attach_without_snapshots_leaves_every_caller_unchanged(tmp_path):
    """snapshots=None is the old call: same payload, untouched None tiles."""
    card = _card("excel-report", _workbook_payload())
    plain = _card("excel-report", _workbook_payload())
    attach_cards([plain], _context())
    attach_cards([card], _context(), snapshots=None)
    assert card == plain

    orphan = _card("outlook-digest", None)
    attach_cards([orphan], _context(), snapshots=SnapshotStore(tmp_path).read())
    assert orphan["payload"] is None

    stranger = _card("plugin-health", {"elements": []})
    untouched = _card("plugin-health", {"elements": []})
    attach_cards([stranger], _context(), snapshots=SnapshotStore(tmp_path).read())
    assert stranger == untouched


def test_attach_prepends_the_delta_block_after_the_reading(tmp_path):
    """A viewed workbook tile whose figure moved opens with its line,
    ahead of the reading's own blocks."""
    store = SnapshotStore(tmp_path)
    viewed = _card("excel-report", _workbook_payload())
    attach_cards([viewed], _context())
    store.record([viewed])

    moved = _card("excel-report", _workbook_payload(value="150"))
    attach_cards([moved], _context(), snapshots=store.read()["cards"])
    blocks = moved["payload"]["insight"]["blocks"]
    assert blocks[0] == {
        "kind": "delta",
        "text": PREFIX + "your tracked figure moved from 120 to 150 deals.",
    }
    # The unchanged second view clears the line: the watermark advanced.
    attach_cards([moved], _context(), snapshots=store.record([moved])["cards"])
    assert [block["kind"] for block in moved["payload"]["insight"]["blocks"]] != []
    assert all(block["kind"] != "delta" for block in moved["payload"]["insight"]["blocks"])


def test_attach_initializes_a_payload_for_a_changed_attention_tile(tmp_path):
    """A tile with no payload at all still opens with its delta, in the
    same minimal insight shape the families serve."""
    store = SnapshotStore(tmp_path)
    store.record([_card("plugin-health", None, freshness="attention",
                        cause="No file matches")])
    recovered = _card("plugin-health", None, freshness="fresh")
    attach_cards([recovered], _context(), snapshots=store.read()["cards"])
    assert recovered["payload"]["insight"]["blocks"][0] == {
        "kind": "delta",
        "text": PREFIX + "this tile has fresh data again.",
    }
    assert recovered["payload"]["insight"]["source"] == "local"

    # An empty delta leaves the tile exactly as it was, payload and all:
    # the watermark advances to the recovered tile, then an identical one
    # reads no change.
    store.record([recovered])
    twin = _card("plugin-health", None, freshness="fresh")
    attach_cards([twin], _context(), snapshots=store.read()["cards"])
    assert twin["payload"] is None


# -- the HTTP split -------------------------------------------------------


@pytest.fixture()
def booted(tmp_path, monkeypatch):
    """The real server, with the desk data directory moved into the test."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def _manual_metric_zip(destination: Path) -> Path:
    """The fixture plugin, retargeted at a hand-kept metric file whose
    value the test rewrites between a view and a poll."""
    schema = {
        "type": "card",
        "title": "Hand-kept number",
        "elements": [{"type": "metric", "binding": "value", "label": "Value"}],
    }
    return build_zip(
        VALID_PLUGIN_DIR, destination,
        manifest_overrides={
            "contributes": {"widgets": [{
                "id": "sales-delta",
                "size": "2x1",
                "dataSource": {"type": "manual-metric"},
                "render": {"type": "ui-schema", "file": "manual.ui.json"},
            }]},
            # A hand-kept metric reads its own plugin-data file, so the
            # fixture's workspace read glob would hang as over-permission.
            "permissions": {"filesystem": {"read": [], "write": ["${pluginData}"]}},
            # No schedule or hook: a view-mode tile reads live on every
            # open, which is the poll the watermark is read against.
            "activationEvents": [],
        },
        extra_file=("manual.ui.json", json.dumps(schema)),
    )


def _write_manual_metric(booted, value: float) -> None:
    """Write the hand-kept number at the installed tile's plugin-data root."""
    entry = booted.server.plugins._read()["plugins"]["sales-delta-widget"]
    manual = Path(entry["data_dir"]) / "manual.json"
    manual.parent.mkdir(parents=True, exist_ok=True)
    manual.write_text(json.dumps({
        "value": value, "unit": "deals",
        "history": [{"at": "2026-11-26T09:00:00", "value": value}],
    }), encoding="utf-8")


def _insight_blocks(payload_card: dict) -> list:
    """The insight blocks one dashboard payload card carries."""
    insight = (payload_card.get("payload") or {}).get("insight") or {}
    return insight.get("blocks") or []


def test_repeated_polls_preserve_the_delta_until_the_view_advances(booted, tmp_path):
    """The watermark moves only on the explicit view report."""
    auth = booted.exchange()
    status, _headers, body = booted.post_json(
        "/api/plugins/install",
        {"zip_path": str(_manual_metric_zip(tmp_path / "manual.zip")), "source": "zip"},
        auth)
    assert status == 200, body
    _write_manual_metric(booted, 10)

    # Nothing was ever viewed: a first read invents no change.
    status, _headers, body = booted.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    assert all(block["kind"] != "delta" for block in _insight_blocks(cards[0]))
    store_path = Path(os.environ["AGENTDESK_DATA"]) / STORE_FILE

    # The explicit view records the watermark; a GET has not.
    assert not store_path.exists()
    status, _headers, body = booted.post_json("/api/dashboard/view", {}, auth)
    assert status == 200
    assert json.loads(body) == {"spent": 1}
    stored = json.loads(store_path.read_text(encoding="utf-8"))
    assert stored["cards"]["sales-delta-widget"]["signature"]["generic"]["metrics"] == [["Value", "10"]]

    # The figure moves, and the poll says what changed since the view.
    _write_manual_metric(booted, 14)
    for _poll in range(2):
        status, _headers, body = booted.request("GET", "/api/dashboard", auth)
        assert status == 200
        cards = json.loads(body)["plugins"]["cards"]
        blocks = _insight_blocks(cards[0])
        assert blocks and blocks[0]["kind"] == "delta"
        assert blocks[0]["text"].startswith(PREFIX)
        assert "changed" in blocks[0]["text"]
    # Both polls were pure reads: the watermark still holds the old value.
    stored = json.loads(store_path.read_text(encoding="utf-8"))
    assert stored["cards"]["sales-delta-widget"]["signature"]["generic"]["metrics"] == [["Value", "10"]]

    # The user views the dashboard again, and the line clears.
    status, _headers, body = booted.post_json("/api/dashboard/view", {}, auth)
    assert status == 200
    stored = json.loads(store_path.read_text(encoding="utf-8"))
    assert stored["cards"]["sales-delta-widget"]["signature"]["generic"]["metrics"] == [["Value", "14"]]
    status, _headers, body = booted.request("GET", "/api/dashboard", auth)
    cards = json.loads(body)["plugins"]["cards"]
    assert all(block["kind"] != "delta" for block in _insight_blocks(cards[0]))
