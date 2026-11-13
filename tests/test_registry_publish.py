"""Publishing a local release into the registry (ticket #63).

A publish validates the source through the shared validator, copies the
tree into the registry's plugins/<id>/ directory, pins it in index.json
by the same tree digest install verifies, and marks the release
``source: "local"``: no git tag exists for it, so installs resolve it
straight from the plugins directory. Refusals are named, validator
style, and the index stays total: every new shape loads or raises with
a named reason.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from registry_fixtures import PLUGIN_FIXTURE, tree_digest  # noqa: E402


def make_plugin(tmp_path: Path, plugin_id: str, version: str) -> Path:
    """A valid plugin directory with the given id and version, shaped
    like the repo fixture (manifest plus ui schema)."""
    source = tmp_path / "built" / plugin_id
    source.mkdir(parents=True, exist_ok=True)
    for item in PLUGIN_FIXTURE.rglob("*"):
        if item.is_file():
            target = source / item.relative_to(PLUGIN_FIXTURE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["id"] = plugin_id
    manifest["version"] = version
    (source / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                          encoding="utf-8")
    return source


def bare_registry(tmp_path: Path) -> Path:
    """A registry root with an empty index and no git at all: a local
    release must publish and install without a single git invocation."""
    root = tmp_path / "bare-registry"
    (root / "plugins").mkdir(parents=True)
    (root / "index.json").write_text(
        json.dumps({"schemaVersion": 1, "plugins": []}, indent=2) + "\n",
        encoding="utf-8")
    return root


def publish(root: Path, plugin_id: str, version: str, source: Path):
    from agentdesk.registry.publish import publish_to_registry
    return publish_to_registry(root, plugin_id, version=version,
                               source_dir=source)


def test_publish_lands_a_local_release_pinned_by_digest(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")

    out = publish(root, "team-notes-widget", "0.1.0", source)

    assert out["ok"] is True
    assert out["plugin"] == "team-notes-widget"
    assert out["version"] == "0.1.0"
    assert out["source"] == "local"
    # The tree landed in the registry, versioned under the plugin id.
    landed = root / "plugins" / "team-notes-widget" / "0.1.0"
    assert (landed / "manifest.json").is_file()
    assert (landed / "widget.ui.json").is_file()
    # The pin is the tree digest of exactly what landed.
    assert out["sha256"] == tree_digest(landed)
    assert out["sha256"] == tree_digest(source)

    from agentdesk.registry.index import load_index
    index = load_index((root / "index.json").read_text(encoding="utf-8"))
    entry = index.plugin("team-notes-widget")
    assert entry is not None
    assert entry.latest == "0.1.0"
    assert entry.class_ == "declarative"
    release = entry.release_for("0.1.0")
    assert release.sha256 == out["sha256"]
    assert release.source == "local"
    assert release.tag == ""


def test_published_index_round_trips_byte_faithfully(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    publish(root, "team-notes-widget", "0.1.0", source)

    from agentdesk.registry.index import load_index
    raw = (root / "index.json").read_text(encoding="utf-8")
    index = load_index(raw)
    assert json.loads(index.to_json()) == json.loads(raw)
    # And the total-loader guarantee: reload of the reload is the same.
    again = load_index(index.to_json())
    assert json.loads(again.to_json()) == json.loads(raw)


def test_local_release_installs_end_to_end_without_git(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    published = publish(root, "team-notes-widget", "0.1.0", source)

    from agentdesk.registry.install import install_from_registry, read_lock
    out = install_from_registry(root, "team-notes-widget", version="0.1.0",
                                destination=tmp_path / "client")
    assert out["ok"] is True
    assert out["sha256"] == published["sha256"]
    installed = tmp_path / "client" / "team-notes-widget-0.1.0"
    assert (installed / "manifest.json").is_file()
    # The client lockfile records the pin.
    lock = read_lock(tmp_path / "client", "team-notes-widget")
    assert lock["version"] == "0.1.0"
    assert lock["sha256"] == published["sha256"]


def test_tampered_local_release_refuses_on_hash(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    publish(root, "team-notes-widget", "0.1.0", source)
    manifest_path = (root / "plugins" / "team-notes-widget" / "0.1.0"
                     / "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = "Quietly different"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")

    from agentdesk.registry.install import RegistryError, install_from_registry
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(root, "team-notes-widget", version="0.1.0",
                              destination=tmp_path / "client")
    assert excinfo.value.code == "install:hash-mismatch"


def test_missing_plugins_dir_refuses_with_named_error(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    publish(root, "team-notes-widget", "0.1.0", source)
    shutil.rmtree(root / "plugins" / "team-notes-widget" / "0.1.0")

    from agentdesk.registry.install import RegistryError, install_from_registry
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(root, "team-notes-widget", version="0.1.0",
                              destination=tmp_path / "client")
    assert excinfo.value.code == "install:local-plugin-missing"


def test_duplicate_id_and_version_is_refused(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    publish(root, "team-notes-widget", "0.1.0", source)
    # Even identical content: the pin already exists.
    from agentdesk.registry.publish import RegistryError
    with pytest.raises(RegistryError) as excinfo:
        publish(root, "team-notes-widget", "0.1.0", source)
    assert excinfo.value.code == "publish:already-exists"


def test_new_version_appends_cleanly_and_ci_stays_green(tmp_path):
    from agentdesk.registry.ci import review_registry_changes
    from agentdesk.registry.index import load_index

    root = bare_registry(tmp_path)
    first = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    publish(root, "team-notes-widget", "0.1.0", first)
    base_index = (root / "index.json").read_text(encoding="utf-8")

    second = make_plugin(tmp_path, "team-notes-widget", "0.2.0")
    out = publish(root, "team-notes-widget", "0.2.0", second)

    index = load_index((root / "index.json").read_text(encoding="utf-8"))
    entry = index.plugin("team-notes-widget")
    assert [r.version for r in entry.releases] == ["0.1.0", "0.2.0"]
    assert entry.latest == "0.2.0"
    # The plugins directory holds the newly published tree, versioned.
    assert tree_digest(root / "plugins" / "team-notes-widget" / "0.2.0") \
        == out["sha256"]
    # Registry CI over the mutated index: green.
    review = review_registry_changes(
        root, [root / "plugins" / "team-notes-widget" / "0.2.0"],
        base_index_text=base_index)
    assert review["ok"] is True, review["reasons"]


def test_publishing_a_new_version_keeps_earlier_local_releases(tmp_path):
    """The P1 review fix, pinned: each local release is digest-pinned to
    its own versioned directory, so publishing 0.2.0 must leave 0.1.0
    exactly where its pin says it is."""
    root = bare_registry(tmp_path)
    first = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    published_1 = publish(root, "team-notes-widget", "0.1.0", first)
    second = make_plugin(tmp_path, "team-notes-widget", "0.2.0")
    publish(root, "team-notes-widget", "0.2.0", second)

    # Both versioned trees exist side by side, each with its manifest.
    for version, sha in (("0.1.0", published_1["sha256"]),):
        tree = root / "plugins" / "team-notes-widget" / version
        assert (tree / "manifest.json").is_file()
        assert (tree / "widget.ui.json").is_file()
        assert tree_digest(tree) == sha
    assert (root / "plugins" / "team-notes-widget" / "0.2.0"
            / "manifest.json").is_file()

    # The old release installs by exact pin and hash-verifies.
    from agentdesk.registry.install import install_from_registry
    out = install_from_registry(root, "team-notes-widget", version="0.1.0",
                                sha256=published_1["sha256"],
                                destination=tmp_path / "client")
    assert out["ok"] is True
    assert out["sha256"] == published_1["sha256"]
    installed_manifest = json.loads(
        (tmp_path / "client" / "team-notes-widget-0.1.0" / "manifest.json")
        .read_text(encoding="utf-8"))
    assert installed_manifest["version"] == "0.1.0"

    # And the new one still installs too, unpinned (latest resolves it).
    out = install_from_registry(root, "team-notes-widget", version="0.2.0",
                                destination=tmp_path / "client2")
    assert out["version"] == "0.2.0"


def test_publishing_an_older_version_keeps_latest(tmp_path):
    """The P2 review fix, pinned: publishing an older version (say after
    a rollback) appends history without dragging latest, and therefore
    unpinned installs, backwards."""
    from agentdesk.registry.index import load_index

    root = bare_registry(tmp_path)
    publish(root, "team-notes-widget", "0.1.0",
            make_plugin(tmp_path, "team-notes-widget", "0.1.0"))
    publish(root, "team-notes-widget", "0.2.0",
            make_plugin(tmp_path, "team-notes-widget", "0.2.0"))
    publish(root, "team-notes-widget", "0.1.1",
            make_plugin(tmp_path, "team-notes-widget", "0.1.1"))

    index = load_index((root / "index.json").read_text(encoding="utf-8"))
    entry = index.plugin("team-notes-widget")
    assert [r.version for r in entry.releases] == ["0.1.0", "0.2.0", "0.1.1"]
    assert entry.latest == "0.2.0"

    # Unpinned resolution follows latest, not the last append.
    from agentdesk.registry.source import stage_registry_install
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage_registry_install(root, "team-notes-widget",
                                        staging_dir=Path(tmp))
        assert staged["version"] == "0.2.0"


def test_latest_advances_by_numeric_compare_not_lexical(tmp_path):
    """0.10.0 is newer than 0.9.0; a string compare would say otherwise."""
    from agentdesk.registry.index import load_index

    root = bare_registry(tmp_path)
    publish(root, "team-notes-widget", "0.9.0",
            make_plugin(tmp_path, "team-notes-widget", "0.9.0"))
    publish(root, "team-notes-widget", "0.10.0",
            make_plugin(tmp_path, "team-notes-widget", "0.10.0"))

    index = load_index((root / "index.json").read_text(encoding="utf-8"))
    assert index.plugin("team-notes-widget").latest == "0.10.0"

    publish(root, "team-notes-widget", "0.2.0",
            make_plugin(tmp_path, "team-notes-widget", "0.2.0"))
    index = load_index((root / "index.json").read_text(encoding="utf-8"))
    assert index.plugin("team-notes-widget").latest == "0.10.0"


def test_publish_refuses_an_invalid_plugin(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["permissions"]["shell"] = "full"  # Class D refuses this
    (source / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                          encoding="utf-8")

    from agentdesk.registry.publish import RegistryError
    with pytest.raises(RegistryError) as excinfo:
        publish(root, "team-notes-widget", "0.1.0", source)
    assert excinfo.value.code == "publish:validator-failed"
    # Nothing landed: the registry is untouched.
    assert not (root / "plugins" / "team-notes-widget").exists()
    from agentdesk.registry.index import load_index
    assert load_index((root / "index.json").read_text(encoding="utf-8")).plugins == ()


def test_publish_refuses_a_manifest_that_disagrees(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")

    from agentdesk.registry.publish import RegistryError
    with pytest.raises(RegistryError) as excinfo:
        publish(root, "team-notes-widget", version="9.9.9", source=source)
    assert excinfo.value.code == "publish:manifest-mismatch"
    with pytest.raises(RegistryError) as excinfo:
        publish(root, "somebody-else", version="0.1.0", source=source)
    assert excinfo.value.code == "publish:manifest-mismatch"


def test_publish_refuses_unsafe_names(tmp_path):
    root = bare_registry(tmp_path)
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")

    from agentdesk.registry.publish import RegistryError
    with pytest.raises(RegistryError) as excinfo:
        publish(root, "../escape", version="0.1.0", source=source)
    assert excinfo.value.code == "publish:unsafe-name"
    with pytest.raises(RegistryError) as excinfo:
        publish(root, "team-notes-widget", version="..", source=source)
    assert excinfo.value.code == "publish:unsafe-name"


def test_publish_refuses_an_unreadable_index(tmp_path):
    root = tmp_path / "not-a-registry"
    root.mkdir()
    source = make_plugin(tmp_path, "team-notes-widget", "0.1.0")

    from agentdesk.registry.publish import RegistryError
    with pytest.raises(RegistryError) as excinfo:
        publish(root, "team-notes-widget", "0.1.0", source)
    assert excinfo.value.code == "publish:index-unreadable"


def test_publish_root_names_the_three_resolution_sources(monkeypatch):
    from agentdesk.registry import source as registry_source
    from agentdesk.registry.publish import RegistryError, resolve_publish_root

    monkeypatch.delenv("AGENTDESK_REGISTRY", raising=False)
    monkeypatch.setattr(registry_source, "discover_repo_registry",
                        lambda: None)

    class EmptySettings:
        @staticmethod
        def get(_key):
            return ""

    with pytest.raises(RegistryError) as excinfo:
        resolve_publish_root(settings_store=EmptySettings())
    assert excinfo.value.code == "publish:no-registry"
    message = str(excinfo.value)
    for needle in ("registry_path", "AGENTDESK_REGISTRY", "checkout"):
        assert needle in message


def test_publish_root_resolves_in_the_sacred_order(tmp_path, monkeypatch):
    from agentdesk.registry import source as registry_source
    from agentdesk.registry.publish import resolve_publish_root

    monkeypatch.delenv("AGENTDESK_REGISTRY", raising=False)
    by_settings = tmp_path / "by-settings"
    by_settings.mkdir()
    by_env = tmp_path / "by-env"
    by_env.mkdir()

    class Settings:
        def __init__(self, value: str) -> None:
            self.value = value

        def get(self, _key):
            return self.value

    assert resolve_publish_root(settings_store=Settings(str(by_settings)),
                                environ={}) == by_settings
    # The environment wins only when settings are silent.
    assert resolve_publish_root(settings_store=Settings(""),
                                environ={"AGENTDESK_REGISTRY": str(by_env)}) == by_env
    monkeypatch.setattr(registry_source, "discover_repo_registry",
                        lambda: by_settings)
    assert resolve_publish_root(settings_store=Settings(""),
                                environ={}) == by_settings


# -- the index schema: the local release shape --------------------------------


def release_document(**overrides) -> dict:
    document = {"version": "0.1.0", "sha256": "a" * 64, "tag": "x-0.1.0",
                "yanked": False}
    document.update(overrides)
    return document


def load_one_release(release: dict):
    from agentdesk.registry.index import load_index
    raw = json.dumps({"schemaVersion": 1, "plugins": [
        {"id": "p", "publisher": "pub", "latest": "0.1.0", "risk": "low",
         "class": "declarative", "releases": [release]}]})
    return load_index(raw)


def test_local_release_loads_without_a_tag(tmp_path):
    index = load_one_release({"version": "0.1.0", "sha256": "a" * 64,
                              "source": "local"})
    release = index.plugins[0].releases[0]
    assert release.source == "local"
    assert release.tag == ""
    # Round-trip keeps the shape: source local, no tag key.
    round_tripped = json.loads(index.to_json())["plugins"][0]["releases"][0]
    assert round_tripped["source"] == "local"
    assert "tag" not in round_tripped


def test_tag_release_still_requires_a_tag():
    from agentdesk.registry.index import RegistryIndexError
    with pytest.raises(RegistryIndexError, match="index:release-tag-missing"):
        load_one_release({"version": "0.1.0", "sha256": "a" * 64})


def test_unknown_release_source_is_a_named_error():
    from agentdesk.registry.index import RegistryIndexError
    with pytest.raises(RegistryIndexError, match="index:release-source-invalid"):
        load_one_release({"version": "0.1.0", "sha256": "a" * 64,
                          "source": "tarball"})


def test_local_release_with_a_tag_is_a_named_error():
    from agentdesk.registry.index import RegistryIndexError
    with pytest.raises(RegistryIndexError, match="index:release-local-tag-present"):
        load_one_release({"version": "0.1.0", "sha256": "a" * 64,
                          "tag": "x-0.1.0", "source": "local"})
