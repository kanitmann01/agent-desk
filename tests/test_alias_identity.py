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
