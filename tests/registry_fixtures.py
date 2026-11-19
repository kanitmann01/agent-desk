"""Registry fixtures: a real git repository with tagged plugin releases.

The registry is a git repository whose root index.json lists plugins with
releases pinned by sha256 (over the plugin tree bytes) and git tags. These
helpers build one deterministically for the public-API tests. Importing
this module also makes the src/ package importable, like a conftest.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_src = REPO_ROOT / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# The fixture pins are made by the production walk in registry/install,
# never by a copy of it: a copied walk that drifted (as the pathlib
# object sort once did on Windows) would pin digests the installer
# refuses, red only on the machines that disagree with the copy.
from agentdesk.registry.install import tree_digest  # noqa: E402,F401

FIXTURES = Path(__file__).resolve().parent
PLUGIN_FIXTURE = FIXTURES / "fixtures" / "registry" / "plugins" / "sales-delta-widget"

REGISTRY_INDEX = {
    "schemaVersion": 1,
    "plugins": [
        {
            "id": "sales-delta-widget",
            "publisher": "acme-tools",
            "latest": "1.2.0",
            "risk": "low",
            "class": "declarative",
            "releases": [
                {"version": "1.2.0", "sha256": None, "tag": "sales-delta-widget-1.2.0",
                 "yanked": False},
            ],
        }
    ],
}


def git(repo: Path, *args: str, env_dates: dict | None = None) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env.update(env_dates or {})
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, env=env,
    )


def make_registry(tmp_path: Path, *, sha256: str | None = None) -> Path:
    """A git registry with one tagged, indexed plugin release.

    The registry pins its own line endings and disables autocrlf locally:
    hash pinning is byte-exact, and a CRLF archive would break every pin.
    Production registries carry the same .gitattributes.
    """
    repo = tmp_path / "registry"
    (repo / "plugins" / "sales-delta-widget").mkdir(parents=True)
    for item in PLUGIN_FIXTURE.rglob("*"):
        if item.is_file():
            target = repo / "plugins" / "sales-delta-widget" / item.relative_to(PLUGIN_FIXTURE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "core.autocrlf", "false")
    (repo / ".gitattributes").write_text(
        "* text=auto\n*.json text eol=lf\n*.lock text eol=lf\n"
        "*.md text eol=lf\n*.py text eol=lf\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "plugin",
        env_dates={"GIT_AUTHOR_DATE": "2026-11-11T09:00:00 +0000",
                   "GIT_COMMITTER_DATE": "2026-11-11T09:00:00 +0000"})
    digest = sha256 or tree_digest(repo / "plugins" / "sales-delta-widget")
    index = json.loads(json.dumps(REGISTRY_INDEX))
    index["plugins"][0]["releases"][0]["sha256"] = digest
    (repo / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "index",
        env_dates={"GIT_AUTHOR_DATE": "2026-11-11T09:01:00 +0000",
                   "GIT_COMMITTER_DATE": "2026-11-11T09:01:00 +0000"})
    git(repo, "tag", "sales-delta-widget-1.2.0")
    return repo
