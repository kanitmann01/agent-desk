"""The side-car backend: the pinned engine CLI, one contained process per turn.

The desk drives one turn at a time by shelling out to the pinned tag's
command-line chat in its own virtual environment under the desk's data
folder (tools/install_engine_sidecar.py creates that venv; this module
only resolves and runs it). The grammar below was verified against the
pinned tag v0.23.3 on 2026-11-23: one JSON event per line on stdout,
with the event kinds `system` (its subtype says init), `text` and
`result`.

The process is contained: its home folder (where the CLI may write its
own state) is the side-car folder under the data folder, never the user
profile root, and it reads the turn on stdin-free argv so nothing
interactive is possible. The side-car is never a hard dependency: a
machine without the venv answers `available()` False and the boundary
falls back to the desk's fixed loop.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# The pinned tag the installer puts in the venv; the boundary runs
# whatever the venv holds, so this constant documents and the installer
# enforces.
PINNED_TAG = "v0.23.3"

# The side-car's folder name under the desk's data folder, and the venv
# folder inside it.
SIDECAR_DIR = "engine-sidecar"
VENV_DIR = "venv"

# One turn's ceiling in seconds. A turn is one prompt to a local or
# saved endpoint; a hung process is killed at the ceiling and the turn
# answers as failed.
DEFAULT_TIMEOUT_S = 120.0


class SidecarError(Exception):
    """The side-car turn could not run or did not answer cleanly.

    Carries the plain sentence the boundary puts in the turn result's
    note; a failed turn never raises into the pass that asked for it.
    """


@dataclass(frozen=True)
class SpawnResult:
    """One finished process: its exit code and captured output."""

    returncode: int
    stdout: str
    stderr: str


def home_dir(data_dir) -> Path:
    """The side-car's contained home folder under this data folder."""
    return Path(data_dir) / SIDECAR_DIR


def default_home() -> Path:
    """The side-car home for this machine's desk: under the data folder.

    The data folder resolves at call time (the server module owns the
    AGENTDESK_DATA rule), so the reverse import here keeps the
    dependency acyclic.
    """
    from agentdesk.server.app import default_data_dir

    return home_dir(default_data_dir())


def venv_dir(home: Path) -> Path:
    """The pinned venv folder inside one side-car home."""
    return Path(home) / VENV_DIR


def cli_path(home: Path) -> Path:
    """The pinned CLI executable inside one side-car home.

    Windows venvs put scripts in Scripts, POSIX ones in bin; the CLI
    name is the same.
    """
    scripts = "Scripts" if os.name == "nt" else "bin"
    name = "hermes.exe" if os.name == "nt" else "hermes"
    return venv_dir(home) / scripts / name


def available(home=None) -> bool:
    """Whether the side-car is installed: its pinned CLI file exists.

    The answer is read from disk every call, so an install that lands
    while the desk runs is picked up on the next turn without a
    restart.
    """
    try:
        return cli_path(home if home is not None else default_home()).is_file()
    except OSError:
        return False


def build_command(prompt: str, *, base_url: str, api_key: str, model: str,
                  cli: str) -> list[str]:
    """The one-shot turn command in the grammar the pinned tag verifies.

    Order and spelling are the verified v0.23.3 shape: a quiet one-shot
    chat, the prompt as the positional value of -q, stream-json events,
    the endpoint the desk saved, and --yolo for the unattended run. The
    prompt rides as one argv element, so no shell ever re-splits it.
    """
    return [
        str(cli), "chat", "-q", prompt, "--oneshot", "--format", "stream-json",
        "--base-url", base_url, "--api-key", api_key, "--model", model, "--yolo",
    ]


def _spawn(argv: list[str], *, cwd: Path, env: dict, timeout_s: float) -> SpawnResult:
    """Run one contained process to completion, killing it at the ceiling.

    The child reads no input and writes only what it must: stdout is the
    event stream, stderr is kept for the failure note. A process that
    outlives the timeout is killed and the turn answers as failed.
    """
    proc = subprocess.Popen(
        argv, cwd=str(cwd), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise SidecarError(
            "The engine side-car turn ran past its time limit and was stopped.") from None
    return SpawnResult(proc.returncode, stdout or "", stderr or "")


def contained_env(home: Path) -> dict:
    """The child process environment with its home pointed into the folder.

    Both spellings are set so a CLI written for either platform writes
    its own state inside the side-car folder and never touches the real
    user profile root.
    """
    env = dict(os.environ)
    home_text = str(home)
    env["HOME"] = home_text
    env["USERPROFILE"] = home_text
    return env


def run(prompt: str, *, connection, home=None, timeout_s: float = DEFAULT_TIMEOUT_S,
        spawn=None) -> tuple[dict, ...]:
    """Run one turn in the side-car and return its event stream.

    `connection` is the boundary's ConnectionSpec (base URL, key, model)
    for the endpoint the desk saved. A non-zero exit or an empty stream
    raises SidecarError with the cause; the boundary turns that into a
    failed turn, never a crash.
    """
    home = home if home is not None else default_home()
    cli = cli_path(home)
    argv = build_command(
        prompt, base_url=connection.base_url, api_key=connection.api_key,
        model=connection.model, cli=str(cli))
    runner = spawn if spawn is not None else _spawn
    result = runner(argv, cwd=Path(home), env=contained_env(home),
                    timeout_s=timeout_s)
    events = parse_events(result.stdout)
    if result.returncode != 0:
        cause = (result.stderr or "").strip().splitlines()
        detail = cause[-1][:200] if cause else f"exit code {result.returncode}"
        raise SidecarError(f"The engine side-car turn failed: {detail}")
    if not events:
        raise SidecarError("The engine side-car answered with no events.")
    return events


def parse_events(text: str) -> tuple[dict, ...]:
    """Parse the stream: one JSON event object per line.

    Blank lines are skipped. A line this build cannot read becomes one
    event of kind "unreadable" carrying the line's opening, so a grammar
    drift is visible in the event kinds instead of silently dropped.
    """
    events: list[dict] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except ValueError:
            events.append({"type": "unreadable", "line": stripped[:120]})
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            events.append({"type": "unreadable", "line": stripped[:120]})
    return tuple(events)


def event_kinds(events) -> tuple[str, ...]:
    """The kind of each event, in stream order: what the smoke prints."""
    return tuple(str(event.get("type") or "") for event in events)
