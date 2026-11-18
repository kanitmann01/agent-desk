"""Communication family: the three mail plugins, authored against v2.

Every plugin in the family is declarative: a v2 manifest, a ui-schema of
known element kinds, a sample that binds every element, and a README. The
mail metadata bridge emits header counts only, so the family's list
elements point at the closest frozen name and are proven blank rather
than fed an invented rows binding.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.plugins.render import ELEMENT_KINDS, render_sample  # noqa: E402
from agentdesk.validator.core import validate_plugin  # noqa: E402

PLUGINS = ROOT / "registry" / "plugins"
FAMILY = "communication"
EXPECTED_IDS = {"outlook-digest", "vip-watch", "waiting-on-you"}

# The host's mail vocabulary (docs/design/plugin-authoring-v2.md,
# section "Binding vocabulary emitted by the host"). outlook-brief adds the
# ranked-message and reply-starter names; the other family members keep
# reading the older mail-digest bridge.
MAIL_BINDINGS = {
    "messages", "threads", "unread", "topSenders", "windowNote",
    "sendersRows", "vipRows", "waitingRows",
    "threadRows", "topEmailSubject", "topEmailLine", "topEmailWhy",
    "replyOptions",
}

# Every list, table, timeline and checklist element binds a row binding the
# host actually emits, so no communication card renders blank on live data.
GAP_ELEMENTS: dict[str, set[tuple[str, str]]] = {}

SLOT_BY_KIND = {
    "list": "rowsBinding",
    "table": "rowsBinding",
    "sparkline": "pointsBinding",
    "timeline": "itemsBinding",
    "checklist": "itemsBinding",
}

ELEMENT_FILES = {"manifest.json", "widget.ui.json", "sample.json", "README.md"}

BINDING_KEYS = (
    "binding",
    "rowsBinding",
    "directionBinding",
    "toneBinding",
    "itemsBinding",
    "pointsBinding",
    "targetBinding",
)


def _family():
    """(dir, manifest) for every committed communication plugin."""
    found = []
    for manifest_path in sorted(PLUGINS.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("category") == FAMILY:
            found.append((manifest_path.parent, manifest))
    return found


def _schema(plugin_dir):
    return json.loads(
        (plugin_dir / "widget.ui.json").read_text(encoding="utf-8-sig")
    )


def _sample(plugin_dir, manifest):
    return json.loads(
        (plugin_dir / manifest["sample"]).read_text(encoding="utf-8-sig")
    )


def _primary_binding(element):
    slot = SLOT_BY_KIND.get(element.get("type"), "binding")
    return slot, element.get(slot)


def test_the_family_contains_its_three_plugins():
    ids = {plugin_dir.name for plugin_dir, _ in _family()}
    assert EXPECTED_IDS <= ids


def test_every_communication_plugin_validates_as_v2():
    for plugin_dir, manifest in _family():
        assert manifest["schemaVersion"] == 2, plugin_dir.name
        verdict = validate_plugin(plugin_dir)
        assert verdict.ok, (plugin_dir.name, verdict.as_dict())


def test_manifest_metadata_matches_the_family_contract():
    for plugin_dir, manifest in _family():
        name = plugin_dir.name
        assert manifest["category"] == FAMILY, name
        assert manifest["icon"] == "mail", name
        assert 0 < len(manifest["summary"]) <= 120, name
        assert manifest["description"].strip(), name
        tags = manifest["tags"]
        assert len(tags) == 3, name
        assert len(set(tags)) == 3, name
        assert all(tag.islower() and tag.strip() for tag in tags), name
        highlights = manifest["highlights"]
        assert len(highlights) == 3, name
        assert all(0 < len(line) <= 120 for line in highlights), name
        if name == "outlook-digest":
            assert manifest["version"] == "0.3.0"
        else:
            assert manifest["version"] == "0.1.0"


def test_every_element_uses_a_known_kind_and_a_frozen_mail_binding():
    for plugin_dir, _ in _family():
        for element in _schema(plugin_dir)["elements"]:
            kind = element["type"]
            assert kind in ELEMENT_KINDS, (plugin_dir.name, kind)
            names = [element[key] for key in BINDING_KEYS if key in element]
            if kind in SLOT_BY_KIND:
                assert element[SLOT_BY_KIND[kind]] in MAIL_BINDINGS, (
                    plugin_dir.name, element)
            if not names:
                continue
            for binding in names:
                assert binding in MAIL_BINDINGS, (plugin_dir.name, binding)


def test_sample_binds_every_element():
    for plugin_dir, manifest in _family():
        sample = _sample(plugin_dir, manifest)
        assert sample["state"] == "ok", plugin_dir.name
        assert sample["checkedAt"], plugin_dir.name
        bindings = sample["bindings"]
        assert isinstance(bindings, dict), plugin_dir.name
        for element in _schema(plugin_dir)["elements"]:
            _, binding = _primary_binding(element)
            assert binding in bindings, (plugin_dir.name, element)


def test_sample_renders_fresh_with_only_the_documented_gaps():
    for plugin_dir, manifest in _family():
        name = plugin_dir.name
        schema_elements = _schema(plugin_dir)["elements"]
        rendered = render_sample(plugin_dir)
        assert rendered["status"] == "fresh", name
        assert rendered["cause"] == "", name
        assert rendered["checked_at"] == _sample(plugin_dir, manifest)["checkedAt"]
        assert len(rendered["elements"]) == len(schema_elements), name

        gaps = GAP_ELEMENTS.get(name, set())
        for element, dto in zip(schema_elements, rendered["elements"]):
            _, binding = _primary_binding(element)
            if (element["type"], binding) in gaps:
                assert dto["state"] == "blank", (name, binding)
                assert dto["rows"] == [], (name, binding)
                assert binding in dto["reason"], (name, binding)
            else:
                assert dto["state"] == "ok", (name, dto)


def test_outlook_digest_upgrades_in_place_and_keeps_its_skill():
    plugin_dir = PLUGINS / "outlook-digest"
    manifest = json.loads(
        (plugin_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["id"] == "outlook-digest"
    assert manifest["version"] == "0.3.0"
    assert manifest["contributes"]["skills"] == ["skills/mail-overview/SKILL.md"]
    assert (plugin_dir / "skills" / "mail-overview" / "SKILL.md").is_file()


def test_permissions_are_metadata_only():
    for plugin_dir, manifest in _family():
        permissions = manifest["permissions"]
        assert permissions["filesystem"] == {"read": [], "write": []}, (
            plugin_dir.name)
        assert permissions["network"] == {"allow": []}, plugin_dir.name
        assert permissions["llm"] == {"allow": False}, plugin_dir.name
        assert permissions["shell"] == "none", plugin_dir.name


def test_every_widget_reads_the_mail_metadata_bridge():
    for plugin_dir, manifest in _family():
        widgets = manifest["contributes"]["widgets"]
        assert widgets, plugin_dir.name
        for widget in widgets:
            expected = ({"type": "outlook-brief"}
                        if plugin_dir.name == "outlook-digest"
                        else {"type": "mail-digest"})
            assert widget["dataSource"] == expected, plugin_dir.name
            render = widget["render"]
            assert render["type"] == "ui-schema"
            assert (plugin_dir / render["file"]).is_file(), plugin_dir.name


def test_no_plugin_ships_code():
    for plugin_dir, _ in _family():
        for path in plugin_dir.rglob("*"):
            if path.is_dir():
                continue
            relative = path.relative_to(plugin_dir)
            if relative.parts[0] == "skills":
                continue
            assert relative.name in ELEMENT_FILES, (plugin_dir.name, str(relative))
