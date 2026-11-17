"""Command family: two aggregate command cards plus the pack catalog.

Morning Brief and Weekly Review declare a host aggregate over installed
cards. They reuse the real aggregate source, so this test also proves the
command cards fail closed: a missing dependency is named, a blank member
blanks the whole card, and only numeric contributors are counted. The pack
catalog is checked against the same plugin registry.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.plugins.render import ELEMENT_KINDS, render_sample  # noqa: E402
from agentdesk.plugins.sources import SourceContext, read_source  # noqa: E402
from agentdesk.validator.core import validate_plugin  # noqa: E402
from agentdesk.validator.schema import (  # noqa: E402
    ICONS,
    MAX_DESCRIPTION_CHARS,
    MAX_HIGHLIGHT_CHARS,
    MAX_SUMMARY_CHARS,
)

PLUGINS_DIR = ROOT / "registry" / "plugins"
PACKS_FILE = ROOT / "registry" / "packs.json"
FAMILY = "command"
EXPECTED_IDS = {"morning-brief", "weekly-review"}
EXPECTED_ELEMENTS = {
    "morning-brief": ("metric", "list"),
    "weekly-review": ("metric", "list"),
}
SLOT_KEYS = {
    "metric": ("binding",),
    "text": ("binding",),
    "list": ("rowsBinding",),
    "table": ("rowsBinding",),
    "sparkline": ("pointsBinding",),
    "status": ("binding", "toneBinding"),
    "checklist": ("itemsBinding",),
    "timeline": ("itemsBinding",),
    "progress": ("binding", "targetBinding"),
    "delta": ("binding", "directionBinding"),
}
EXPECTED_PACKS = {
    "manager": {
        "calendar-today",
        "week-load",
        "meeting-prep",
        "follow-up-watch",
        "sales-delta-widget",
        "outlook-digest",
        "research-brief",
        "morning-brief",
    },
    "cfo": {
        "revenue-vs-target",
        "ar-aging",
        "budget-burn",
        "kpi-scorecard",
        "reconciliation-watch",
        "renewal-radar",
        "audit-digest",
        "weekly-review",
    },
    "ops": {
        "follow-up-watch",
        "waiting-on-you",
        "source-ledger",
        "notes-actions",
        "plugin-health",
        "update-radar",
        "compliance-posture",
        "weekly-review",
    },
}


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest(plugin_dir):
    return _json(plugin_dir / "manifest.json")


def _command_plugins():
    found = []
    for manifest_path in sorted(PLUGINS_DIR.glob("*/manifest.json")):
        if _json(manifest_path).get("category") == FAMILY:
            found.append(manifest_path.parent)
    return found


COMMAND_PLUGINS = _command_plugins()


def _source(plugin_dir):
    return _manifest(plugin_dir)["contributes"]["widgets"][0]["dataSource"]


def _context(tmp_path, plugin_id, dependencies=None):
    return SourceContext(
        plugin_id=plugin_id,
        workspace_dir=tmp_path,
        data_dir=tmp_path,
        now=datetime(2026, 11, 15, 9, 0, 0),
        dependencies=dependencies or {},
    )


def _packs():
    return _json(PACKS_FILE)["packs"]


@pytest.mark.parametrize("plugin_dir", COMMAND_PLUGINS, ids=lambda p: p.name)
def test_plugin_is_expanded_and_documented(plugin_dir):
    assert {"manifest.json", "widget.ui.json", "sample.json", "README.md"} <= {
        path.name for path in plugin_dir.iterdir()
    }


def test_command_family_is_the_two_expected_plugins():
    assert {plugin_dir.name for plugin_dir in COMMAND_PLUGINS} == EXPECTED_IDS


@pytest.mark.parametrize("plugin_dir", COMMAND_PLUGINS, ids=lambda p: p.name)
def test_manifest_contract(plugin_dir):
    manifest = _manifest(plugin_dir)
    assert manifest["schemaVersion"] == 2
    assert manifest["category"] == FAMILY
    assert manifest["class"] == "declarative"
    assert manifest["publisher"] == "agent-desk"
    assert manifest["license"] == "MIT"
    assert manifest["icon"] in ICONS
    assert manifest["icon"] in {"checklist", "clock"}
    assert len(manifest["tags"]) == 3
    assert len(set(manifest["tags"])) == 3
    assert len(manifest["summary"]) <= MAX_SUMMARY_CHARS
    assert len(manifest["description"]) <= MAX_DESCRIPTION_CHARS
    assert len(manifest["highlights"]) == 3
    assert all(
        len(item) <= MAX_HIGHLIGHT_CHARS for item in manifest["highlights"]
    )
    assert manifest["sample"] == "sample.json"
    assert (plugin_dir / "sample.json").is_file()
    source = manifest["contributes"]["widgets"][0]["dataSource"]
    assert source["type"] == "aggregate"
    assert source["aggregate"] == "count"
    assert manifest["requires"] == source["over"]
    assert len(manifest["requires"]) == 4


@pytest.mark.parametrize("plugin_dir", COMMAND_PLUGINS, ids=lambda p: p.name)
def test_validator_accepts_the_command_plugin(plugin_dir):
    verdict = validate_plugin(plugin_dir)
    assert verdict.ok, verdict.as_dict()


@pytest.mark.parametrize("plugin_dir", COMMAND_PLUGINS, ids=lambda p: p.name)
def test_element_kinds_match_the_declared_card(plugin_dir):
    ui = _json(plugin_dir / "widget.ui.json")
    kinds = tuple(element["type"] for element in ui["elements"])
    assert kinds == EXPECTED_ELEMENTS[plugin_dir.name]
    assert set(kinds) <= set(ELEMENT_KINDS)


@pytest.mark.parametrize("plugin_dir", COMMAND_PLUGINS, ids=lambda p: p.name)
def test_sample_binds_every_slot_and_nothing_else(plugin_dir):
    ui = _json(plugin_dir / "widget.ui.json")
    sample = _json(plugin_dir / "sample.json")
    slots = set()
    for element in ui["elements"]:
        for key in SLOT_KEYS[element["type"]]:
            if key in element:
                slots.add(element[key])
    assert set(sample["bindings"]) == slots
    assert sample["state"] == "ok"
    assert "T" in sample["checkedAt"]
    assert all(value is not None for value in sample["bindings"].values())


@pytest.mark.parametrize("plugin_dir", COMMAND_PLUGINS, ids=lambda p: p.name)
def test_render_sample_is_fresh_with_no_blank_element(plugin_dir):
    rendered = render_sample(plugin_dir)
    assert rendered["status"] == "fresh"
    assert rendered["cause"] == ""
    assert rendered["checked_at"]
    kinds = tuple(element["kind"] for element in rendered["elements"])
    assert kinds == EXPECTED_ELEMENTS[plugin_dir.name]
    assert {element["state"] for element in rendered["elements"]} == {"ok"}


@pytest.mark.parametrize("plugin_id", sorted(EXPECTED_IDS))
def test_missing_dependency_is_named(tmp_path, plugin_id):
    manifest = _manifest(PLUGINS_DIR / plugin_id)
    result = read_source(
        _source(PLUGINS_DIR / plugin_id),
        _context(tmp_path, plugin_id),
    )
    assert result.state == "blank"
    assert result.reason == "missing-dependency"
    assert manifest["requires"][0] in result.human
    assert result.bindings == {}


def test_blank_member_blanks_the_whole_aggregate(tmp_path):
    source = _source(PLUGINS_DIR / "morning-brief")
    dependencies = {
        "sales-delta-widget": {
            "contributes": {
                "widgets": [
                    {
                        "dataSource": {
                            "type": "csv-watch",
                            "file": "${workspace}/missing.csv",
                            "keyColumn": "Owner",
                            "valueColumn": "Due",
                        }
                    }
                ]
            }
        },
    }
    result = read_source(
        source,
        _context(tmp_path, "morning-brief", dependencies),
    )
    assert result.state == "blank"
    assert result.reason == "blank-dependency"
    assert "sales-delta-widget" in result.human
    assert result.detail["dependency"] == "sales-delta-widget"
    assert result.bindings == {}


@pytest.mark.parametrize("plugin_id", sorted(EXPECTED_IDS))
def test_count_counts_numeric_contributors(tmp_path, plugin_id):
    manifest = _manifest(PLUGINS_DIR / plugin_id)
    source = _source(PLUGINS_DIR / plugin_id)
    dependencies = {}
    for dep_id in manifest["requires"]:
        path = tmp_path / (dep_id + ".csv")
        path.write_text("Owner,Due\nA,1\nB,2\n", encoding="utf-8")
        dependencies[dep_id] = {
            "contributes": {
                "widgets": [
                    {
                        "dataSource": {
                            "type": "csv-watch",
                            "file": "${workspace}/" + path.name,
                            "keyColumn": "Owner",
                            "valueColumn": "Due",
                            "aggregate": "count",
                        }
                    }
                ]
            }
        }
    result = read_source(
        source,
        _context(tmp_path, plugin_id, dependencies),
    )
    assert result.state == "ok"
    assert result.bindings["value"] == 4
    assert result.bindings["count"] == 4
    assert [row["primary"] for row in result.bindings["rows"]] == manifest["requires"]
    assert all(row["secondary"] == "2" for row in result.bindings["rows"])
    assert result.detail == {"mode": "count", "over": manifest["requires"]}


def test_packs_file_parses_with_three_packs():
    data = _json(PACKS_FILE)
    assert data["schemaVersion"] == 1
    assert [pack["id"] for pack in data["packs"]] == ["manager", "cfo", "ops"]


@pytest.mark.parametrize("pack_id", sorted(EXPECTED_PACKS))
def test_pack_member_sets_are_exact(pack_id):
    pack = next(pack for pack in _packs() if pack["id"] == pack_id)
    assert set(pack["plugins"]) == EXPECTED_PACKS[pack_id]
    assert len(pack["plugins"]) == len(set(pack["plugins"])) == 8
    assert isinstance(pack.get("audience"), str) and pack["audience"]
    assert isinstance(pack.get("summary"), str) and pack["summary"]
    assert pack.get("icon") in ICONS
    assert pack.get("sampleData") is False
    assert pack.get("firstRun") is True


def test_every_pack_member_is_installed():
    for pack in _packs():
        for plugin_id in pack["plugins"]:
            manifest_path = PLUGINS_DIR / plugin_id / "manifest.json"
            assert manifest_path.is_file(), (pack["id"], plugin_id)
            assert _json(manifest_path)["id"] == plugin_id


def test_competitor_watch_is_only_an_exclusion():
    packs = _packs()
    manager = next(pack for pack in packs if pack["id"] == "manager")
    assert manager["excluded"] == [
        {"id": "competitor-watch", "reason": "network plugin, excluded from packs"},
    ]
    assert "competitor-watch" not in manager["plugins"]
    for pack in packs:
        assert "competitor-watch" not in pack["plugins"]
    assert all(
        not pack["excluded"] for pack in packs if pack["id"] != "manager"
    )


def test_excel_report_is_reference_and_unpacked():
    manifest = _manifest(PLUGINS_DIR / "excel-report")
    assert manifest["category"] == "reference"
    assert manifest["id"] == "excel-report"
    assert manifest["version"] == "0.1.0"
    assert manifest["config"]["kinds"] == ["workbook"]
    assert "file" not in manifest["contributes"]["widgets"][0]["dataSource"]
    assert validate_plugin(PLUGINS_DIR / "excel-report").ok
    packed = {plugin_id for pack in _packs() for plugin_id in pack["plugins"]}
    assert "excel-report" not in packed
