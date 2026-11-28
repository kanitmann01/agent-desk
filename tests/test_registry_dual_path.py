"""Registry plugins pass through both host paths in clean interpreters.

Spec 032 ticket 08 (issue 362, story 30; testing decision 8). One clean
interpreter imports the host through nexuusbot, another through the
agentdesk alias. In each, every plugin in the committed registry is
validated, installed and rendered, and an import fixture reads a public
host module through that path. Both runs print a JSON document and the
two documents must be equal.

The subprocesses stop at the public seams (validator, plugin runtime,
sample renderer): no desk, no walk, no application, no browser, no
office application. The template plugin contributes no widget, so its
render leg goes through the marketplace's own honest-null seam, the
same one the plugin detail page uses.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
REGISTRY = ROOT / "registry"

# The probe one interpreter runs, parameterised by host module name.
_DUAL_SCRIPT = """\
import importlib, json, os, sys
from pathlib import Path

host_name = os.environ["DUAL_HOST"]
registry = Path(os.environ["DUAL_REGISTRY"])
plugins_dir = Path(os.environ["DUAL_PLUGINS"])
data_dir = Path(os.environ["DUAL_DATA"])
workspace_dir = Path(os.environ["DUAL_WORKSPACE"])

host = importlib.import_module(host_name)
validator_core = importlib.import_module(host_name + ".validator.core")
plugin_runtime = importlib.import_module(host_name + ".plugins.runtime")
plugin_render = importlib.import_module(host_name + ".plugins.render")
plugin_vocabulary = importlib.import_module(host_name + ".plugins.vocabulary")

validate_plugin = validator_core.validate_plugin
runtime = plugin_runtime.PluginRuntime(
    plugins_dir=plugins_dir,
    data_dir=data_dir,
    workspace_dir=workspace_dir,
    now="2026-11-28T00:00:00",
)
render_sample = plugin_render.render_sample

plugins = {}
for plugin_dir in sorted(registry.joinpath("plugins").iterdir()):
    if not plugin_dir.is_dir():
        continue
    verdict = validate_plugin(plugin_dir)
    installed = runtime.install(plugin_dir, source="registry")
    record = runtime.record(installed["id"])
    try:
        rendered = render_sample(plugin_dir)
    except plugin_render.PluginRenderError:
        rendered = None
    plugins[plugin_dir.name] = {
        "validated": verdict.ok,
        "failures": [failure.code for failure in verdict.failures],
        "installed": {
            "ok": installed.get("ok"),
            "id": installed.get("id"),
            "version": installed.get("version"),
            "pilot": installed.get("pilot"),
        },
        "state": record.get("state"),
        "active_version": record.get("active_version"),
        "rendered": rendered,
    }

report = {
    "host": host_name,
    "import_fixture": {
        # A public host module read through this path must return the
        # same value the other path returns.
        "element_kinds": list(plugin_vocabulary.ELEMENT_KINDS),
        "product_name": host.PRODUCT_NAME,
    },
    "modules": {
        "host_imported": host_name in sys.modules,
        "canonical_imported": "nexuusbot" in sys.modules,
        "alias_imported": "agentdesk" in sys.modules,
    },
    "plugins": plugins,
}
print(json.dumps(report, sort_keys=True))
"""


def _run_path(host_name: str, tmp_path: Path) -> dict:
    """One clean interpreter exercising the registry through host_name."""
    env = dict(os.environ)
    parts = [part for part in env.get("PYTHONPATH", "").split(os.pathsep)
             if part]
    if str(SRC) not in parts:
        parts.insert(0, str(SRC))
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["DUAL_HOST"] = host_name
    env["DUAL_REGISTRY"] = str(REGISTRY)
    env["DUAL_PLUGINS"] = str(tmp_path / "plugins")
    env["DUAL_DATA"] = str(tmp_path / "data")
    env["DUAL_WORKSPACE"] = str(tmp_path / "workspace")
    proc = subprocess.run(
        [sys.executable, "-c", _DUAL_SCRIPT],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_registry_plugins_pass_through_both_host_paths(tmp_path):
    """Both runs install, validate and render the same results."""
    canonical = _run_path("nexuusbot", tmp_path / "canonical")
    alias = _run_path("agentdesk", tmp_path / "alias")

    # Each interpreter really took its own path: the canonical run never
    # imported the alias, the alias run imported both (one object each).
    assert canonical["modules"] == {
        "host_imported": True, "canonical_imported": True,
        "alias_imported": False,
    }
    assert alias["modules"] == {
        "host_imported": True, "canonical_imported": True,
        "alias_imported": True,
    }
    # The import fixture returns the same value through each path.
    assert canonical["import_fixture"] == alias["import_fixture"]
    # Every registry plugin validated, installed and rendered the same.
    assert canonical["plugins"] == alias["plugins"]
    assert canonical["plugins"], "the committed registry is empty"
    for name, outcome in canonical["plugins"].items():
        assert outcome["validated"] is True, (name, outcome["failures"])
        assert outcome["installed"]["ok"] is True, name
        assert outcome["state"] == "enabled", name
