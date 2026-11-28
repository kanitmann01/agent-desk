"""The old import path resolves to the same module objects (032-8).

Spec 032 ticket 08 (issue 362, stories 28 to 30). The alias package
src/agentdesk must hand back the canonical nexuusbot module objects,
never copies: `import agentdesk` and every `agentdesk.*` submodule are
the same objects `nexuusbot` and `nexuusbot.*` are. Identity is proved
in three ways here:

1. In clean subprocesses over src/, in both import orders.
2. In an installed distribution: the test builds and installs the
   project into a temporary virtual environment (pip, --no-deps, no
   network), imports both paths there and asserts the objects match and
   the generated distribution metadata names nexuus-bot.
3. A reading check: no live document or declared distribution name
   promises the old distribution name as an install alias; the
   compatibility promise is the old import path only.

No desk, no walk and no application starts here; the installed
environment is temporary and is removed.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Submodules whose import chains stay inside the standard library, so
# the --no-deps temporary install can import them: config, briefs
# (through calendar.store), plugins.vocabulary, layout and locking.
IDENTITY_MODULES = (
    "config",
    "briefs",
    "plugins.vocabulary",
    "layout",
    "locking",
)

# The identity probe one interpreter runs: import both paths, assert
# object identity, and report as JSON the parent can compare.
_IDENTITY_SCRIPT = """\
import json, sys

modules = sys.argv[1].split(",")
report = {"sys": {"nexuusbot": "nexuusbot" in sys.modules,
                  "agentdesk": "agentdesk" in sys.modules},
          "top": None, "modules": {}}
import nexuusbot
import agentdesk
report["top"] = agentdesk is nexuusbot
report["sys"] = {"nexuusbot": "nexuusbot" in sys.modules,
                 "agentdesk": "agentdesk" in sys.modules}
for name in modules:
    canonical = __import__("nexuusbot." + name, fromlist=["x"])
    alias = __import__("agentdesk." + name, fromlist=["x"])
    report["modules"][name] = {
        "same_object": alias is canonical,
        "same_sys_module": (
            sys.modules["agentdesk." + name]
            is sys.modules["nexuusbot." + name]),
    }
print(json.dumps(report))
"""

# The reverse order: the alias submodule imports first.
_IDENTITY_SCRIPT_ALIAS_FIRST = """\
import json, sys

modules = sys.argv[1].split(",")
report = {"modules": {}}
import agentdesk
import nexuusbot
report["top"] = agentdesk is nexuusbot
for name in modules:
    alias = __import__("agentdesk." + name, fromlist=["x"])
    canonical = __import__("nexuusbot." + name, fromlist=["x"])
    report["modules"][name] = {
        "same_object": alias is canonical,
        "same_sys_module": (
            sys.modules["agentdesk." + name]
            is sys.modules["nexuusbot." + name]),
    }
print(json.dumps(report))
"""


def _run_interpreter(interpreter, script, modules):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    proc = subprocess.run(
        [str(interpreter), "-c", script, ",".join(modules)],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_alias_imports_return_the_canonical_module_objects():
    """In a clean interpreter the alias is the canonical package itself."""
    report = _run_interpreter(sys.executable, _IDENTITY_SCRIPT,
                              IDENTITY_MODULES)
    assert report["top"] is True
    assert report["sys"] == {"nexuusbot": True, "agentdesk": True}
    for name, outcome in report["modules"].items():
        assert outcome == {"same_object": True, "same_sys_module": True}, name


def test_alias_first_import_order_keeps_identity():
    """The same holds when the alias submodule imports first."""
    report = _run_interpreter(sys.executable, _IDENTITY_SCRIPT_ALIAS_FIRST,
                              IDENTITY_MODULES)
    assert report["top"] is True
    for name, outcome in report["modules"].items():
        assert outcome == {"same_object": True, "same_sys_module": True}, name


def test_an_unknown_alias_submodule_is_the_canonical_import_error():
    """A name the canonical package does not have stays a clean miss."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    proc = subprocess.run(
        [sys.executable, "-c", "import agentdesk.no_such_module"],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    assert proc.returncode != 0
    assert "No module named 'agentdesk.no_such_module'" in proc.stderr


# --- spec names and reload (the P2 fix pinned by the PR 389 review) ---
#
# The pinned semantics, chosen as the smallest coherent whole:
#
# - The alias import's spec (what the finder hands the machinery for an
#   agentdesk.X import) is a CLONE named agentdesk.X that shares the
#   canonical module's loader and origin. The canonical module's own
#   __spec__ is never mutated.
# - The one shared module object carries the canonical __spec__, so
#   its __spec__.name reads the canonical name; that is what makes
#   both reload spellings (importlib.reload(nexuusbot.X) and
#   importlib.reload(agentdesk.X)) re-find the canonical spec and
#   re-execute the real module through the canonical loader, instead
#   of silently routing through the alias. A module object has one
#   __spec__, so the shared object reading canonical is the choice
#   that keeps reload real; the alias name keeps its own spec only at
#   the finder level (find_spec on an alias submodule that is not yet
#   in sys.modules returns the clone; once imported, it returns the
#   shared canonical spec, exactly as for any imported module).
# - Reload re-executes in place: the object identity between the two
#   names holds before and after, and a name the module source
#   assigns (its `import os` binding) is restored by the fresh
#   execution, which is the observable marker that the code re-ran.

_SPEC_SCRIPT = """\
import importlib.util, json, sys

order, modules_arg = sys.argv[1], sys.argv[2]
modules = modules_arg.split(",")
report = {"order": order, "alias_clone_names": {}, "modules": {}}
import nexuusbot
import agentdesk
# The finder-level alias specs, probed before any agentdesk.X submodule
# is imported: one clone per alias name, named for the alias.
for name in modules:
    report["alias_clone_names"][name] = importlib.util.find_spec(
        "agentdesk." + name).name
if order == "alias_first":
    import agentdesk
    import nexuusbot
else:
    import nexuusbot
    import agentdesk
for name in modules:
    canonical = __import__("nexuusbot." + name, fromlist=["x"])
    alias = __import__("agentdesk." + name, fromlist=["x"])
    report["modules"][name] = {
        "same_object": alias is canonical,
        "shared_spec_name": canonical.__spec__.name,
        "find_canonical_name": importlib.util.find_spec(
            "nexuusbot." + name).name,
    }
print(json.dumps(report))
"""

_RELOAD_SCRIPT = """\
import importlib, json, os, sys

order = sys.argv[1]
if order == "alias_first":
    import agentdesk.config as alias_view
    canonical = importlib.import_module("nexuusbot.config")
else:
    import nexuusbot.config as canonical
    alias_view = importlib.import_module("agentdesk.config")
report = {"order": order}
report["import_identity"] = alias_view is canonical
shared = sys.modules["nexuusbot.config"]
# A name the module source assigns: `import os` rebinds it when the
# code re-executes, so a planted canary is the execution marker.
shared.os = "CANARY"
importlib.reload(canonical)
report["reexecuted"] = shared.os is not "CANARY" and shared.os is os
report["reload_identity"] = sys.modules["agentdesk.config"] is shared \
    and sys.modules["nexuusbot.config"] is shared
report["spec_name_after_reload"] = shared.__spec__.name
print(json.dumps(report))
"""


def _run_script(script, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    proc = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("order", ["canonical_first", "alias_first"])
def test_specs_stay_named_for_their_own_paths_in_both_import_orders(order):
    """The canonical spec is never mutated; the alias import uses a clone.

    In both orders: the finder-level spec for every probed alias
    submodule is a clone named agentdesk.X; after the imports, the
    shared module's __spec__.name and find_spec("nexuusbot.X").name
    read the canonical name; and the identity contract still holds.
    """
    report = _run_script(_SPEC_SCRIPT, order, ",".join(IDENTITY_MODULES))
    assert report["order"] == order
    for name, clone_name in report["alias_clone_names"].items():
        assert clone_name == "agentdesk." + name, name
    for name, outcome in report["modules"].items():
        assert outcome["same_object"] is True, name
        assert outcome["shared_spec_name"] == "nexuusbot." + name, name
        assert outcome["find_canonical_name"] == "nexuusbot." + name, name


@pytest.mark.parametrize("order", ["canonical_first", "alias_first"])
def test_reload_of_the_canonical_name_reexecutes_after_an_alias_import(
        order):
    """Reload after an alias import re-executes the real module.

    importlib.reload(nexuusbot.config) re-runs the module source (the
    planted canary is restored by the fresh execution), the module
    object stays the same under both names, and the shared __spec__
    still reads the canonical name afterwards.
    """
    report = _run_script(_RELOAD_SCRIPT, order)
    assert report["import_identity"] is True
    assert report["reexecuted"] is True, report
    assert report["reload_identity"] is True
    assert report["spec_name_after_reload"] == "nexuusbot.config"


def _installed_interpreter(tmp_path: Path) -> Path:
    """Build and install the distribution into a temporary environment.

    The venv sees the base interpreter's site-packages so setuptools can
    build without network access; the project itself installs --no-deps
    into the venv's own site-packages, which shadow the base for the
    nexuusbot and agentdesk names. Runtime dependencies (cryptography,
    keyring) are deliberately absent: the identity probes only touch
    standard-library import chains.
    """
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True, system_site_packages=True)
    interpreter = env_dir / "Scripts" / "python.exe" if os.name == "nt" \
        else env_dir / "bin" / "python"
    proc = subprocess.run(
        [str(interpreter), "-m", "pip", "install", "--quiet",
         "--disable-pip-version-check", "--no-deps", "--no-build-isolation",
         str(ROOT)],
        capture_output=True, text=True, env=dict(os.environ),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return interpreter


def test_the_installed_distribution_shares_module_objects_and_metadata(
        tmp_path):
    """Install nexuus-bot, then prove identity and metadata in that env.

    The distribution metadata is read through importlib.metadata from
    the installed wheel the pip build produced: it names nexuus-bot
    because the build regenerates it from pyproject.toml, never because
    a committed file was hand-edited.
    """
    interpreter = _installed_interpreter(tmp_path)
    report = _run_interpreter(interpreter, _IDENTITY_SCRIPT,
                              IDENTITY_MODULES)
    assert report["top"] is True
    assert report["sys"] == {"nexuusbot": True, "agentdesk": True}
    for name, outcome in report["modules"].items():
        assert outcome == {"same_object": True, "same_sys_module": True}, name

    metadata = subprocess.run(
        [str(interpreter), "-c",
         "import importlib.metadata, json;"
         " print(json.dumps({'name': importlib.metadata.metadata("
         "'nexuus-bot')['Name'],"
         "'version': importlib.metadata.version('nexuus-bot')}))"],
        capture_output=True, text=True, env=dict(os.environ),
    )
    assert metadata.returncode == 0, metadata.stderr
    document = json.loads(metadata.stdout.strip())
    assert document == {"name": "nexuus-bot", "version": "0.1.0"}


# --- no document promises the old distribution name as an install alias ---


def _live_documents():
    """The live documents the naming inventory scans, as repo paths.

    The same scope the naming guard reads: its roots and named files.
    Dated archives, legal instruments and notice files are excluded by
    the contract's own exclusion list before this reads anything.
    """
    import fnmatch

    inventory = json.loads(
        (ROOT / "tools" / "naming" / "inventory.json").read_text(
            encoding="utf-8"))
    exclusions = json.loads(
        (ROOT / "tools" / "naming" / "exclusions.json").read_text(
            encoding="utf-8"))
    scan = inventory["scan"]
    roots = tuple(Path(r) for r in scan["roots"])
    named = {Path(f) for f in scan["files"]}
    skip = tuple(Path(s) for s in scan.get("skip", ()))
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, text=True).stdout
    paths = [Path(p) for p in tracked.split("\0") if p]
    for path in paths:
        if path in named:
            pass
        elif any(path == s or s in path.parents for s in skip):
            continue
        elif not any(tree in path.parents for tree in roots):
            continue
        if any(fnmatch.fnmatch(path.as_posix(), pattern)
               for entry in exclusions["entries"]
               for pattern in entry["paths"]):
            continue
        if path.suffix in {".md", ".txt", ".json", ".toml", ".yml",
                           ".yaml", ".html", ".py", ".cmd", ".command",
                           ".ts"} or path.name in {".gitignore",
                                                   ".gitattributes"}:
            yield path


def test_no_document_promises_the_old_distribution_as_an_install_alias():
    """The compatibility promise is the old import path, nothing else.

    No live document may instruct anyone to install the old
    distribution name (`pip install agent-desk` and every other
    `install agent-desk` instruction), and the declared distribution
    name is nexuus-bot. Documents that name the old import path or the
    retained launcher filenames are untouched by this rule.
    """
    pattern = re.compile(r"(?<!un)install\s+(?:-\S+\s+)*agent-desk\b",
                         re.IGNORECASE)
    offenders = []
    for path in _live_documents():
        text = path.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            offenders.append(path.as_posix())
    assert offenders == [], (
        "live documents promise the old distribution name as an install "
        f"alias: {offenders}"
    )
    declared = None
    for line in (ROOT / "pyproject.toml").read_text(
            encoding="utf-8").splitlines():
        match = re.match(r'^name\s*=\s*"([^"]+)"', line)
        if match:
            declared = match.group(1)
            break
    assert declared == "nexuus-bot", (
        "pyproject.toml must declare the nexuus-bot distribution"
    )
