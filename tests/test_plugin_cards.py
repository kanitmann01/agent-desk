"""The card factory and its serializer: one owner per wire shape (#177).

The widget card dict used to be assembled by four hand literals, and one
of them once missed pluginId (#165): the invariant was hoped for at each
site and enforced nowhere. These tests pin the factory's contract (the
plugin identity is mandatory, every emitted shape carries it) and the
one serializer that turns a card into the dashboard API's camelCase
dict, so contract drift fails here instead of shipping silently.
"""

from pathlib import Path

import pytest

from agentdesk.plugins.cards import (
    CardError,
    attention_card,
    card_to_api,
    setup_card,
    tracker_card,
    widget_card,
)
from excel_fixtures import make_xlsx
from plugins_fixtures import valid_zip

NOW = "2026-11-11T16:00:00"
ROOT = Path(__file__).resolve().parents[1]

# Every public card shape, as a callable over one plugin identity.
SHAPES = {
    "setup": lambda plugin_id, instance_id: setup_card(
        plugin_id, instance_id, title="T", version="1.0.0",
        pilot=True, step="source"),
    "tracker": lambda plugin_id, instance_id: tracker_card(
        plugin_id, instance_id, title="T", version="1.0.0",
        pilot=True, reading={}),
    "attention": lambda plugin_id, instance_id: attention_card(
        plugin_id, instance_id, card_id="c", title="T", version="1.0.0",
        pilot=True, cause="why"),
    "widget": lambda plugin_id, instance_id: widget_card(
        plugin_id, instance_id, title="T", version="1.0.0", pilot=True,
        state="enabled", data={}, payload=None, manifest={}),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_card_shape_refuses_to_build_without_its_plugin_identity(shape):
    """A card that cannot receive its reading is unrepresentable (#165).

    The reading and press seams key off pluginId and instanceId, so a
    card missing either would silently never be coupled. The factory
    refuses it by name, whichever shape was asked for.
    """
    with pytest.raises(CardError) as refused:
        SHAPES[shape]("", "main")
    assert refused.value.code == "card:missing-identity"
    with pytest.raises(CardError) as refused:
        SHAPES[shape]("sales-delta-widget", "")
    assert refused.value.code == "card:missing-identity"


def test_every_card_the_runtime_emits_names_its_plugin(tmp_path):
    """All four shapes widget_cards() emits carry the identity.

    Setup (no instance yet), the confirmed tracker, the instance whose
    granted file disappeared, the live single-instance widget, and the
    tampered install's attention card: each names its plugin and
    instance, because each was built by the factory.
    """
    from agentdesk.plugins.config import InstanceStore
    from agentdesk.plugins.runtime import PluginRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(make_xlsx([["Region", "Booked"], ["East", 10], ["West", 5]]))
    dirs = dict(plugins_dir=tmp_path / "plugins", data_dir=tmp_path / "data",
                workspace_dir=workspace, now=NOW)
    runtime = PluginRuntime(**dirs)
    runtime.install(ROOT / "registry" / "plugins" / "excel-report", source="dir")

    # The setup shape: a config-backed plugin with no instance yet.
    setup = next(c for c in runtime.widget_cards()
                 if c["pluginId"] == "excel-report")
    assert setup["freshness"] == "setup"
    assert setup["instanceId"] == "main"

    # The tracker shape: one confirmed instance reading its granted file.
    store = InstanceStore(runtime.data_dir, workspace)
    store.create("excel-report", "pipeline", "Pipeline")
    store.stage_file("excel-report", "pipeline", book)
    store.confirm("excel-report", "pipeline",
                  {"labelColumn": "Region", "valueColumn": "Booked",
                   "aggregate": "sum"})
    tracker = next(c for c in runtime.widget_cards()
                   if c["instanceId"] == "pipeline")
    assert tracker["freshness"] == "fresh"
    assert tracker["pluginId"] == "excel-report"

    # The instance attention shape: the granted file is gone, the card
    # carries the reason instead of a stale value.
    book.unlink()
    gone = next(c for c in runtime.widget_cards()
                if c["instanceId"] == "pipeline")
    assert gone["freshness"] == "attention"
    assert gone["pluginId"] == "excel-report"
    assert gone["payload"] is None

    # The live widget shape: a single-instance plugin with a workbook.
    reports = workspace / "reports"
    reports.mkdir()
    (reports / "q4.xlsx").write_bytes(
        make_xlsx([["Region", "Sales"], ["North", 10]]))
    runtime.install(valid_zip(tmp_path / "plugin.zip"), source="zip")
    live = next(c for c in runtime.widget_cards()
                if c["pluginId"] == "sales-delta-widget")
    assert live["freshness"] == "fresh"
    assert live["instanceId"] == "main"

    # The tampered attention shape: a restarted runtime refuses the pin.
    version_dir = Path(
        runtime.record("sales-delta-widget")["versions"][0]["dir"])
    manifest_file = version_dir / "manifest.json"
    manifest_file.write_text(
        manifest_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    restarted = PluginRuntime(**dirs)
    cards = restarted.widget_cards()
    tampered = next(c for c in cards if c["pluginId"] == "sales-delta-widget")
    assert tampered["freshness"] == "attention"
    assert "installed files changed" in tampered["cause"]
    assert tampered["instanceId"] == "main"
    for card in cards:
        assert card["pluginId"], card
        assert card["instanceId"], card


def test_the_serializer_pins_the_dashboard_api_card_shape():
    """card_to_api is the dashboard payload's card, exactly as served.

    The camelCase field list, its order (the API JSON is byte-for-byte
    what it was), the manifest staying internal, and a layout rename
    overriding the title: all decided in this one place.
    """
    card = widget_card(
        "sales-delta-widget", "main", title="Sales 24h Delta",
        version="1.2.0", pilot=True, state="enabled",
        data={"status": "fresh", "cause": "", "checked_at": NOW},
        payload={"elements": [], "status": "fresh"},
        manifest={"id": "sales-delta-widget"},
    )
    assert card_to_api(card) == {
        "id": "sales-delta-widget",
        "title": "Sales 24h Delta",
        "version": "1.2.0",
        "pilot": True,
        "state": "enabled",
        "freshness": "fresh",
        "cause": "",
        "checkedAt": NOW,
        "pluginId": "sales-delta-widget",
        "instanceId": "main",
        "payload": {"elements": [], "status": "fresh"},
    }
    assert list(card_to_api(card)) == [
        "id", "title", "version", "pilot", "state", "freshness", "cause",
        "checkedAt", "pluginId", "instanceId", "payload",
    ]
    assert "manifest" not in card_to_api(card)
    assert card_to_api(card, "Renamed")["title"] == "Renamed"


def test_the_serializer_keeps_the_defaults_the_dashboard_served():
    """A card without the optional fields still serializes.

    The dashboard used per-field gets with empty-string defaults so a
    pre-factory card (the seam tests build minimal ones) could not crash
    the payload; the one serializer answers the same defaults.
    """
    assert card_to_api({
        "id": "p", "title": "T", "version": "", "pilot": False,
        "state": "enabled", "freshness": "setup", "cause": "",
    }) == {
        "id": "p", "title": "T", "version": "", "pilot": False,
        "state": "enabled", "freshness": "setup", "cause": "",
        "checkedAt": "", "pluginId": "", "instanceId": "",
        "payload": None,
    }
