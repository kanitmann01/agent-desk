"""Run the server-free marketplace walkthrough as a test."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "marketplace_walkthrough.py"


def test_marketplace_walkthrough_passes() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, (
        f"walkthrough exited {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "walkthrough: PASS" in completed.stdout
    for step in range(1, 16):
        assert f"{step}. " in completed.stdout, f"step {step} did not print"
