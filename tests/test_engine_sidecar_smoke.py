"""The side-car smoke's honest absence path (spec 023, ticket 023-3).

The smoke itself is opt-in evidence a person runs on a machine with the
side-car installed; no test ever starts the real side-car. What the
suite can pin hermetically is the refusal: on a machine without the
pinned venv the tool says so, names the installer, and exits non-zero
without running a turn or touching a real data folder.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "engine_sidecar_check.py"


def _minimal_env() -> dict[str, str]:
    """The pinned environment a subprocess needs, with the desk unconfigured."""
    needed = ("SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOMEDRIVE",
              "HOMEPATH", "USERPROFILE", "LOCALAPPDATA")
    env = {name: os.environ[name] for name in needed if name in os.environ}
    env["AGENTDESK_DATA"] = ""
    return env


def test_the_smoke_names_the_refusal_without_the_sidecar():
    """No installed venv: the tool refuses by name and points at the installer."""
    with tempfile.TemporaryDirectory(prefix="agentdesk-smoke-absent-") as folder:
        result = subprocess.run(
            [sys.executable, str(TOOL), "--home", folder],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
            env=_minimal_env(),
        )
        output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "no side-car is installed" in output
    assert "install_engine_sidecar.py" in output
    assert "PASS" not in output
