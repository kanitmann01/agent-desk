"""Self-update: read the share, stage a verified bundle, and go back on failure.

The feature ships off. With Install updates off the desk still reads the
channel and says which version is out there, but it copies nothing and runs
nothing. With it on, a bundle is snapshotted, extracted, checked against its
manifest, and handed to its own --self-check before the pointer moves. A
failed first start puts the previous pointer back and repairs only the sqlite
files that no longer pass integrity_check.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agentdesk import PRODUCT_NAME, __version__
from agentdesk.update import stage
from agentdesk.update.channel import Available, ChannelUnreadable, newest, parse_version

READY = (
    "Version {version} is ready. Restart "
    f"{PRODUCT_NAME} from its shortcut to switch."
)
NO_PROGRAM_IN_STAGE = f"The update has no {PRODUCT_NAME} program in it."
ROLLED_BACK = (
    "This version failed its check. The desk went back to {version}. "
    "Restart from the shortcut to finish."
)
SHARE_UNREADABLE = "The update share couldn't be read: {cause}"


def _now() -> datetime:
    """The local time an update check is stamped with."""
    return datetime.now(timezone.utc).astimezone()


def _data_dir(server=None) -> Path:
    """The desk's data folder; the server carries no separate copy."""
    from agentdesk.server.app import default_data_dir

    return Path(default_data_dir())


def _channel(server) -> str:
    """The configured share path, stripped, or empty when unset."""
    settings = getattr(server, "settings", None)
    if settings is None:
        return ""
    value = settings.get("update_channel")
    return value.strip() if isinstance(value, str) else ""


def _target_for(data_dir: Path, version: str) -> Path:
    """The executable the launcher should start for one version folder."""
    folder = Path(data_dir) / stage.VERSIONS_DIR / version
    for name in ("AgentDesk.exe", "agentdesk.exe"):
        candidate = folder / name
        if candidate.is_file():
            return candidate
    executables = sorted(folder.glob("*.exe"))
    if executables:
        return executables[0]
    return folder / "AgentDesk.exe"


def _prune_versions(data_dir: Path, keep: set[str]) -> None:
    """Keep the named version folders and delete every older staged one."""
    root = Path(data_dir) / stage.VERSIONS_DIR
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir() and child.name not in keep:
            shutil.rmtree(child, ignore_errors=True)


def _copy_for_check(data_dir: Path) -> Path:
    """A throwaway copy of the data folder without the update area."""
    root = Path(tempfile.mkdtemp(prefix="agentdesk-update-"))
    shutil.copytree(
        data_dir,
        root / "data",
        ignore=shutil.ignore_patterns("update"),
        dirs_exist_ok=False,
    )
    return root / "data"


def _default_health(executable: Path, data_copy: Path) -> tuple[bool, str]:
    """Run the staged copy's own self-check against the copy of the data."""
    from agentdesk.server import selfcheck

    command = selfcheck.command_for(executable, data_copy)
    return selfcheck.run_staged(command, data_copy)


def _state(data_dir: Path) -> stage.UpdateState:
    """The update state for one data folder."""
    return stage.UpdateState(data_dir)


def _set_result(data_dir: Path, value: str, *, cause: str = "", **changes) -> dict:
    """Write one terminal result and the fields that explain it."""
    state = _state(data_dir)
    return state.set(lastResult=value, lastCause=cause, lastCheckTs=_now().timestamp(), **changes)


def summary(data_dir: Path) -> dict:
    """What the settings page and the banner need, from state.json alone."""
    document = _state(data_dir).read()
    banner = None
    if document.get("pending") and document.get("lastResult") == "staged":
        banner = READY.format(version=document["pending"])
    elif document.get("lastResult") == "rolled-back":
        banner = ROLLED_BACK.format(version=document.get("current") or __version__)
    return {
        "current": document.get("current") or __version__,
        "previous": document.get("previous"),
        "pending": document.get("pending"),
        "lastResult": document.get("lastResult") or "none",
        "lastCause": document.get("lastCause") or "",
        "lastCheckTs": document.get("lastCheckTs") or 0,
        "available": document.get("available"),
        "banner": banner,
    }


def _remove_pointer(data_dir: Path) -> None:
    """Forget the pointer when there is no previous version to point at."""
    try:
        (Path(data_dir) / stage.POINTER_PATH).unlink()
    except FileNotFoundError:
        pass


def _previous_pointer(data_dir: Path, document: dict) -> dict:
    """The pointer before this update, captured for Undo."""
    pointer = stage.read_pointer(data_dir)
    if pointer is not None:
        return pointer
    previous = document.get("previous") or document.get("current") or __version__
    return {"version": previous, "path": str(_target_for(data_dir, previous))}


def _record_applied(server, data_dir: Path, version: str, before: dict) -> str | None:
    """One undoable row naming the version and the pointer it replaced."""
    ledger = getattr(server, "ledger", None)
    if ledger is None:
        return None
    pointer = stage.read_pointer(data_dir) or {}
    entry = ledger.record(
        actor="agent",
        action="update.applied",
        subject=f"update/{version}",
        why="The desk staged a version that passed its own check.",
        undo_kind="version-pointer",
        before=json.dumps(before, sort_keys=True).encode("utf-8"),
        after=json.dumps(pointer, sort_keys=True).encode("utf-8"),
        detail={"version": version},
    )
    return entry.id


def _check_channel(server, data_dir: Path) -> tuple[Available | None, dict]:
    """Read the channel and write the last-check answers."""
    channel = _channel(server)
    if not channel:
        document = _set_result(data_dir, "none", available=None)
        return None, document
    try:
        available = newest(Path(channel), __version__)
    except ChannelUnreadable as exc:
        document = _set_result(
            data_dir,
            "channel-unreadable",
            cause=SHARE_UNREADABLE.format(cause=str(exc)),
            available=None,
        )
        return None, document
    document = _state(data_dir).read()
    if available is None:
        document = _set_result(data_dir, "up-to-date", available=None)
        return None, document
    document = _set_result(
        data_dir,
        "none" if not document.get("lastResult") == "staged" else document["lastResult"],
        available=available.version,
    )
    return available, document


def _failed(data_dir: Path, result: str, cause: str) -> dict:
    """Write a failed check and return its terminal result."""
    _set_result(data_dir, result, cause=cause, pending=None)
    return {"result": result, "cause": cause}


def _stage_bundle(server, data_dir: Path, available: Available, health_runner) -> dict:
    """Snapshot, extract, verify and health-check; return a terminal result."""
    folder = available.folder
    outside = folder / "manifest.json"
    bundle = folder / "agent-desk.zip"
    try:
        outside_bytes = outside.read_bytes()
    except OSError as exc:
        return _failed(data_dir, "channel-unreadable", SHARE_UNREADABLE.format(cause=str(exc)))
    try:
        snapshot_dir = stage.snapshot(data_dir, _now())
    except Exception as exc:
        return _failed(data_dir, "health-failed", f"The desk could not snapshot its data: {exc}")

    staged = Path(data_dir) / stage.VERSIONS_DIR / available.version
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)
    try:
        stage.extract(bundle, staged)
    except (OSError, ValueError) as exc:
        shutil.rmtree(staged, ignore_errors=True)
        return _failed(data_dir, "health-failed", f"The update archive was refused: {exc}")
    try:
        inside_bytes = (staged / "manifest.json").read_bytes()
    except OSError:
        inside_bytes = b""
    if inside_bytes != outside_bytes:
        shutil.rmtree(staged, ignore_errors=True)
        return _failed(
            data_dir, "health-failed",
            "The manifest in the bundle does not match the share.",
        )
    problems = stage.verify(staged, available.manifest)
    if problems:
        shutil.rmtree(staged, ignore_errors=True)
        return _failed(
            data_dir, "health-failed",
            "The update did not match its manifest: " + " ".join(problems[:3]),
        )

    executable = next(
        (path for path in (staged / "AgentDesk.exe", staged / "agentdesk.exe") if path.is_file()),
        None,
    )
    if executable is None:
        shutil.rmtree(staged, ignore_errors=True)
        return _failed(data_dir, "health-failed", NO_PROGRAM_IN_STAGE)

    try:
        data_copy = _copy_for_check(data_dir)
    except OSError as exc:
        shutil.rmtree(staged, ignore_errors=True)
        return _failed(data_dir, "health-failed", f"The desk could not copy its data: {exc}")
    try:
        runner = health_runner or _default_health
        ok, note = runner(executable, data_copy)
    except Exception as exc:
        ok, note = False, f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(data_copy.parent, ignore_errors=True)
    if not ok:
        shutil.rmtree(staged, ignore_errors=True)
        return _failed(data_dir, "health-failed", note or "The staged copy failed its check.")

    before = _previous_pointer(data_dir, _state(data_dir).read())
    previous = _state(data_dir).read().get("previous") or _state(data_dir).read().get("current") or __version__
    stage.write_pointer(data_dir, available.version, executable)
    _set_result(
        data_dir,
        "staged",
        available=available.version,
        previous=previous,
        pending=available.version,
        snapshot=snapshot_dir.name,
    )
    entry = _record_applied(server, data_dir, available.version, before)
    _prune_versions(data_dir, {available.version, previous})
    return {"result": "staged", "version": available.version, "entry": entry}


def _audit(server, action: str, *, status: str = "ok", detail: str = "", target: str = "") -> None:
    """One trail row, when this server has an audit connection."""
    conn = getattr(server, "audit_conn", None)
    if conn is None:
        return
    try:
        from agentdesk.assistant.audit import record

        record(conn, action, target=target, status=status, detail=detail[:300])
    except Exception:  # noqa: BLE001 - a trail write never stops the check
        pass


def run_update(server, health_runner=None) -> dict:
    """One check: report a newer version, and install it only when allowed."""
    data_dir = _data_dir(server)
    available, _document = _check_channel(server, data_dir)
    if available is None:
        document = _state(data_dir).read()
        result = {"result": document.get("lastResult") or "none", "available": document.get("available")}
        if result["result"] == "channel-unreadable":
            _audit(server, "update.check-failed", status="error",
                   detail=document.get("lastCause") or "", target="channel")
        return result
    settings = getattr(server, "settings", None)
    auto = bool(settings.get("auto_update")) if settings is not None else False
    if not auto:
        return {"result": "none", "available": available.version}
    document = _state(data_dir).read()
    if document.get("pending") == available.version and document.get("lastResult") == "staged":
        # Already waiting for a restart: another pass must not copy,
        # execute or record the same version a second time.
        return {"result": "staged", "version": available.version}
    result = _stage_bundle(server, data_dir, available, health_runner)
    if result.get("result") == "staged":
        _audit(server, "update.applied", target=available.version,
               detail=str(result.get("entry") or ""))
    elif result.get("result") == "health-failed":
        _audit(server, "update.check-failed", status="error",
               detail=str(result.get("cause") or ""), target=available.version)
    return result


def _rollback(data_dir: Path, document: dict, *, cause: str) -> dict:
    """Put the previous pointer back, repair corrupt stores, and say so."""
    previous = document.get("previous") or document.get("current") or __version__
    snapshot_name = document.get("snapshot")
    snapshot_dir = Path(data_dir) / stage.SNAPSHOT_DIR / snapshot_name if snapshot_name else None
    if previous:
        stage.write_pointer(data_dir, previous, _target_for(data_dir, previous))
    else:
        _remove_pointer(data_dir)
    if snapshot_dir is not None:
        stage.restore_corrupt(data_dir, snapshot_dir)
    _prune_versions(data_dir, {previous} if previous else set())
    return _state(data_dir).set(
        current=previous,
        pending=None,
        lastResult="rolled-back",
        lastCause=cause,
        lastCheckTs=_now().timestamp(),
    )


def first_start(data_dir: Path, checker=None) -> dict:
    """Check a pending version in-process before the desk serves; roll back on failure."""
    state = _state(data_dir)
    document = state.read()
    pending = document.get("pending")
    if not pending:
        return summary(data_dir) | {"lastResult": document.get("lastResult") or "none"}
    run_check = checker
    if run_check is None:
        from agentdesk.server import selfcheck

        run_check = lambda: selfcheck.run(Path(data_dir))
    try:
        answer = run_check()
    except Exception as exc:
        answer = {"ok": False, "findings": [{"cause": f"{type(exc).__name__}: {exc}"}]}
    if isinstance(answer, dict) and answer.get("ok"):
        state.set(current=pending, pending=None, lastResult="applied")
        return summary(data_dir) | {"lastResult": "applied"}
    cause = "This version failed its check."
    if isinstance(answer, dict) and answer.get("findings"):
        first = answer["findings"][0]
        if isinstance(first, dict) and first.get("cause"):
            cause = str(first["cause"])[:300]
    _rollback(data_dir, document, cause=cause)
    return summary(data_dir) | {"lastResult": "rolled-back"}


def make_rolled_back(data_dir: Path, *, cause: str = "The update was undone.") -> dict:
    """Mark the state after Undo put the previous pointer back."""
    pointer = stage.read_pointer(data_dir) or {}
    return _set_result(
        data_dir,
        "rolled-back",
        cause=cause,
        current=pointer.get("version") or __version__,
        pending=None,
    )


def rollback_now(server, data_dir: Path | None = None) -> dict:
    """Roll back from the pointer captured on an update.applied row."""
    root = Path(data_dir) if data_dir is not None else _data_dir(server)
    document = _state(root).read()
    result = _rollback(root, document, cause="The update was undone.")
    _audit(server, "update.rolled-back", target=str(result.get("current") or ""))
    return result
