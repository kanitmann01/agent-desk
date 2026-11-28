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
profile root; it reads the turn from argv (the CLI has no stdin prompt
mode), runs the zero-tool `safe` toolset with the user's own MCP and
tool configuration ignored, and receives the endpoint key in its
environment, never on the command line. The key is redacted from every
sentence this module builds. Output is capped so a runaway process
cannot consume the desk's memory: stdout 2 MiB, stderr 64 KiB, after
which the process tree is killed and the turn answers as failed.

The side-car is never a hard dependency: a machine without the venv (or
without a matching install marker) answers `available()` False and the
boundary's caller falls back to the desk's fixed loop.

One residual is named rather than hidden: the running child is held by
the turn that started it, not by the loop's stop path. A turn that is
still running when the desk shuts down is killed at its own ceiling,
and a desk process killed outright (no shutdown path) can leave its
child until that child exits. That is the local single-user POC's
accepted visibility window, the same reason the prompt rides argv.
"""

import json
import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

# The pinned tag the installer puts in the venv; the boundary runs
# whatever the venv holds, so this constant documents and the installer
# enforces. An install marker records the tag and commit the installer
# wrote; a marker for another tag is not this build's side-car.
PINNED_TAG = "v0.23.3"

# The side-car's folder name under the desk's data folder, and the venv
# folder inside it.
SIDECAR_DIR = "engine-sidecar"
VENV_DIR = "venv"
MARKER_NAME = "install.json"

# One turn's ceiling in seconds. A turn is one prompt to a local or
# saved endpoint; a hung process is killed at the ceiling and the turn
# answers as failed.
DEFAULT_TIMEOUT_S = 120.0

# How long a killed process tree gets to go away before the turn answers
# anyway. A grandchild that ignores termination must not hang the loop.
KILL_WAIT_S = 5.0

# The most output one turn may produce. The event stream is small JSON
# lines; anything above these caps is a runaway process, not a reply.
STDOUT_MAX_BYTES = 2 * 1024 * 1024
STDERR_MAX_BYTES = 64 * 1024
READ_CHUNK_BYTES = 8192

# The environment names the child inherits: the OS plumbing it needs to
# start, and nothing about this machine's desk, keys or user profile.
ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT")

# The home-relative variables the child gets, so everything it writes
# lands under the side-car's own folder. HERMES_HOME is the pinned
# CLI's explicit home: without it the CLI finds a gateway service from
# the real user profile and refuses the turn as another home's.
HOME_ENV = {
    "HOME": "",
    "USERPROFILE": "",
    "HERMES_HOME": "hermes-home",
    "APPDATA": "appdata",
    "LOCALAPPDATA": "appdata",
    "XDG_CONFIG_HOME": "config",
    "XDG_CACHE_HOME": "cache",
    "XDG_STATE_HOME": "state",
    "TMP": "tmp",
    "TEMP": "tmp",
}

# The key's environment variable: the OpenAI-compatible spelling the
# pinned CLI reads for a custom base URL.
KEY_ENV = "OPENAI_API_KEY"


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
    from nexuusbot.server.app import default_data_dir

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


def marker_path(home: Path) -> Path:
    """The install marker the installer writes beside the venv."""
    return Path(home) / MARKER_NAME


def read_marker(home: Path) -> dict | None:
    """The install marker as a dict, or None when there is none readable.

    A marker is evidence, not the CLI: an unreadable or malformed file
    reads as no marker rather than as a crash, and a hand-built venv
    without one is still a runnable side-car (the CLI file decides).
    """
    try:
        data = json.loads(marker_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_marker(home: Path, *, tag: str, commit: str) -> None:
    """Write the install marker: the tag and commit the installer pinned."""
    path = marker_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tag": tag, "commit": commit},
                               ensure_ascii=False) + "\n", encoding="utf-8")


def available(home=None) -> bool:
    """Whether the side-car is installed and pinned as this build expects.

    The answer is read from disk every call, so an install that lands
    while the desk runs is picked up on the next turn without a
    restart. The CLI file is required. A marker that names another tag
    is a refusal: this build's grammar was verified against PINNED_TAG.
    A home with no marker (a hand-built or pre-marker venv) is still
    available: the CLI file is the only install this module can prove.
    """
    try:
        home_path = Path(home) if home is not None else default_home()
        if not cli_path(home_path).is_file():
            return False
        marker = read_marker(home_path)
        if marker is None:
            return True
        return str(marker.get("tag") or "") == PINNED_TAG
    except OSError:
        return False


def redact(text: str, secret: str) -> str:
    """The sentence with this turn's endpoint key replaced by a marker.

    The key rides the child's environment and must never reach a note,
    the audit detail or a log line; any stderr the CLI echoes is passed
    through here before a sentence is built from it.
    """
    if not text or not secret:
        return text
    return text.replace(secret, "[the key]")


def build_command(prompt: str, *, base_url: str, model: str,
                  cli: str) -> list[str]:
    """The one-shot turn command in the grammar the pinned tag verifies.

    Order and spelling are the verified v0.23.3 shape: a quiet one-shot
    chat, the prompt as the positional value of -q, stream-json events,
    the endpoint the desk saved, the zero-tool `safe` toolset and the
    user's own tool configuration ignored. The key is deliberately not
    here: it rides the child's environment as OPENAI_API_KEY, so it can
    never appear in a process listing. The prompt rides as one argv
    element (the CLI has no stdin prompt mode), so no shell re-splits
    it; the caller caps its length before this call.
    """
    return [
        str(cli), "chat", "-q", prompt, "--oneshot", "--format", "stream-json",
        "--base-url", base_url, "--model", model,
        "-t", "safe", "--ignore-user-config",
    ]


def _env_value(name: str) -> str | None:
    """One inherited environment value, matched without regard to case."""
    for key, value in os.environ.items():
        if key.upper() == name.upper():
            return value
    return None


def contained_env(home: Path, *, api_key: str | None = None) -> dict:
    """The child process environment: an allowlist, pointed into the folder.

    Only the names a process needs to start are inherited (PATH and the
    Windows plumbing); everything else about this machine's desk, keys
    and profile is absent. The home-relative variables, TEMP included,
    all point under the side-car folder, both spellings so a CLI written
    for either platform writes its own state there. The endpoint key,
    when given, is set as OPENAI_API_KEY for this child only.
    """
    home = Path(home)
    env: dict[str, str] = {}
    for name in ENV_ALLOWLIST:
        value = _env_value(name)
        if value is not None:
            env[name] = value
    for name, relative in HOME_ENV.items():
        env[name] = str(home / relative) if relative else str(home)
    if api_key:
        env[KEY_ENV] = api_key
    return env


def _creation_flags() -> int:
    """Start the child in its own group so the whole tree can be killed."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    return 0


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill one process and everything it started, then wait briefly.

    Windows has no process groups a kill signal reaches: taskkill /T
    names the tree by its root PID. POSIX gets its own session and the
    group is signalled. The wait is bounded so a grandchild that ignores
    termination cannot hang the loop; the caller closes its pipes.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=KILL_WAIT_S,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.wait(timeout=KILL_WAIT_S)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=KILL_WAIT_S)
    except subprocess.TimeoutExpired:
        pass


def _read_bounded(stream, limit: int, sink: dict, *, on_overflow) -> None:
    """Read one pipe to EOF, stopping at the cap and killing the process.

    A reader thread per pipe keeps the bounded read simple on Windows,
    where select() does not answer for pipes. The overflow flag is set
    before the kill, so the turn answers with the cap sentence even if
    the process dies for another reason at the same moment.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = stream.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                sink["overflow"] = True
                on_overflow()
                break
            chunks.append(chunk)
    except (OSError, ValueError):
        pass
    finally:
        sink["data"] = b"".join(chunks)
        try:
            stream.close()
        except OSError:
            pass


def _spawn(argv: list[str], *, cwd: Path, env: dict, timeout_s: float) -> SpawnResult:
    """Run one contained process to completion, killing it at the ceiling.

    The child reads no input and writes only what it must: stdout is the
    event stream, stderr is kept for the failure note. Both pipes are
    read through a cap; the first byte past it kills the whole process
    tree. A process that outlives the timeout is killed the same way,
    and the turn answers as failed.
    """
    proc = subprocess.Popen(
        argv, cwd=str(cwd), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=False,
        creationflags=_creation_flags(),
        start_new_session=(os.name != "nt"),
    )
    kill_lock = threading.Lock()
    killed = {"done": False}

    def on_overflow() -> None:
        """Kill the tree once, whichever pipe crossed its cap first."""
        with kill_lock:
            if killed["done"]:
                return
            killed["done"] = True
        _kill_tree(proc)

    out_sink: dict = {"data": b"", "overflow": False}
    err_sink: dict = {"data": b"", "overflow": False}
    pairs = [(proc.stdout, STDOUT_MAX_BYTES, out_sink),
             (proc.stderr, STDERR_MAX_BYTES, err_sink)]
    readers = [
        threading.Thread(target=_read_bounded, name=f"engine-sidecar-read-{index}",
                         args=(stream, limit, sink),
                         kwargs={"on_overflow": on_overflow}, daemon=True)
        for index, (stream, limit, sink) in enumerate(pairs)
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
    for reader in readers:
        reader.join(KILL_WAIT_S)
    if any(reader.is_alive() for reader in readers):
        _kill_tree(proc)
        for reader in readers:
            reader.join(KILL_WAIT_S)
    if timed_out:
        raise SidecarError(
            "The engine side-car turn ran past its time limit and was stopped.")
    if out_sink["overflow"] or err_sink["overflow"]:
        raise SidecarError("The engine side-car answered with too much output.")
    stdout = out_sink["data"].decode("utf-8", "replace")
    stderr = err_sink["data"].decode("utf-8", "replace")
    return SpawnResult(proc.returncode, stdout, stderr)


def run(prompt: str, *, connection, home=None, timeout_s: float = DEFAULT_TIMEOUT_S,
        spawn=None) -> tuple[dict, ...]:
    """Run one turn in the side-car and return its event stream.

    `connection` is the boundary's ConnectionSpec (base URL, key, model)
    for the endpoint the desk saved. The key rides the child's
    environment only. A spawn that cannot start, a non-zero exit, the
    output cap or an empty stream raises SidecarError with the cause;
    the boundary turns that into a failed turn, never a crash. Every
    sentence built from the child's stderr is redacted first.
    """
    home = home if home is not None else default_home()
    cli = cli_path(home)
    argv = build_command(
        prompt, base_url=connection.base_url, model=connection.model,
        cli=str(cli))
    for relative in ("tmp", "appdata", "config", "cache", "state", "hermes-home"):
        try:
            (Path(home) / relative).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    runner = spawn if spawn is not None else _spawn
    try:
        result = runner(argv, cwd=Path(home),
                        env=contained_env(home, api_key=connection.api_key),
                        timeout_s=timeout_s)
    except OSError as exc:
        detail = redact(str(exc)[:200], connection.api_key)
        raise SidecarError(
            f"The engine side-car could not start: {detail}") from None
    events = parse_events(result.stdout)
    if result.returncode != 0:
        cause = (result.stderr or "").strip().splitlines()
        detail = redact(cause[-1][:200], connection.api_key) if cause \
            else f"exit code {result.returncode}"
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
