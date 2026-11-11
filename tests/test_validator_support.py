"""Shared support for the validator tests.

Importing this module first puts the src layout on sys.path so the tests
can import ``agentdesk.validator`` without installing the package. It also
provides helpers that run the validator CLI in a subprocess.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
SRC_DIR = REPO_ROOT / "src"
FIXTURES_DIR = TESTS_DIR / "fixtures" / "validator"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


VALID_MANIFEST = json.loads(
    (FIXTURES_DIR / "valid-manifest" / "manifest.json").read_text(encoding="utf-8")
)
VALID_UI_SCHEMA = json.loads(
    (FIXTURES_DIR / "valid-manifest" / "widget.ui.json").read_text(encoding="utf-8")
)


def write_plugin(dest: Path, manifest=None, files: dict | None = None) -> Path:
    """Write a plugin directory that passes validation, then apply overrides.

    ``manifest`` replaces manifest.json entirely; ``files`` maps relative
    paths to text contents added on top of the default files.
    """
    dest.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(
        VALID_MANIFEST if manifest is None else manifest, indent=2
    )
    (dest / "manifest.json").write_text(manifest_text, encoding="utf-8")
    (dest / "widget.ui.json").write_text(
        json.dumps(VALID_UI_SCHEMA, indent=2), encoding="utf-8"
    )
    skills = dest / "skills" / "sales-summary"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "SKILL.md").write_text("# sales summary\n", encoding="utf-8")
    for relpath, text in (files or {}).items():
        target = dest / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return dest


def cli_env() -> dict:
    """Environment for CLI subprocesses that can import agentdesk."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if str(SRC_DIR) not in parts:
        parts.insert(0, str(SRC_DIR))
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run ``python -m agentdesk.validator`` with the given arguments."""
    return subprocess.run(
        [sys.executable, "-m", "agentdesk.validator", *args],
        capture_output=True,
        text=True,
        env=cli_env(),
        cwd=str(REPO_ROOT),
    )


def fixture(name: str) -> Path:
    """Path to a fixture plugin directory under tests/fixtures/validator."""
    return FIXTURES_DIR / name
