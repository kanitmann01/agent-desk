"""Real-world adapters for the probe (the only side-effectful code).

These are thin wrappers over subprocess, urllib, shutil and the filesystem.
Gate logic never imports this module; only the CLI (and the one real
subprocess test) wires them in, which keeps every gate testable with fakes.
Even the gates' file writes and copies flow through the write_text and
copy_file callables bundled in Adapters, so gates.py does no direct disk
I/O beyond (re)creating the caller-supplied workdir.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agentdesk.probe.core import POWER_AUTOMATE_URL, OneDriveInfo, ReachResult, RunResult

DEFAULT_TIMEOUT_S = 120
REACH_TIMEOUT_S = 10


def subprocess_runner(cmd: list[str], timeout: int = DEFAULT_TIMEOUT_S) -> RunResult:
    """Run a command as the current user, no elevation, capture output."""
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RunResult(returncode=124, error=f"timed out after {timeout}s")
    except OSError as exc:
        return RunResult(returncode=127, error=str(exc))
    return RunResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def reach_url(url: str = POWER_AUTOMATE_URL, timeout: int = REACH_TIMEOUT_S) -> ReachResult:
    """Best-effort HTTPS reachability check with stdlib only.

    Any HTTP status (even 403 from a proxy) means the endpoint is reachable;
    only connection-level errors are reported as failures.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "agentdesk-probe"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return ReachResult(url=url, status=response.status)
    except urllib.error.HTTPError as exc:
        # A response arrived, so the endpoint is reachable at network level.
        return ReachResult(url=url, status=exc.code)
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return ReachResult(url=url, error=str(reason))


def find_uv() -> str | None:
    """Locate uv on PATH without elevation."""
    return shutil.which("uv")


def write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Write text to a file (gate 1's hello-world, gate 4's probe file)."""
    Path(path).write_text(text, encoding=encoding)


def copy_file(source, dest) -> None:
    """Copy a file (gate 4's probe-file copy into the sync root)."""
    shutil.copy(source, dest)


def list_processes() -> RunResult:
    """List running processes for the EDR gate (stdlib only).

    Windows: tasklist with its service columns. Other platforms (macOS
    and Linux): ps is the portable shape. The gates only consume stdout
    as text, so either listing feeds them the same way.
    """
    import os

    if os.name == "nt":
        return subprocess_runner(["tasklist", "/svc", "/fo", "csv", "/nh"], timeout=30)
    return subprocess_runner(["ps", "-axo", "pid,comm"], timeout=30)


def discover_onedrive() -> OneDriveInfo | None:
    """Find the OneDrive sync root for the current user.

    Windows: the OneDrive environment variables first, then a OneDrive*
    folder under the user profile. macOS: the sync root lives under
    ~/Library/CloudStorage/OneDrive-<tenant>, so glob that shape. The
    evidence string names what was actually checked. Never writes
    anything.
    """
    import os

    if os.name != "nt":
        home = Path.home()
        for entry in sorted(home.glob("Library/CloudStorage/OneDrive*")):
            if entry.is_dir():
                return OneDriveInfo(
                    path=str(entry),
                    how="folder found under ~/Library/CloudStorage matching OneDrive*",
                )
        return None

    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(var)
        if value and Path(value).is_dir():
            return OneDriveInfo(path=value, how=f"environment variable {var}")

    profile = os.environ.get("USERPROFILE")
    if profile:
        for entry in sorted(Path(profile).glob("OneDrive*")):
            if entry.is_dir():
                return OneDriveInfo(path=str(entry), how=f"folder found under %USERPROFILE% matching OneDrive*")
    return None


@dataclass(frozen=True)
class Adapters:
    """The injectable side-effect bundle the CLI passes to every gate.

    Tests swap this for fakes; the CLI builds the real one.
    """

    runner: Callable  # list[str] -> RunResult
    find_uv: Callable  # () -> str | None
    reach: Callable  # str -> ReachResult
    list_processes: Callable  # () -> RunResult
    discover_onedrive: Callable  # () -> OneDriveInfo | None
    write_text: Callable  # (path, text, encoding="utf-8") -> None
    copy_file: Callable  # (source, dest) -> None


def real_adapters() -> Adapters:
    """The production bundle: subprocess, shutil, urllib and the filesystem."""
    return Adapters(
        runner=subprocess_runner,
        find_uv=find_uv,
        reach=reach_url,
        list_processes=list_processes,
        discover_onedrive=discover_onedrive,
        write_text=write_text,
        copy_file=copy_file,
    )
