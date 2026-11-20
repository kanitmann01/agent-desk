"""The two shipped plugins keep the publishing contract after spec 015.

The retirement (spec 015, issue #188) leaves exactly two in-box plugins:
excel-report (the workbook tracker card) and competitor-watch (the page
watch card). This file holds the contract that still applies to them: the
shared validator accepts each plugin, registry review CI passes over the
shipped index, every release pin equals the recomputed tree digest, the
listing payload names both, the executable card binds only names its
source type computes, every sample renders complete (no blank elements),
and excel-report still installs and shows its honest setup state without
a workbook.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import excel_fixtures  # noqa: E402

from agentdesk.plugins.execute import BINDINGS, PluginWidgetRunner  # noqa: E402
from agentdesk.plugins.render import ELEMENT_KINDS, render_sample  # noqa: E402
from agentdesk.plugins.runtime import PluginRuntime  # noqa: E402
from agentdesk.registry.ci import review_registry_changes  # noqa: E402
from agentdesk.registry.index import load_index  # noqa: E402
from agentdesk.registry.install import tree_digest  # noqa: E402
from agentdesk.validator.core import validate_plugin  # noqa: E402

REGISTRY = ROOT / "registry"
PLUGINS = REGISTRY / "plugins"

# The whole shipped library after the retirement: id -> latest version.
LIBRARY = {
    "competitor-watch": "0.1.0",
    "excel-report": "0.1.0",
}

# The names the executable excel-watch source computes; its card may bind
# only these. competitor-watch's http-get vocabulary (changed/rows/
# fetchedAt) belongs to the http-get bridge, not the runner's BINDINGS.
EXCEL_BINDINGS = {
    "value", "delta24h", "addedCount", "removedCount", "unchangedCount",
    "rowsSeen", "file", "windowNote",
}

SLOT_KEYS = (
    "binding", "directionBinding", "rowsBinding", "pointsBinding",
    "itemsBinding", "targetBinding", "toneBinding",
)


def _manifest(plugin_id: str) -> dict:
    return json.loads((PLUGINS / plugin_id / "manifest.json").read_text(
        encoding="utf-8"))


def _ui_schema(plugin_id: str) -> dict:
    manifest = _manifest(plugin_id)
    render = manifest["contributes"]["widgets"][0]["render"]
    assert render["type"] == "ui-schema"
    return json.loads((PLUGINS / plugin_id / render["file"]).read_text(
        encoding="utf-8"))


def _one_card(runtime):
    cards = runtime.widget_cards()
    assert len(cards) == 1
    return cards[0]


# ---- the publishing contract -------------------------------------------


@pytest.mark.parametrize("plugin_id", LIBRARY)
def test_shared_validator_accepts_each_shipped_plugin(plugin_id):
    verdict = validate_plugin(PLUGINS / plugin_id)
    assert verdict.ok, verdict.failures


@pytest.mark.parametrize("plugin_id", LIBRARY)
def test_every_plugin_stays_inside_the_declarative_vocabulary(plugin_id):
    """Keep every shipped plugin declarative and deny-by-default.

    No shell, no LLM, no unscoped glob, no HTML. The only network grant is
    competitor-watch's host consent, declared as an optional permission
    rather than a base one.
    """
    manifest = _manifest(plugin_id)
    assert manifest["class"] == "declarative"
    permissions = manifest["permissions"]
    assert permissions["network"]["allow"] == []
    assert permissions["shell"] == "none"
    assert permissions["llm"]["allow"] is False
    for glob in permissions["filesystem"].get("read", []):
        assert glob.startswith("${workspace}/") or glob == "${pluginData}"
    render = manifest["contributes"]["widgets"][0]["render"]
    assert render["type"] == "ui-schema"
    assert render["file"].endswith(".json")


def test_registry_ci_passes_over_the_shipped_index():
    """The same review CI runs passes over the two-entry shipped index."""
    base = json.loads((REGISTRY / "index.json").read_text(encoding="utf-8"))
    result = review_registry_changes(
        REGISTRY,
        [PLUGINS / plugin_id for plugin_id in LIBRARY],
        base_index_text=json.dumps(base),
    )
    assert result == {"ok": True, "reasons": []}, result["reasons"]


def test_index_pins_match_the_published_trees():
    index = load_index((REGISTRY / "index.json").read_text(encoding="utf-8"))
    assert {entry.id for entry in index.plugins} == set(LIBRARY)
    for plugin_id, version in LIBRARY.items():
        entry = index.plugin(plugin_id)
        assert entry is not None, plugin_id
        release = entry.release_for(version)
        assert release is not None, plugin_id
        if release.source == "local":
            assert release.tag == ""
        else:
            assert release.tag == f"{entry.id}-{release.version}"
        assert release.yanked is False
        assert entry.class_ == "declarative"
        assert release.sha256 == tree_digest(PLUGINS / entry.id), entry.id


def test_listing_payload_carries_the_whole_library():
    """The /plugins page's listing payload names both entries with their
    pinned releases, the payload the registry bridge serves."""
    from agentdesk.registry.source import registry_listing

    listing = registry_listing(REGISTRY)
    assert listing["ok"] is True, listing
    by_id = {entry["id"]: entry for entry in listing["plugins"]}
    assert set(LIBRARY) <= set(by_id)
    assert len(by_id) == len(load_index(
        (REGISTRY / "index.json").read_text(encoding="utf-8")).plugins)
    for plugin_id, version in LIBRARY.items():
        entry = by_id[plugin_id]
        assert entry["class"] == "declarative"
        assert entry["latest"] == version
        release = next(item for item in entry["releases"]
                       if item["version"] == version)
        if release["source"] == "tag":
            assert release["tag"] == f"{plugin_id}-{version}"
        else:
            assert release["tag"] == ""
        assert release["yanked"] is False


# ---- the binding vocabulary --------------------------------------------


def test_the_excel_card_binds_only_names_its_source_computes():
    """Unknown-binding safety, pinned at the source: the excel-watch card
    may bind only names the runner's excel vocabulary computes."""
    schema = _ui_schema("excel-report")
    bound = {element["binding"] for element in schema["elements"]
             if "binding" in element}
    assert bound
    assert bound <= EXCEL_BINDINGS
    assert bound <= set(BINDINGS)


# ---- every sample is complete ------------------------------------------


@pytest.mark.parametrize("plugin_id", LIBRARY)
def test_every_sample_renders_fresh_with_no_blank_element(plugin_id):
    rendered = render_sample(PLUGINS / plugin_id)
    assert rendered["status"] == "fresh", (plugin_id, rendered)
    assert rendered["elements"], plugin_id
    blank = [element for element in rendered["elements"]
             if element.get("state") == "blank"]
    assert blank == [], (plugin_id, blank)
    kinds = [element["type"] for element in _ui_schema(plugin_id)["elements"]]
    assert kinds, plugin_id
    assert set(kinds) <= set(ELEMENT_KINDS), (plugin_id, kinds)


def test_the_excel_sample_binds_every_element_slot():
    manifest = _manifest("excel-report")
    sample = json.loads((PLUGINS / "excel-report" /
                         manifest["sample"]).read_text(encoding="utf-8"))
    bindings = sample["bindings"]
    missing = []
    for element in _ui_schema("excel-report")["elements"]:
        for key in SLOT_KEYS:
            name = element.get(key)
            if isinstance(name, str) and name not in bindings:
                missing.append(f"{element['type']}.{key}={name}")
    assert missing == []


# ---- excel-report installs ---------------------------------------------


def _excel_runner(workspace: Path, tmp_path: Path, clock: list[float]):
    """The real excel pipeline (shadow copy, stdlib parser) over a real
    .xlsx, with the shadow dir kept inside the test's temp tree. The
    clock is a one-cell list the test moves between windows."""
    from agentdesk.excel import shadow as shadow_mod
    from agentdesk.excel import xlsx as xlsx_mod
    from agentdesk.excel.watcher import Adapters

    return PluginWidgetRunner(
        workspace, adapters=Adapters(
            copy_shadow=lambda path: shadow_mod.copy_to_shadow(
                path, workdir=tmp_path / "shadow"),
            parse_workbook=xlsx_mod.parse_workbook_file,
            clock=lambda: clock[0]))


def test_excel_report_installs_and_waits_for_a_confirmed_file(tmp_path):
    workspace = tmp_path / "workspace" / "reports"
    workspace.mkdir(parents=True)
    (workspace / "report.xlsx").write_bytes(
        excel_fixtures.make_xlsx(excel_fixtures.BASE_ROWS))
    clock = [1_000_000.0]
    runner = _excel_runner(workspace.parent, tmp_path, clock)
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins", data_dir=tmp_path / "plugin-data",
        workspace_dir=workspace.parent, runner=runner)
    runtime.install(PLUGINS / "excel-report", source="dir")
    card = _one_card(runtime)
    assert card["id"] == "excel-report"
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["step"] == "source"
    # A workbook sitting in the old reports folder is not read on install.
    assert card["payload"]["elements"] == []


def test_excel_report_with_no_workbook_asks_for_one(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = _excel_runner(workspace, tmp_path, [1_000_000.0])
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins", data_dir=tmp_path / "plugin-data",
        workspace_dir=workspace, runner=runner)
    runtime.install(PLUGINS / "excel-report", source="dir")
    card = _one_card(runtime)
    assert card["freshness"] == "setup"
    assert card["cause"] == ""
    assert card["payload"]["setup"]["step"] == "source"


def test_the_packs_document_is_empty():
    """Retire the packs document to an empty list."""
    packs = json.loads((REGISTRY / "packs.json").read_text(encoding="utf-8"))
    assert packs == {"schemaVersion": 1, "packs": []}


def test_excel_report_is_reference_and_unpacked():
    manifest = _manifest("excel-report")
    assert manifest["category"] == "reference"
    assert manifest["id"] == "excel-report"
    assert manifest["version"] == "0.1.0"
    assert manifest["config"]["kinds"] == ["workbook"]
    assert "file" not in manifest["contributes"]["widgets"][0]["dataSource"]
    assert validate_plugin(PLUGINS / "excel-report").ok

