"""Registry hardening tests: names are names, not paths.

Ids, versions and tags become filesystem fragments and git pathspecs, so
traversal shapes are refused at every door: index load, resolve, install,
and rollback. The client lockfile is the pointer that rollback repoints.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.registry.index import RegistryIndexError, load_index
from agentdesk.registry.install import (
    RegistryError,
    install_from_registry,
    read_lock,
    rollback,
)
from .registry_fixtures import make_registry


def test_index_refuses_traversal_in_id_version_and_tag(tmp_path):
    document = {
        "schemaVersion": 1,
        "plugins": [{
            "id": "../escaped", "publisher": "p", "latest": "1.0.0",
            "risk": "low", "class": "declarative",
            "releases": [{"version": "1.0.0", "sha256": "0" * 64, "tag": "v1"}],
        }],
    }
    with pytest.raises(RegistryIndexError) as excinfo:
        load_index(json.dumps(document))
    assert "unsafe-id" in str(excinfo.value)

    document["plugins"][0]["id"] = "ok-id"
    document["plugins"][0]["releases"][0]["version"] = "1.0.0/../../x"
    with pytest.raises(RegistryIndexError) as excinfo:
        load_index(json.dumps(document))
    assert "unsafe-version" in str(excinfo.value)

    document["plugins"][0]["releases"][0]["version"] = "1.0.0"
    document["plugins"][0]["releases"][0]["tag"] = "- dash-start"
    with pytest.raises(RegistryIndexError) as excinfo:
        load_index(json.dumps(document))
    assert "unsafe-tag" in str(excinfo.value)


def test_install_refuses_unsafe_names_even_before_the_index(tmp_path):
    repo = make_registry(tmp_path)
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(repo, "../escaped", version="1.2.0",
                              destination=tmp_path / "plugins")
    assert excinfo.value.code == "install:unsafe-name"
    # Nothing was written: the destination was never even created.
    assert not (tmp_path / "plugins").exists()
    assert not (tmp_path / "escaped").exists()


def test_traversal_version_via_the_index_is_refused_at_install(tmp_path):
    """The reproduced exploit: a valid-looking index whose version is a
    path must not escape the destination."""
    repo = make_registry(tmp_path)
    index_path = repo / "index.json"
    document = json.loads(index_path.read_text(encoding="utf-8"))
    document["plugins"][0]["releases"][0]["version"] = "1.2.0/../../escaped"
    index_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(RegistryError) as excinfo:
        install_from_registry(repo, "sales-delta-widget", version="1.2.0/../../escaped",
                              destination=tmp_path / "plugins")
    assert excinfo.value.code == "install:unsafe-name"
    assert not (tmp_path / "escaped").exists()


def test_install_writes_the_client_lockfile(tmp_path):
    repo = make_registry(tmp_path)
    install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                          destination=tmp_path / "plugins")
    lock = read_lock(tmp_path / "plugins", "sales-delta-widget")
    assert lock is not None
    assert lock["version"] == "1.2.0"
    assert len(lock["sha256"]) == 64
    assert lock["history"]["1.2.0"] == lock["sha256"]


def test_rollback_repoints_the_lock_to_an_installed_version(tmp_path):
    repo = make_registry(tmp_path)
    destination = tmp_path / "plugins"
    install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                          destination=destination)
    # An older version directory already on disk, as a previous install
    # would have left it.
    older = destination / "sales-delta-widget-1.1.0"
    older.mkdir()
    (older / "manifest.json").write_text("{}", encoding="utf-8")
    lock_path = destination / "lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    entry = lock["plugins"]["sales-delta-widget"]
    entry["history"]["1.1.0"] = entry["history"]["1.2.0"]  # same tree, older pin
    lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")

    result = rollback(destination, "sales-delta-widget", to_version="1.1.0")
    assert result["ok"] is True
    lock = read_lock(destination, "sales-delta-widget")
    assert lock["version"] == "1.1.0"
    # The versioned directory is untouched: rollback is a repoint, not a
    # re-download.
    assert older.is_dir()


def test_rollback_refuses_missing_versions_and_pins(tmp_path):
    repo = make_registry(tmp_path)
    destination = tmp_path / "plugins"
    install_from_registry(repo, "sales-delta-widget", version="1.2.0",
                          destination=destination)
    with pytest.raises(RegistryError) as excinfo:
        rollback(destination, "sales-delta-widget", to_version="0.9.0")
    assert excinfo.value.code == "rollback:version-not-installed"

    destination2 = tmp_path / "elsewhere"
    destination2.mkdir()
    (destination2 / "sales-delta-widget-1.0.0").mkdir()
    with pytest.raises(RegistryError) as excinfo:
        rollback(destination2, "sales-delta-widget", to_version="1.0.0")
    assert excinfo.value.code == "rollback:unknown-pin"


def test_no_shell_run_interpolates_an_untrusted_ref():
    """The hosted registry workflow (retired with the paid runners)
    interpolated the PR base ref into shell lines, guarded here. The
    guard now covers whatever remains: any workflow file under
    .github/workflows, and the local gate's shell=True call sites,
    which must pass constant command lists only (ci_local's npm calls
    name their fixed commands; no variable ever reaches a shell)."""
    workflows_dir = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for workflow in workflows_dir.glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("run:") or "git show" in line or "git diff" in line:
                assert "${{ github." not in line, f"{workflow.name}: {line.strip()}"
    ci_local = (Path(__file__).resolve().parents[1] / "tools" / "ci_local.py").read_text(encoding="utf-8")
    for line in ci_local.splitlines():
        if "shell=" in line:
            assert "${{" not in line and "os.environ" not in line.split("shell=")[0].rsplit("subprocess.run", 1)[-1], line.strip()


def test_registry_root_document_is_seeded():
    """The committed index loads and tells the truth about the plugin
    directories next to it: every entry's pin equals the recomputed
    tree digest of its plugin directory (after spec 015 the two shipped
    releases are excel-report and competitor-watch)."""
    repo = Path(__file__).resolve().parents[1]
    raw = (repo / "registry" / "index.json").read_text(encoding="utf-8")
    index = load_index(raw)
    assert index is not None
    ids = {entry.id for entry in index.plugins}
    assert ids == {"excel-report", "competitor-watch"}
    from agentdesk.registry.install import tree_digest
    for entry in index.plugins:
        release = entry.release_for(entry.latest)
        assert release is not None, entry.id
        plugin_dir = repo / "registry" / "plugins" / entry.id
        assert plugin_dir.is_dir(), entry.id
        assert release.sha256 == tree_digest(plugin_dir), entry.id


def test_tree_digest_walks_in_posix_string_order(tmp_path):
    """The digest's walk order is the case-sensitive posix relpath
    string order on every platform. Two pathlib sort orders disagree
    with it, each on its own platform: Windows compares
    case-insensitively, walking manifest.json before README.md, and
    posix tuple-compares path parts, walking skills/ before skills.zip
    because "skills" < "skills.zip" where string order puts skills.zip
    first ('.' sorts below '/'). The mixed-case pair is the Windows
    failure this fix came from (pinned installs failing with
    install:hash-mismatch while the pins verified on posix machines);
    the skills pair keeps this test red on posix too, so CI on ubuntu
    catches a regression back to a pathlib sort, not just a Windows
    developer's local run."""
    import hashlib

    from agentdesk.registry.install import tree_digest

    plugin_dir = tmp_path / "plugin"
    (plugin_dir / "skills" / "recap").mkdir(parents=True)
    (plugin_dir / "README.md").write_text("# plugin\n", encoding="utf-8")
    (plugin_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    (plugin_dir / "skills.zip").write_text("zip\n", encoding="utf-8")
    (plugin_dir / "skills" / "recap" / "SKILL.md").write_text("x\n",
                                                             encoding="utf-8")
    # String order, which is the pin's order: README.md sorts before
    # manifest.json (a case-insensitive walk flips the pair) and
    # skills.zip sorts before skills/recap/SKILL.md (a pathlib
    # part-tuple walk visits the directory first).
    names = sorted(["README.md", "manifest.json", "skills.zip",
                    "skills/recap/SKILL.md"])
    assert names[:2] == ["README.md", "manifest.json"]
    assert names[2:] == ["skills.zip", "skills/recap/SKILL.md"]
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("utf-8") + b"\n")
        digest.update((plugin_dir / name).read_bytes())
    assert tree_digest(plugin_dir) == digest.hexdigest()


def test_empty_base_index_means_nothing_published_yet(tmp_path):
    """The workflow writes {} when the base branch has no index: that is
    the clean first-publish case, not a broken base."""
    from agentdesk.registry.ci import review_registry_changes

    registry_root = tmp_path / "registry"
    registry_root.mkdir()
    (registry_root / "index.json").write_text(
        json.dumps({"plugins": [], "schemaVersion": 1}), encoding="utf-8")
    result = review_registry_changes(registry_root, [], base_index_text="{}")
    assert result == {"ok": True, "reasons": []}
