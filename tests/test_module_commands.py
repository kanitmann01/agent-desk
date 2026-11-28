"""The old module commands keep working through the alias (032-8).

Spec 032 ticket 08 (issue 362, story 29). All five retained commands
run with --help in isolated subprocesses and print their existing
parser names, and the canonical module commands exist beside them.
Each subprocess stops at argument parsing: no server, probe, registry
write, validation run or deck is ever started here.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# (module, the existing parser name its --help prints)
OLD_COMMANDS = (
    ("agentdesk.server", "python -m agentdesk.server"),
    ("agentdesk.probe", "agentdesk.probe"),
    ("agentdesk.presentations.cli", "agentdesk.presentations"),
    ("agentdesk.registry", "agentdesk.registry"),
    ("agentdesk.validator", "agentdesk-validator"),
)

CANONICAL_COMMANDS = (
    "nexuusbot.server",
    "nexuusbot.probe",
    "nexuusbot.presentations.cli",
    "nexuusbot.registry",
    "nexuusbot.validator",
)


def run_module(module: str, *flags: str) -> subprocess.CompletedProcess:
    """Run `python -m <module>` over src/ in an isolated subprocess."""
    env = dict(os.environ)
    parts = [part for part in env.get("PYTHONPATH", "").split(os.pathsep)
             if part]
    if str(SRC) not in parts:
        parts.insert(0, str(SRC))
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return subprocess.run(
        [sys.executable, "-m", module, *flags],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )


@pytest.mark.parametrize("module,parser_name", OLD_COMMANDS)
def test_the_old_module_commands_print_their_existing_parser_names(
        module, parser_name):
    """Every retained command answers --help with its existing name."""
    proc = run_module(module, "--help")
    assert proc.returncode == 0, proc.stderr
    assert parser_name in proc.stdout, proc.stdout[:400]


@pytest.mark.parametrize("module", CANONICAL_COMMANDS)
def test_the_canonical_module_commands_exist_beside_them(module):
    """The canonical spelling answers --help the same way."""
    proc = run_module(module, "--help")
    assert proc.returncode == 0, proc.stderr
    assert "--help" not in proc.stderr
