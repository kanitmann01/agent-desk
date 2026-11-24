"""Install the engine side-car: the pinned tag in its own venv (spec 023).

The desk's engine runs one turn at a time by shelling out to the pinned
engine CLI. The CLI lives in its own virtual environment under the
desk's data folder, so the desk's own Python environment and the user
profile root are never touched; the side-car's home folder is the same
folder, and the turn points the process's home there. This script is
the documented path a technical owner runs once on a dev machine
(which is where the POC draws the line); it is never part of a user
path, and the desk behaves exactly as before without it.

    python tools/install_engine_sidecar.py

The tag is pinned (v0.23.3, the grammar's verification point). The
engine ships no wheel, so the venv installs editable from a clone at
the tag: clone shallow, create the venv with the running interpreter,
pip install -e, then print the CLI path the desk resolves. The
installer verifies the clone's HEAD against the tag's commit and
writes an install marker (the tag and commit) beside the venv, which
`available()` and the smoke read: a checkout at another commit is
refused rather than run. Re-running is safe: an existing venv is left
alone unless --force asks for a rebuild.

Stdlib only, loopback nothing: the clone reaches the network once, on
purpose, and every other byte stays under the side-car folder.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

PINNED_TAG = "v0.23.3"
UPSTREAM = "https://github.com/NousResearch/hermes-agent.git"


def default_data_dir() -> Path:
    """The desk's data folder this install lives under."""
    override = os.environ.get("AGENTDESK_DATA")
    if override:
        return Path(override)
    return Path(Path.home(), ".agent-desk")


def venv_python(venv: Path) -> Path:
    """The venv's interpreter, Windows spelling included."""
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _git(clone: Path, *args: str) -> str:
    """One git answer inside the clone, or '' when git cannot answer."""
    proc = subprocess.run(
        ["git", "-C", str(clone), *args],
        capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _verify_checkout(clone: Path, tag: str) -> str:
    """The clone's HEAD when it matches the tag's commit, '' otherwise.

    A checkout at another commit is not the pinned grammar the desk was
    verified against; it is refused rather than run. The tag must be
    resolvable in the clone (a failed fetch or a foreign checkout leaves
    it unresolvable), which is why the message names both.
    """
    head = _git(clone, "rev-parse", "HEAD")
    tagged = _git(clone, "rev-parse", f"{tag}^{{commit}}")
    if not head or not tagged or head != tagged:
        return ""
    return head


def main() -> int:
    """Create the side-car home, venv and pinned clone; print the CLI path."""
    parser = argparse.ArgumentParser(
        description="Install the desk engine's pinned side-car venv")
    parser.add_argument("--data-dir", default=str(default_data_dir()),
                        help="the desk's data folder (default: AGENTDESK_DATA or ~/.agent-desk)")
    parser.add_argument("--tag", default=PINNED_TAG,
                        help=f"the tag to pin (default: {PINNED_TAG})")
    parser.add_argument("--force", action="store_true",
                        help="remove an existing venv and clone first")
    args = parser.parse_args()

    from agentdesk.engine import cli_path, home_for, venv_path, write_marker

    home = home_for(args.data_dir)
    venv = venv_path(home)
    clone = home / "src"
    home.mkdir(parents=True, exist_ok=True)
    if args.force:
        _remove(venv)
        _remove(clone)
    if not venv_python(venv).is_file():
        print(f"creating the venv at {venv}", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    if not (clone / ".git").exists():
        print(f"cloning {args.tag} into {clone}", flush=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", args.tag, UPSTREAM,
             str(clone)],
            check=True)
    commit = _verify_checkout(clone, args.tag)
    if not commit:
        print(f"the checkout at {clone} is not {args.tag}: "
              f"HEAD is {_git(clone, 'rev-parse', 'HEAD') or 'unreadable'} and the tag's "
              f"commit is {_git(clone, 'rev-parse', args.tag + '^{commit}') or 'unreadable'}. "
              "Re-run with --force to rebuild it.", flush=True)
        return 1
    print("installing (editable) into the venv", flush=True)
    subprocess.run(
        [str(venv_python(venv)), "-m", "pip", "install", "-e", str(clone)],
        check=True)
    cli = cli_path(home)
    if not cli.is_file():
        print(f"the install finished but no CLI is at {cli}; check the clone",
              flush=True)
        return 1
    write_marker(home, tag=args.tag, commit=commit)
    print(f"the side-car is installed: {cli}", flush=True)
    print(f"install marker: {home / 'install.json'} ({args.tag} {commit[:12]})",
          flush=True)
    print("the desk picks it up on its next engine turn; nothing to restart.",
          flush=True)
    return 0


def _remove(folder: Path) -> None:
    """Delete a folder for real, ignoring one that is not there."""
    import shutil

    shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
