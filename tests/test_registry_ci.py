"""Registry CI review (ticket #10): the shared validator, a dependency
scan, hash consistency, and append-only history.

The review runs the same validate_plugin entry point the client runs
(byte-identical CI, per the spec), checks that every indexed dependency
exists, recomputes the tree digest against the index pin, and refuses
any index that truncates release history: clients pinned to older
versions must keep resolving.
"""
import json

from .registry_fixtures import PLUGIN_FIXTURE, make_registry, tree_digest


def index_text(digest, plugin_id="sales-delta-widget", dependencies=None):
    document = {
        "schemaVersion": 1,
        "plugins": [{
            "id": plugin_id,
            "publisher": "acme-tools",
            "latest": "1.2.0",
            "risk": "low",
            "class": "declarative",
            "releases": [{"version": "1.2.0", "sha256": digest,
                          "tag": f"{plugin_id}-1.2.0", "yanked": False}],
        }],
    }
    if dependencies is not None:
        document["plugins"][0]["dependencies"] = dependencies
    return json.dumps(document, indent=2)


def review(tmp_path, digest, plugin_dir=None, plugin_id="sales-delta-widget",
           base_index_text=None, dependencies=None):
    from agentdesk.registry.ci import review_registry_changes
    registry_root = tmp_path / "registry"
    registry_root.mkdir(parents=True)
    (registry_root / "index.json").write_text(
        index_text(digest, plugin_id=plugin_id, dependencies=dependencies),
        encoding="utf-8")
    dirs = [plugin_dir] if plugin_dir else []
    return review_registry_changes(registry_root, dirs,
                                   base_index_text=base_index_text)


def test_valid_plugin_passes_review(tmp_path):
    out = review(tmp_path, tree_digest(PLUGIN_FIXTURE), plugin_dir=PLUGIN_FIXTURE)
    assert out["ok"] is True, out["reasons"]
    assert out["reasons"] == []


def test_validator_failure_blocks_with_named_reason(tmp_path):
    shell = tmp_path / "shell-plugin"
    shell.mkdir()
    validator_fixtures = PLUGIN_FIXTURE.parents[2] / "validator" / "shell-permission"
    for item in validator_fixtures.rglob("*"):
        if item.is_file():
            target = shell / item.relative_to(validator_fixtures)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
    out = review(tmp_path, tree_digest(shell), plugin_dir=shell,
                 plugin_id="shell-plugin")
    assert out["ok"] is False
    assert any(r.startswith("validator:") for r in out["reasons"]), out["reasons"]


def test_hash_inconsistency_blocks(tmp_path):
    out = review(tmp_path, "0" * 64, plugin_dir=PLUGIN_FIXTURE)
    assert out["ok"] is False
    assert any(r.startswith("registry-ci:hash-mismatch") for r in out["reasons"])


def test_unknown_dependency_blocks(tmp_path):
    out = review(tmp_path, tree_digest(PLUGIN_FIXTURE), plugin_dir=PLUGIN_FIXTURE,
                 dependencies=["ghost-plugin"])
    assert out["ok"] is False
    assert "registry-ci:unknown-dependency:ghost-plugin" in out["reasons"]


def test_known_dependency_passes(tmp_path):
    from agentdesk.registry.index import load_index
    base = json.loads(index_text(tree_digest(PLUGIN_FIXTURE)))
    base["plugins"].append(dict(base["plugins"][0], id="base-plugin"))
    registry_root = tmp_path / "registry"
    registry_root.mkdir(parents=True)
    (registry_root / "index.json").write_text(json.dumps(base, indent=2),
                                              encoding="utf-8")
    from agentdesk.registry.ci import review_registry_changes
    out = review_registry_changes(
        registry_root, [PLUGIN_FIXTURE],
        base_index_text=None)
    # ghost is gone; dependencies of sales-delta-widget point at base-plugin
    document = json.loads((registry_root / "index.json").read_text(encoding="utf-8"))
    document["plugins"][0]["dependencies"] = ["base-plugin"]
    (registry_root / "index.json").write_text(json.dumps(document, indent=2),
                                              encoding="utf-8")
    out = review_registry_changes(registry_root, [PLUGIN_FIXTURE])
    assert out["ok"] is True, out["reasons"]


def test_truncated_history_blocks(tmp_path):
    old = index_text("a" * 64)
    document = json.loads(old)
    document["plugins"][0]["releases"].append(
        {"version": "1.3.0", "sha256": "b" * 64,
         "tag": "sales-delta-widget-1.3.0", "yanked": False})
    document["plugins"][0]["latest"] = "1.3.0"
    new = json.dumps(document, indent=2)

    from agentdesk.registry.ci import review_registry_changes
    registry_root = tmp_path / "registry"
    registry_root.mkdir(parents=True)

    # Appending is fine even with no plugin dirs changed.
    (registry_root / "index.json").write_text(new, encoding="utf-8")
    out = review_registry_changes(registry_root, [], base_index_text=old)
    assert out["ok"] is True, out["reasons"]

    # Dropping the old release breaks pins: refuse with a named reason.
    (registry_root / "index.json").write_text(old, encoding="utf-8")
    out = review_registry_changes(registry_root, [], base_index_text=new)
    assert out["ok"] is False
    assert any(r.startswith("registry-ci:history-truncated")
               and "1.3.0" in r for r in out["reasons"])
