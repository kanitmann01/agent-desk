"""Operations family: four declarative desk-state cards.

Plugin health, update radar, audit digest, and compliance posture all
answer an operations question from the host's desk state. The family test
discovers every plugin whose manifest declares category "operations", runs
the real validator over it, and renders the packaged sample through the
host renderer to prove every slot is bound and nothing renders blank.
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
from agentdesk.validator.core import validate_plugin  # noqa: E402
from agentdesk.validator.schema import CATEGORIES, ICONS  # noqa: E402

PLUGINS_DIR = ROOT / "registry" / "plugins"
FAMILY = "operations"
EXPECTED_IDS = {
    "plugin-health",
    "update-radar",
    "audit-digest",
    "compliance-posture",
}
EXPECTED_ELEMENTS = {
    "plugin-health": ("status", "list", "metric"),
    "update-radar": ("list", "delta"),
    "audit-digest": ("metric", "table", "text"),
    "compliance-posture": ("status", "checklist", "text"),
}
DESK_STATE_SELECTORS = ("runtime", "audit", "policy")

# Slot keys per element kind: the binding names a shipped sample must supply.
SLOT_KEYS = {
    "metric": ("binding",),
    "text": ("binding",),
    "delta": ("binding", "directionBinding"),
    "progress": ("binding", "targetBinding", "toneBinding"),
    "list": ("rowsBinding",),
    "table": ("rowsBinding",),
    "sparkline": ("pointsBinding",),
    "status": ("binding", "toneBinding"),
    "timeline": ("itemsBinding",),
    "checklist": ("itemsBinding",),
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _manifest(plugin_dir: Path) -> dict:
    return _json(plugin_dir / "manifest.json")


def _family_plugins() -> list[Path]:
    found = []
    for manifest_path in sorted(PLUGINS_DIR.glob("*/manifest.json")):
        if _manifest(manifest_path.parent).get("category") == FAMILY:
            found.append(manifest_path.parent)
    return found


PLUGINS = _family_plugins()

plugin_dir = pytest.mark.parametrize(
    "plugin_dir", PLUGINS, ids=[plugin.name for plugin in PLUGINS]
)


def _elements(plugin_dir: Path) -> list[dict]:
    schema = _json(plugin_dir / "widget.ui.json")
    return [element for element in schema["elements"] if isinstance(element, dict)]


def _slot_names(plugin_dir: Path) -> set[str]:
    names = set()
    for element in _elements(plugin_dir):
        for key in SLOT_KEYS[element["type"]]:
            name = element.get(key)
            if isinstance(name, str) and name:
                names.add(name)
    return names


def test_family_is_the_four_operations_plugins():
    assert {plugin.name for plugin in PLUGINS} == EXPECTED_IDS
    for plugin in PLUGINS:
        assert plugin.is_dir()
        assert (plugin / "README.md").is_file(), plugin.name
        assert (plugin / "sample.json").is_file(), plugin.name


@plugin_dir
def test_manifest_is_a_v2_desk_state_card(plugin_dir):
    manifest = _manifest(plugin_dir)
    assert manifest["schemaVersion"] == 2
    assert manifest["category"] == FAMILY
    assert manifest["category"] in CATEGORIES
    assert manifest["icon"] in ICONS
    assert manifest["class"] == "declarative"
    assert manifest["permissions"]["shell"] == "none"
    assert manifest["permissions"]["network"] == {"allow": []}

    widgets = manifest["contributes"]["widgets"]
    assert len(widgets) == 1, plugin_dir.name
    widget = widgets[0]
    assert widget["id"] == manifest["id"]
    assert widget["dataSource"]["type"] == "desk-state"
    assert widget["dataSource"]["selector"] in DESK_STATE_SELECTORS
    assert widget["render"] == {"type": "ui-schema", "file": "widget.ui.json"}
    assert manifest["sample"] == "sample.json"


@plugin_dir
def test_validator_accepts_the_plugin(plugin_dir):
    verdict = validate_plugin(plugin_dir)
    assert verdict.ok, verdict.as_dict()


@plugin_dir
def test_element_kinds_are_the_ten_contract_kinds(plugin_dir):
    elements = _elements(plugin_dir)
    assert elements, plugin_dir.name
    assert all(element["type"] in ELEMENT_KINDS for element in elements)
    assert tuple(element["type"] for element in elements) == EXPECTED_ELEMENTS[plugin_dir.name]


@plugin_dir
def test_sample_binds_every_slot_and_nothing_else(plugin_dir):
    sample = _json(plugin_dir / "sample.json")
    bindings = sample["bindings"]
    assert sample["state"] == "ok"
    assert isinstance(sample["checkedAt"], str) and "T" in sample["checkedAt"]
    # Every declared slot has a value, and the sample invents no binding the
    # widget never reads.
    assert set(bindings) == _slot_names(plugin_dir)
    for name, value in bindings.items():
        assert value is not None, name


@plugin_dir
def test_render_sample_is_fresh_with_no_blank_element(plugin_dir):
    out = render_sample(plugin_dir)
    assert out["status"] == "fresh"
    assert out["cause"] == ""
    assert out["checked_at"]
    elements = _elements(plugin_dir)
    assert [rendered["kind"] for rendered in out["elements"]] == [
        element["type"] for element in elements
    ]
    assert all(
        rendered["state"] == "ok" for rendered in out["elements"]
    ), out["elements"]
