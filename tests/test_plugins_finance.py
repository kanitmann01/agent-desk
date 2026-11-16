"""Finance family contract tests (T7).

Discovers every finance plugin under registry/plugins, validates each with
the real validator, renders its sample fixture through the host renderer,
and checks the ten-element contract. The sample must be complete: every
element binds its slot and none falls back to the blank state.
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

PLUGINS_DIR = ROOT / "registry" / "plugins"

EXPECTED_FINANCE_IDS = {
    "sales-delta-widget",
    "revenue-vs-target",
    "ar-aging",
    "budget-burn",
    "kpi-scorecard",
    "reconciliation-watch",
}

SLOT_KEYS = (
    "binding",
    "directionBinding",
    "rowsBinding",
    "pointsBinding",
    "itemsBinding",
    "targetBinding",
    "toneBinding",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _finance_plugins() -> list:
    """(dir, manifest) for every registry plugin with category finance."""
    plugins = []
    for path in sorted(PLUGINS_DIR.iterdir()):
        manifest_path = path / "manifest.json"
        if not path.is_dir() or not manifest_path.is_file():
            continue
        manifest = _load_json(manifest_path)
        if manifest.get("category") == "finance":
            plugins.append((path, manifest))
    return plugins


FINANCE = _finance_plugins()
FINANCE_IDS = [manifest["id"] for _, manifest in FINANCE]
PARAMS = [path for path, _ in FINANCE]


def _ui_schema(manifest: dict) -> dict:
    widgets = manifest["contributes"]["widgets"]
    render = widgets[0]["render"]
    assert render["type"] == "ui-schema"
    return _load_json(PLUGINS_DIR / manifest["id"] / render["file"])


def test_finance_family_discovers_the_six_plugins():
    assert set(FINANCE_IDS) == EXPECTED_FINANCE_IDS


@pytest.mark.parametrize("plugin_dir", PARAMS, ids=FINANCE_IDS)
def test_finance_manifest_passes_the_real_validator(plugin_dir):
    verdict = validate_plugin(plugin_dir)

    assert verdict.ok, (plugin_dir.name, verdict.as_dict())


@pytest.mark.parametrize("plugin_dir", PARAMS, ids=FINANCE_IDS)
def test_finance_sample_renders_fresh_with_no_blank_element(plugin_dir):
    rendered = render_sample(plugin_dir)

    assert rendered["status"] == "fresh", (plugin_dir.name, rendered)
    assert rendered["elements"], plugin_dir.name
    blank = [element for element in rendered["elements"]
             if element.get("state") == "blank"]
    assert blank == [], (plugin_dir.name, blank)


@pytest.mark.parametrize("plugin_dir", PARAMS, ids=FINANCE_IDS)
def test_finance_elements_use_only_the_ten_kinds(plugin_dir):
    manifest = _load_json(plugin_dir / "manifest.json")
    kinds = [element["type"] for element in _ui_schema(manifest)["elements"]]

    assert kinds, plugin_dir.name
    assert set(kinds) <= set(ELEMENT_KINDS), (plugin_dir.name, kinds)


@pytest.mark.parametrize("plugin_dir", PARAMS, ids=FINANCE_IDS)
def test_finance_sample_binds_every_element_slot(plugin_dir):
    manifest = _load_json(plugin_dir / "manifest.json")
    sample = _load_json(plugin_dir / manifest["sample"])
    bindings = sample["bindings"]
    missing = []
    for element in _ui_schema(manifest)["elements"]:
        for key in SLOT_KEYS:
            name = element.get(key)
            if isinstance(name, str) and name not in bindings:
                missing.append(f"{element['type']}.{key}={name}")
    assert missing == [], (plugin_dir.name, missing)
