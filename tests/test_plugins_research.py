"""Research family plugins: research-brief, source-ledger, competitor-watch,
notes-actions.

Each directory goes through the real validator, and each packaged sample
through the host renderer, so the marketplace preview is proven to draw
every element without a blank. Nothing here reads outside the plugin
directory or starts a server.
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
FAMILY = ("research-brief", "source-ledger", "competitor-watch", "notes-actions")
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


def test_research_brief_is_the_upgraded_plugin():
    manifest = manifest_of("research-brief")
    assert manifest["version"] == "0.2.0"
    assert manifest["contributes"]["skills"] == ["skills/research-recap/SKILL.md"]
    assert (
        plugin_dir("research-brief") / "skills" / "research-recap" / "SKILL.md"
    ).is_file()
    assert data_source_of("research-brief")["type"] == "research-brief"

    slots = [
        (element["type"], element.get("binding"), element.get("label"))
        for element in ui_schema_of("research-brief")["elements"]
    ]
    assert slots == [
        ("text", "summary", "Latest answer"),
        ("metric", "sourcesCount", "Sources"),
        ("text", "answeredAt", "Answered"),
    ]


def test_source_ledger_reads_the_research_brief_source():
    assert data_source_of("source-ledger")["type"] == "research-brief"

    table, metric = ui_schema_of("source-ledger")["elements"]
    assert table["type"] == "table"
    assert table["title"] == "Sources"
    assert table["rowsBinding"] == "sourceTable"
    assert table["columns"] == ["Source", "Title", "Used"]
    assert metric["type"] == "metric"
    assert metric["binding"] == "sourcesCount"
    assert metric["label"] == "Entries"

    rows = sample_of("source-ledger")["bindings"]["sourceTable"]
    assert rows and all(len(row) == 3 for row in rows)


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

    readme = (plugin_dir("competitor-watch") / "README.md").read_text(encoding="utf-8")
    text = " ".join(readme.lower().split())
    assert "excluded from every pack" in text
    assert "admin network approval" in text

    for other_id in FAMILY:
        if other_id == "competitor-watch":
            continue
        other = manifest_of(other_id)
        assert other["permissions"]["network"].get("allow", []) == []
        assert "optionalPermissions" not in other
        assert data_source_of(other_id)["type"] != "http-get"


def test_notes_actions_reads_the_actions_heading():
    manifest = manifest_of("notes-actions")
    source = data_source_of("notes-actions")
    assert source["type"] == "markdown-watch"
    assert source["file"] == "${workspace}/notes/*.md"
    assert source["heading"] == "Actions"
    assert manifest["permissions"]["filesystem"]["read"] == ["${workspace}/notes/*.md"]

    checklist, metric, status = ui_schema_of("notes-actions")["elements"]
    assert (checklist["type"], checklist["title"], checklist["itemsBinding"]) == (
        "checklist", "Actions", "items",
    )
    assert (metric["type"], metric["binding"], metric["label"]) == (
        "metric", "openCount", "Open",
    )
    assert (status["type"], status["toneBinding"], status["binding"]) == (
        "status", "tone", "nextDue",
    )

    items = sample_of("notes-actions")["bindings"]["items"]
    assert items and all({"text", "done", "due"} <= set(item) for item in items)
