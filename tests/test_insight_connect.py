"""The connect step (spec 023, ticket 023-1): the pure matcher and the
line it puts on the workbook tracker card.

Unit tests pin the matcher's rules (longest whole word wins, one entry
per entity, the cap, every refusal) on hand-built indexes. The product
tests drive the real app through the harness: on the sample desk the
tracker card's payload carries the line; on a fresh desk with nothing
saved no card carries one.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import server_harness
from agentdesk.insight import insight_connect
from agentdesk.insight import reading as insight_reading
from agentdesk.insight import workbook
from agentdesk.insight.context import build_context
from agentdesk.insight.types import InsightContext
from agentdesk.keys.secrets import KeychainSecrets, MemoryKeychain

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _Entity:
    """Only what build_index reads off the store's entity summaries."""

    id: int
    canonical_name: str
    aliases: tuple = ()
    type: str = "org"
    fact_count: int = 0


def _index(*entities, agenda=None, now=1_000_000.0):
    return insight_connect.build_index(list(entities), agenda, now)


def test_longest_whole_word_match_wins_and_cap_holds():
    index = _index(
        _Entity(1, "Halvorsen Freight", fact_count=3),
        _Entity(2, "Marlow & Finch", fact_count=1),
        _Entity(3, "Acropolis Logistics", ("Acropolis Group",), fact_count=2),
        _Entity(4, "Bergstrom Holdings", fact_count=5),
    )
    rows = [
        "Halvorsen Freight renewal",
        "Marlow & Finch / Acropolis Group / Bergstrom Holdings",
    ]
    line, notes = insight_connect.connect_line(rows, index)
    assert "Halvorsen Freight" in line and "Marlow & Finch" in line
    assert "Acropolis Logistics" in line  # the alias names the entity once
    assert "Bergstrom" not in line        # the cap keeps three per card
    assert notes == 3 + 1 + 2


def test_a_name_and_its_alias_count_once():
    index = _index(_Entity(1, "Acropolis Logistics", ("Acropolis Group",), fact_count=2))
    line, notes = insight_connect.connect_line(
        ["Acropolis Logistics (Acropolis Group)"], index)
    assert line.count("Acropolis") == 1
    assert notes == 2


def test_refusals():
    concept = _Entity(1, "Renewals", type="concept", fact_count=4)
    short = _Entity(2, "Acme", fact_count=2)
    alias_single = _Entity(3, "Northwind Logistics", ("NW",), fact_count=1)
    index = _index(concept, short, alias_single)
    line, notes = insight_connect.connect_line(
        ["Renewals with Acme and NW Freight"], index)
    assert line == "" and notes == 0


def test_empty_memory_draws_no_line():
    assert insight_connect.connect_line(["Halvorsen Freight"], ()) == ("", 0)
    assert insight_connect.connect_line([], ()) == ("", 0)


def test_a_card_with_no_rows_carries_no_line():
    index = _index(_Entity(1, "Halvorsen Freight", fact_count=3))
    found = _reading_for(
        {"tracker": {"table": {"headers": ["Account", "Amount"], "rows": []},
                     "labelColumn": "Account"}},
        index,
    )
    text = " ".join(block["text"] for block in insight_reading.blocks(found))
    assert "Also in your desk" not in text


def test_the_longer_name_wins_a_span_it_shares_with_a_shorter_one():
    """Memory holds both names; a row naming the longer one is one
    connection, to the longer entity, and the shorter is not counted."""
    index = _index(
        _Entity(1, "Halvorsen Freight", fact_count=3),
        _Entity(2, "Halvorsen Freight Logistics", fact_count=5),
    )
    row = "Halvorsen Freight Logistics renewal"
    named = insight_connect.match_names(row, index)
    assert [entry.entity_id for entry in named] == [2]
    line, notes = insight_connect.connect_line([row], index)
    assert line.startswith("Also in your desk: Halvorsen Freight Logistics, 5 things")
    assert "3 things" not in line
    assert line.count("Halvorsen Freight") == 1
    assert notes == 5


def test_the_agenda_clause_reaches_every_entity_its_title_names():
    agenda = {"title": "Renewal call: Halvorsen Freight and Kestrel Foods",
              "time": "2026-11-23T14:38:00"}
    index = _index(
        _Entity(1, "Halvorsen Freight", fact_count=3),
        _Entity(2, "Kestrel Foods", fact_count=2),
        agenda=agenda,
        now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc).timestamp(),
    )
    assert all(entry.event_clause.endswith("14:38") for entry in index)
    line, _notes = insight_connect.connect_line(
        ["Halvorsen Freight renewal", "Kestrel Foods pilot"], index)
    assert line.count("at 14:38") == 2


def test_the_agenda_dates_the_entity_it_names():
    agenda = {"title": "Renewal call: Halvorsen Freight", "time": "2026-11-23T14:38:00"}
    index = _index(_Entity(1, "Halvorsen Freight", fact_count=3), agenda=agenda,
                   now=datetime(2026, 11, 23, 12, 0,
                                tzinfo=timezone.utc).timestamp())
    named = insight_connect.match_names("Halvorsen Freight renewal", index)
    assert named and named[0].event_clause.endswith("14:38")
    line, _notes = insight_connect.connect_line(["Halvorsen Freight"], index)
    assert "you told the desk" in line and "at 14:38" in line
    # The title keeps the casing it was stored with; matching lowercased
    # it only to find the entity.
    assert "Renewal call: Halvorsen Freight" in line
    assert "renewal call: halvorsen freight" not in line


def test_a_sealed_bank_yields_no_names_and_no_line():
    """A sealed bank contributes nothing: no desk names, no line, and the
    documented refusal note. This fake would answer with an entity if the
    is_sealed guard in context._entities were dropped, so the guard is
    what the test pins."""
    sealed = SimpleNamespace(
        is_sealed=True,
        entities=lambda: [_Entity(1, "Halvorsen Freight", fact_count=3)],
    )
    context = build_context(SimpleNamespace(memory=sealed, calendar=None), {})
    assert context.desk_names == ()
    assert "locked" in context.memory_note
    assert insight_connect.connect_line(["Halvorsen Freight"], context.desk_names) == ("", 0)


def _tracker_payload(label_column=None):
    """A tracker table the relations detectors accept: a date column, a
    rising amount (the trend), and an account column for the labels."""
    rows = []
    for index in range(12):
        account = "Halvorsen Freight" if index % 3 == 0 else "Kestrel Foods"
        rows.append([account, f"2026-{index + 1:02d}-01", 900 + index * 40])
    headers = ["Account", "When", "Amount"]
    return {
        "tracker": {"table": {"headers": headers, "rows": rows},
                    "labelColumn": label_column or "Account"},
    }


def _reading_for(payload, desk_names):
    """One workbook family run, with the context the desk would hold."""
    context = InsightContext(preferences={}, now=1_000_000.0, desk_names=desk_names)
    return workbook.derive({"pluginId": "excel-report"}, dict(payload), context)


def test_the_line_is_a_note_block_never_an_element():
    index = _index(_Entity(1, "Halvorsen Freight", fact_count=3))
    found = _reading_for(_tracker_payload(), index)
    text = " ".join(block["text"] for block in insight_reading.blocks(found))
    assert "Also in your desk" in text
    assert not any("Also in your desk" in str(element.get("text", ""))
                   for element in found.elements)
    assert found.inputs == ("rows", "memory", "calendar") and found.memory_notes == 3
    # The receipt names its inputs, so the card's Used line stays honest.
    assert "memory (3 notes)" in text


def test_no_match_leaves_the_reading_exactly_as_it_was():
    payload = _tracker_payload()
    plain_payload = {
        "tracker": {"table": dict(payload["tracker"]["table"],
                                  rows=[[f"House {index} {cell}" if index == 0 else cell
                                         for index, cell in enumerate(row)]
                                        for row in payload["tracker"]["table"]["rows"]]),
                    "labelColumn": "Account"},
    }
    plain = _reading_for(plain_payload, ())
    assert plain.inputs == ("rows",) and plain.memory_notes == 0
    matched = _reading_for(
        payload, _index(_Entity(1, "Halvorsen Freight", fact_count=3)))
    assert matched.inputs == ("rows", "memory", "calendar")


# -- through the product ---------------------------------------------------------


def _instant_check(base_url, api_key, extra_headers=None, timeout=None):
    """A save-time prober that answers instantly and hermetically."""
    from agentdesk.keys import health
    return health.ProbeResult(health.OUTCOME_OK, "", ["hermetic-model"])


def _desk(**kwargs):
    """A booted desk with an in-memory keychain and nothing else saved."""
    kwargs.setdefault("keychain", KeychainSecrets(MemoryKeychain()))
    kwargs.setdefault("connection_check", _instant_check)
    return server_harness.Booted(**kwargs)


def _tracker_card(booted, auth):
    """The excel-report card's insight payload from the dashboard, or None."""
    status, _headers, body = booted.request("GET", "/api/dashboard", auth)
    assert status == 200
    dashboard = json.loads(body)
    for card in ((dashboard.get("plugins") or {}).get("cards") or []):
        if card.get("pluginId") == "excel-report":
            return (card.get("payload") or {}).get("insight") or {}
    return None


def test_the_sample_desk_holds_nameable_things(tmp_path, monkeypatch):
    """Through the real server: with the labelled sample set on and the
    sample workbook open in the Workbook tracker, the card's own insight
    payload carries the line, naming an entity the desk holds; the
    sample desk's concept is still refused."""
    import time as time_module
    from agentdesk.plugins.runtime import PluginRuntime
    from agentdesk.server import demo_data

    data_dir = tmp_path / "desk-data"
    monkeypatch.setenv("AGENTDESK_DATA", str(data_dir))
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "plugin-data",
        workspace_dir=data_dir,
    )
    runtime.install(ROOT / "registry" / "plugins" / "excel-report", source="dir")
    booted = _desk(
        plugins=runtime,
        pick_workbook=lambda: str(demo_data.sample_workbook_path(data_dir)),
    )
    try:
        auth = booted.exchange()
        status, _headers, body = booted.post_json(
            "/settings/toggle", {"key": "sample_data"}, auth)
        assert status == 200, body
        status, _headers, body = booted.post_json(
            "/api/plugins/excel-report/instances/main/pick",
            {"name": "Workbook tracker"}, auth)
        assert status == 200, body
        status, _headers, body = booted.post_json(
            "/api/plugins/excel-report/instances/main/confirm",
            {"tracking": {"labelColumn": "Deal", "valueColumn": "Amount",
                          "aggregate": "sum"}}, auth)
        assert status == 200, body

        deadline = time_module.monotonic() + 10
        names = ()
        while time_module.monotonic() < deadline:
            names = build_context(booted.server, {}, now=time_module.time()).desk_names
            if any("Halvorsen Freight" in entry.names for entry in names):
                break
            time_module.sleep(0.2)
        named = {name for entry in names for name in entry.names}
        assert "Halvorsen Freight" in named and "Kestrel Foods" in named
        assert not any("Q4 pipeline review" in named for _entry in names)
        counts = {entry.names[0]: entry.fact_count for entry in names}
        assert counts.get("Halvorsen Freight") == 3

        insight = _tracker_card(booted, auth)
        assert insight is not None
        text = " ".join(block["text"] for block in insight.get("blocks") or [])
        assert "Also in your desk" in text
        assert "Halvorsen Freight" in text
        assert "memory (6 notes)" in text
    finally:
        booted.close()


def test_a_fresh_desk_holds_no_names():
    booted = _desk()
    try:
        auth = booted.exchange()
        from agentdesk.insight.context import build_context
        import time as time_module
        context = build_context(booted.server, {}, now=time_module.time())
        assert context.desk_names == ()
    finally:
        booted.close()
