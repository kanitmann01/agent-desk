"""The registry index: round-trip, schema, and the CLI list view (ticket #10).

The index lists plugins with id, publisher, latest, risk, class and
releases pinned by sha256 and git tag. Loading is total: a malformed
index raises with a named reason, never a stack trace.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from .registry_fixtures import REGISTRY_INDEX, make_registry

REPO = Path(__file__).resolve().parent.parent


def run_registry_cli(*args: str) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "agentdesk.registry", *args],
        capture_output=True, text=True, env=env,
    )


def test_index_round_trips(tmp_path):
    repo = make_registry(tmp_path)
    raw = (repo / "index.json").read_text(encoding="utf-8")
    from agentdesk.registry.index import load_index
    index = load_index(raw)
    assert index.plugins[0].id == "sales-delta-widget"
    assert index.plugins[0].publisher == "acme-tools"
    assert index.plugins[0].latest == "1.2.0"
    assert index.plugins[0].risk == "low"
    assert index.plugins[0].class_ == "declarative"
    assert index.plugins[0].releases[0].sha256
    assert index.plugins[0].releases[0].tag == "sales-delta-widget-1.2.0"
    # The model normalises v1 into v2 in memory; ids and releases survive.
    serialized = json.loads(index.to_json())
    assert serialized["schemaVersion"] == 2
    assert [plugin["id"] for plugin in serialized["plugins"]] == ["sales-delta-widget"]
    release = serialized["plugins"][0]["releases"][0]
    assert release["version"] == "1.2.0"
    assert release["sha256"] == index.plugins[0].releases[0].sha256
    assert release["tag"] == "sales-delta-widget-1.2.0"


def test_malformed_index_raises_named_reason(tmp_path):
    from agentdesk.registry.index import RegistryIndexError, load_index
    with pytest.raises(RegistryIndexError, match="schemaVersion"):
        load_index(json.dumps({"plugins": []}))
    with pytest.raises(RegistryIndexError):
        load_index("not json at all")


def test_cli_list_shows_metadata(tmp_path):
    repo = make_registry(tmp_path)
    r = run_registry_cli("list", "--registry", str(repo))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sales-delta-widget" in r.stdout
    assert "acme-tools" in r.stdout
    assert "1.2.0" in r.stdout
    assert "declarative" in r.stdout
