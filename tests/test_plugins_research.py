"""Research family: the one surviving research plugin, competitor-watch.

Spec 015 retires the rest of the family, so competitor-watch is the only
in-box research plugin. It is still declarative: a v2 manifest, a ui-schema
of known element kinds, a sample that binds every element, and a README.
Its http-get source is the only network source and the host stays an
explicit consent grant, not a base permission.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.plugins.render import ELEMENT_KINDS, render_sample  # noqa: E402
from agentdesk.validator import validate_plugin  # noqa: E402

PLUGINS = ROOT / "registry" / "plugins"
FAMILY = ("competitor-watch",)
CHECKED_AT = "2026-11-15T09:00:00"

# The one binding field each element kind reads its data from.
PRIMARY_BINDING = {
    "metric": "binding",
    "text": "binding",
    "delta": "binding",
    "progress": "binding",
    "status": "binding",
    "list": "rowsBinding",
    "table": "rowsBinding",
    "sparkline": "pointsBinding",
    "timeline": "itemsBinding",
    "checklist": "itemsBinding",
}


def plugin_dir(plugin_id: str) -> Path:
    directory = PLUGINS / plugin_id
    assert directory.is_dir(), f"missing plugin directory: {plugin_id}"
    return directory


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def manifest_of(plugin_id: str) -> dict:
    return load_json(plugin_dir(plugin_id) / "manifest.json")


def ui_schema_of(plugin_id: str) -> dict:
    render_file = manifest_of(plugin_id)["contributes"]["widgets"][0]["render"]["file"]
    return load_json(plugin_dir(plugin_id) / render_file)


def sample_of(plugin_id: str) -> dict:
    return load_json(plugin_dir(plugin_id) / manifest_of(plugin_id)["sample"])


def data_source_of(plugin_id: str) -> dict:
    return manifest_of(plugin_id)["contributes"]["widgets"][0]["dataSource"]


@pytest.mark.parametrize("plugin_id", FAMILY)
def test_plugin_passes_the_real_validator(plugin_id):
    verdict = validate_plugin(plugin_dir(plugin_id))
    assert verdict.ok, [
        f"{failure.code}: {failure.message}" for failure in verdict.failures
    ]


@pytest.mark.parametrize("plugin_id", FAMILY)
def test_manifest_is_v2_with_the_discovery_fields(plugin_id):
    manifest = manifest_of(plugin_id)
    assert manifest["schemaVersion"] == 2
    assert manifest["id"] == plugin_id
    assert manifest["class"] == "declarative"
    assert manifest["publisher"] == "agent-desk"
    assert manifest["category"] == "research"
    assert manifest["sample"] == "sample.json"
    assert len(manifest["highlights"]) == 3
    assert 0 < len(manifest["tags"]) <= 8
    assert manifest["permissions"]["shell"] == "none"


@pytest.mark.parametrize("plugin_id", FAMILY)
def test_every_element_kind_is_one_of_the_ten(plugin_id):
    kinds = [element["type"] for element in ui_schema_of(plugin_id)["elements"]]
    assert kinds, "a widget must declare at least one element"
    assert set(kinds) <= set(ELEMENT_KINDS)


@pytest.mark.parametrize("plugin_id", FAMILY)
def test_every_slot_has_a_binding_in_the_sample(plugin_id):
    bindings = sample_of(plugin_id)["bindings"]
    assert isinstance(bindings, dict) and bindings
    missing = []
    for element in ui_schema_of(plugin_id)["elements"]:
        key = PRIMARY_BINDING[element["type"]]
        name = element.get(key)
        if not name or name not in bindings:
            missing.append((element["type"], key, name))
    assert missing == []


@pytest.mark.parametrize("plugin_id", FAMILY)
def test_sample_renders_fresh_with_no_blank_element(plugin_id):
    sample = sample_of(plugin_id)
    assert sample["state"] == "ok"
    assert sample["checkedAt"] == CHECKED_AT

    rendered = render_sample(plugin_dir(plugin_id))

    assert rendered["status"] == "fresh"
    assert rendered["checked_at"] == CHECKED_AT
    assert rendered["elements"], "the sample must bind every element"
    blank = [element for element in rendered["elements"] if element["state"] != "ok"]
    assert blank == [], blank


@pytest.mark.parametrize("plugin_id", FAMILY)
def test_every_plugin_ships_a_readme(plugin_id):
    readme = (plugin_dir(plugin_id) / "README.md").read_text(encoding="utf-8")
    assert "## What it answers" in readme
    assert "## What it reads" in readme
    assert "## What it never does" in readme
    assert len(readme.split()) >= 40


def test_competitor_watch_is_the_only_network_plugin():
    manifest = manifest_of("competitor-watch")
    source = data_source_of("competitor-watch")
    assert source["type"] == "http-get"
    assert source["url"] == "https://example.com/pricing"
    assert source["host"] == "example.com"

    # Base permissions stay empty; the host is a consent grant.
    assert manifest["permissions"]["network"] == {"allow": []}
    assert manifest["permissions"]["filesystem"]["read"] == []
    assert manifest["optionalPermissions"]["network"]["allow"] == ["example.com"]
    assert manifest["optionalPermissions"]["network"]["userPrompt"].strip()

    # No other shipped plugin asks for the network, even optionally.
    for other in sorted(PLUGINS.iterdir()):
        if other.name == "competitor-watch" or not other.is_dir():
            continue
        other_manifest = load_json(other / "manifest.json")
        assert other_manifest["permissions"]["network"] == {"allow": []}, other.name
        assert other_manifest.get("optionalPermissions", {}).get("network") is None, other.name

    readme = (plugin_dir("competitor-watch") / "README.md").read_text(encoding="utf-8")
    text = " ".join(readme.lower().split())
    assert "excluded from every pack" in text
    assert "admin network approval" in text
