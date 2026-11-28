"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, agent/idle_schedule.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The loop's two time rules. interval_due decides whether a job's interval
has elapsed, seeding the stored time on first sight and firing that same
sighting, so the first pass comes now and the interval counts from it
(spec 023). claim_run and
release_run are the single-runner rule: a lock file created exclusively
holds the run, a holder whose process is gone or whose claim is older than
the stale threshold is taken over, and anything else waits.
"""

import json
import os
import socket
from datetime import datetime, timedelta
from pathlib import Path

# A claim older than this is takeoverable even if its pid still looks alive
# (Hermes CLAIM_STALE_SECONDS, spec 016 section 8). The threshold equals the
# default interval, so a pass that overruns the interval can briefly leave
# two holders; passes are short local database work, and a second desk
# process on one data folder is the rare case. Disclosed in the PR's Risk
# line rather than redesigned here.
CLAIM_STALE_SECONDS = 3600.0


def interval_due(last_run_iso: str | None, hours: float,
                 now: datetime) -> tuple[bool, str | None]:
    """Whether the interval elapsed, and the time value to store.

    The first time a job is seen there is no stored time: the answer is
    due, and the value to store seeds now, so the first run comes at once
    and the interval counts from it (spec 023). A stored time this build
    cannot parse is treated the same way: one run now, then the fresh seed
    restarts the interval, so a damaged state still cannot fire a burst of
    runs. Zero or negative hours is never due.
    """
    if hours <= 0:
        return (False, None)
    if not last_run_iso:
        return (True, now.isoformat())
    try:
        last_run = datetime.fromisoformat(last_run_iso)
        elapsed = now - last_run
    except (ValueError, TypeError):
        # Naive against aware, or a value that is not a timestamp: fire once
        # and re-seed, so the next spacing is a known-good interval.
        return (True, now.isoformat())
    if elapsed >= timedelta(hours=hours):
        return (True, now.isoformat())
    return (False, None)


def _windows_pid_alive(pid: int) -> bool:
    """Whether a pid exists, asked of the Windows kernel directly.

    kernel32.OpenProcess with query rights is the existence probe Windows
    offers: a handle means the process is there (and is closed at once, the
    probe never holds it), ERROR_ACCESS_DENIED means it is there but
    protected, and any other failure counts as gone. Only the failure to
    open is inspected; no handle ever reaches the process.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    process_query_limited_information = 0x1000
    error_access_denied = 5

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == error_access_denied


def _pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists, probed without any signal.

    On POSIX, os.kill(pid, 0) delivers no signal at all: no exception
    means the process is there, ProcessLookupError means it is gone, and
    PermissionError means it exists but belongs to someone else.

    On Windows there is no such no-op signal: os.kill still routes through
    OpenProcess/TerminateProcess, and on CPython 3.12 and 3.14 it raises
    WinError 87 for our own live pid instead of reporting it, which would
    make every claim look dead. The probe therefore asks kernel32 for a
    query handle instead and never signals anything.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_claim(lock_path: Path) -> str | None:
    """The claim file's raw text, or None when it cannot be read."""
    try:
        return lock_path.read_text(encoding="utf-8")
    except OSError:
        return None


def _claim_is_dead(content: str | None, now: float, stale_after: float) -> bool:
    """Whether a claim's content may be taken over.

    Unreadable content counts as dead: a lock this build cannot understand
    must not block the loop forever. An age past the threshold counts as
    dead even when the pid still resolves, the crash-without-cleanup case.
    A claim another machine wrote is never judged by this machine's pids
    (the pid may belong to a live process here), so only the stale
    threshold may take it over.
    """
    if content is None:
        return True
    try:
        held = json.loads(content)
        start_ts = float(held.get("startTs", 0))
        pid = int(held.get("pid", 0))
        host = str(held.get("host", ""))
    except (ValueError, TypeError, AttributeError):
        return True
    if now - start_ts > stale_after:
        return True
    if host != socket.gethostname():
        return False
    return not _pid_alive(pid)


def claim_run(lock_path: Path, *, now: float,
              stale_after: float = CLAIM_STALE_SECONDS) -> bool:
    """Claim the single run slot at lock_path for this process.

    The lock is created with O_CREAT|O_EXCL, so two processes cannot both
    hold it; the file holds this pid, the claim time and the host name. An
    existing claim is taken over when its holder is dead or its claim is
    stale, and refused otherwise. Two desks can judge the same dead claim
    at the same moment, so the takeover removes only the exact content it
    judged dead: the file is re-read and compared first, and a claim that
    changed underneath (another desk already took over) is left alone.
    """
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    for _attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            dead = _read_claim(lock_path)
            if not _claim_is_dead(dead, now, stale_after):
                return False
            if _read_claim(lock_path) != dead:
                # The file changed between the judgment and the removal:
                # what sits there now is not the claim that was judged.
                return False
            try:
                lock_path.unlink()
            except OSError:
                return False
            continue
        try:
            payload = json.dumps({
                "pid": os.getpid(),
                "startTs": now,
                "host": socket.gethostname(),
            })
            os.write(descriptor, payload.encode("utf-8"))
        finally:
            os.close(descriptor)
        return True
    return False


def release_run(lock_path: Path, *, start_ts: float | None = None) -> None:
    """Give the run slot back; a lock that is already gone stays gone.

    With start_ts (the claim time this pass wrote), the file is removed
    only when it still holds that same claim: a pass that overran the
    stale threshold and lost its claim to a successor must not delete the
    successor's live claim on its way out. Without start_ts the removal is
    unconditional, the pre-existing behaviour.
    """
    try:
        if start_ts is not None:
            held = _read_claim(lock_path)
            if held is None:
                return
            try:
                owner = float(json.loads(held).get("startTs", 0))
            except (ValueError, TypeError, AttributeError):
                owner = None
            if owner != start_ts:
                return
        lock_path.unlink()
    except OSError:
        pass
