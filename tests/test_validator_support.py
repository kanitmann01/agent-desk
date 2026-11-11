"""Shared support for the validator tests.

Importing this module first puts the src layout on sys.path so the tests
can import ``agentdesk.validator`` without installing the package. It also
provides helpers that run the validator CLI in a subprocess.
"""

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
