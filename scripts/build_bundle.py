#!/usr/bin/env python3
"""Build the Nexuus Bot one-folder Windows bundle with Nuitka.

The profile is deliberately one-folder (Nuitka --standalone), never
--onefile: a one-file executable unpacks itself to a temporary directory on
every launch, which is slower, harder for AppLocker/WDAC to reason about,
and more likely to trip endpoint protection. The bundle is extracted once
to a per-user location and launched from there. No step requires admin.

Commands:
    python scripts/build_bundle.py build [--dry-run] [--allow-downloads]
    python scripts/build_bundle.py smoke [--exe PATH] [--port N]
    python scripts/build_bundle.py verify

Exit codes: 0 success, 1 failure, 3 deliberate skip (Nuitka missing or no
built executable). A skip is printed as SKIP and never reported as a build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "dist" / "agent-desk"
DEFAULT_NUITKA_BUILD = REPO_ROOT / "build" / "nuitka"
EXE_NAME = "AgentDesk.exe"
MARKER_NAME = "manifest.json"
SKIP_EXIT = 3
SMOKE_REPORT = REPO_ROOT / "build" / "smoke-report.json"


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run one command with its output captured as text.

    A non-zero exit code comes back in the result instead of raising, and the
    extra keyword arguments go straight to subprocess.run.
    """
    return subprocess.run(cmd, text=True, capture_output=True, **kwargs)


def _app_version(root: Path) -> str:
    """The product version the bundle is stamped with.

    Read from pyproject.toml, then src/nexuusbot/__init__.py, then "0.0.0": an
    unversioned build still gets a manifest.
    """
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if match:
        return match.group(1)
    init = (root / "src" / "nexuusbot" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    return match.group(1) if match else "0.0.0"


def _sha256(path: Path) -> str:
    """The hex sha256 of one file's bytes, read in chunks so size does not matter."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nuitka_version() -> str | None:
    """The installed Nuitka version, or None when it is not installed.

    None is the skip signal: the build prints SKIP and claims no artifact, so a
    missing toolchain never reads as a failed build.
    """
    try:
        result = _run([sys.executable, "-m", "nuitka", "--version"])
    except OSError:
        return None
    if result.returncode != 0:
        return None
    text = (result.stdout or "") + (result.stderr or "")
    match = re.search(r"Nuitka\s+([0-9][^\s]*)", text)
    return match.group(1) if match else text.strip().splitlines()[0] if text.strip() else "unknown"


def _build_command(root: Path, *, allow_downloads: bool) -> list[str]:
    """The exact Nuitka command line for the one-folder build.

    The version flags carry four numeric parts because the Windows version
    resource rejects anything else; --assume-yes-for-downloads appears only when
    the caller opts in.
    """
    version = _app_version(root)
    numeric = ".".join((version.split(".") + ["0", "0", "0", "0"])[:4])
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--enable-plugin=no-qt",
        "--include-package=nexuusbot",
        # The compatibility alias ships beside the canonical package so
        # old imports keep resolving inside frozen builds.
        "--include-package=agentdesk",
        "--include-data-dir=src/nexuusbot/server/static=nexuusbot/server/static",
        "--nofollow-import-to=tests",
        "--nofollow-import-to=pytest",
        "--output-dir=build/nuitka",
        "--output-filename=" + EXE_NAME,
        "--windows-console-mode=disable",
        "--windows-product-name=Nexuus Bot",
        "--windows-company-name=Nexuus Bot",
        "--windows-file-description=Nexuus Bot local application",
        "--windows-file-version=" + numeric,
        "--windows-product-version=" + numeric,
        "--report=build/nuitka-report.xml",
        "--remove-output",
        "scripts/agent_desk_entry.py",
    ]
    if allow_downloads:
        # After "nuitka", not between -m and it: the flag names a Nuitka
        # option, and python -m reads the slot right after it as the module.
        cmd.insert(3, "--assume-yes-for-downloads")
    return cmd


def _secure_rmtree(path: Path) -> None:
    """Remove a build directory if it exists; a missing path is not an error."""
    if path.exists():
        shutil.rmtree(path)


def _prepare_output(output: Path, force: bool) -> None:
    """Clear a previous build's output directory, or refuse to touch it.

    An absent or empty directory is used as is. A non-empty one is removed only
    when it carries manifest.json, so it is provably ours, or when --force says
    it is; anything else raises SystemExit before a file is written.
    """
    if not output.exists():
        return
    if not output.is_dir():
        raise SystemExit(f"build: output path is a file: {output}")
    if not any(output.iterdir()):
        return
    if (output / MARKER_NAME).is_file() or force:
        _secure_rmtree(output)
        return
    raise SystemExit(
        f"build: refusing to overwrite non-empty {output} without a prior "
        "manifest.json; pass --force if that directory is yours"
    )


def _missing_build_inputs(root: Path) -> list[str]:
    """The required legal and SBOM inputs that are absent, as repo-relative paths.

    An empty list means the build may proceed; each name is exactly what the
    caller prints, so the fix is named rather than guessed.
    """
    required = [
        root / "LICENSE",
        root / "LICENSE-SDK",
        root / "THIRD-PARTY-NOTICES.md",
        root / "licenses" / "third-party",
        root / "frontend" / "public" / "licenses",
        root / "build" / "sbom.cdx.json",
    ]
    return [path.relative_to(root).as_posix() for path in required if not path.exists()]


def _copy_support_files(root: Path, output: Path) -> None:
    """Copy the licences, third-party texts and SBOM into the bundle.

    Raises SystemExit when a required file is absent: a bundle without its
    notices is not shippable, so the build stops instead of shipping one.
    """
    notices = root / "THIRD-PARTY-NOTICES.md"
    for name in ("LICENSE", "LICENSE-SDK", "THIRD-PARTY-NOTICES.md"):
        source = root / name
        if not source.is_file():
            raise SystemExit(f"build: missing required legal file {source}")
    shutil.copy2(root / "LICENSE", output / "LICENSE")
    shutil.copy2(root / "LICENSE-SDK", output / "LICENSE-SDK")
    shutil.copy2(notices, output / "THIRD-PARTY-NOTICES.md")
    shutil.copytree(
        root / "licenses" / "third-party",
        output / "licenses" / "third-party",
    )
    shutil.copytree(
        root / "frontend" / "public" / "licenses",
        output / "licenses" / "fonts",
    )
    sbom = root / "build" / "sbom.cdx.json"
    if not sbom.is_file():
        raise SystemExit(
            "build: missing build/sbom.cdx.json; run python scripts/sbom.py first"
        )
    shutil.copy2(sbom, output / "sbom.cdx.json")


def _manifest(
    root: Path,
    output: Path,
    *,
    command: list[str],
    nuitka: str,
    duration: float,
    static_count: int,
    static_index_sha: str,
) -> dict[str, Any]:
    """The manifest.json document describing one built bundle.

    Every file under the output directory is hashed here except the manifest
    itself, so verify can catch both a changed file and an added one. Paths are
    relative to the output root and POSIX-spelled, so a manifest written on
    Windows verifies anywhere.
    """
    files = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == MARKER_NAME:
            continue
        relative = path.relative_to(output).as_posix()
        files.append(
            {"path": relative, "size": path.stat().st_size, "sha256": _sha256(path)}
        )
    sbom_path = output / "sbom.cdx.json"
    return {
        "schema_version": 1,
        "product": "Nexuus Bot",
        "version": _app_version(root),
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "build": {
            "mode": "nuitka-standalone-onefolder",
            "onefile": False,
            "chosen_because": (
                "one-folder launches without self-extraction and is easier for "
                "AppLocker/WDAC and endpoint protection to reason about"
            ),
            "nuitka": nuitka,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "duration_seconds": round(duration, 1),
            "command": command,
            "entrypoint": EXE_NAME,
            "console": "disabled",
            "admin_required": False,
            "admin_note": (
                "Nuitka's default asInvoker manifest is kept; no --windows-uac-admin "
                "flag is used. The bundle writes only to %LOCALAPPDATA%.\\AgentDesk "
                "or to AGENTDESK_DATA."
            ),
            "signing": {
                "status": "unsigned",
                "publisher": None,
                "note": (
                    "No Authenticode certificate is available in this environment. "
                    "The AppLocker publisher rule in docs/ops/distribution.md stays a "
                    "placeholder until the release build is signed."
                ),
            },
            "nuitka_report": "build/nuitka-report.xml",
            "sbom": "sbom.cdx.json",
            "sbom_sha256": _sha256(sbom_path),
        },
        "frontend": {
            "source": "src/nexuusbot/server/static/spa",
            "files": static_count,
            "index_sha256": static_index_sha,
            "note": "committed Vite bundle; no node needed at runtime",
        },
        "licenses": {
            "core": "LICENSE",
            "plugin_sdk": "LICENSE-SDK",
            "notices": "THIRD-PARTY-NOTICES.md",
            "third_party_texts": sorted(
                p.relative_to(output).as_posix()
                for p in (output / "licenses").rglob("*")
                if p.is_file()
            ),
        },
        "files": files,
    }


def build(args: argparse.Namespace) -> int:
    """Build the bundle into the output directory and write its manifest.

    Returns 0 on success, 1 on a failed or unusable build, and SKIP_EXIT when
    Nuitka is absent: a skip means no artifact was attempted. --dry-run prints
    the command and the frontend hash, runs nothing, and returns 0.
    """
    root = REPO_ROOT
    output = args.output.resolve()
    static = root / "src" / "nexuusbot" / "server" / "static" / "spa"
    index = static / "index.html"
    if not index.is_file():
        print(
            "build: FAIL missing frontend bundle "
            f"{index.relative_to(root).as_posix()}; run 'npm ci && npm run build' "
            "in frontend/ (it writes the committed static bundle)",
            file=sys.stderr,
        )
        return 1
    static_files = [p for p in static.rglob("*") if p.is_file()]
    static_count = len(static_files)
    static_sha = _sha256(index)
    command = _build_command(root, allow_downloads=args.allow_downloads)
    nuitka = _nuitka_version()
    if args.dry_run:
        if nuitka is None:
            print(
                "build: Nuitka is NOT installed; --dry-run only prints the plan "
                "and does not claim a build.",
                file=sys.stderr,
            )
        else:
            print(f"build: Nuitka {nuitka} is installed")
        print("build: command (not executed, --dry-run):")
        print("  " + " ".join(command))
        print(f"build: frontend bundle {static_count} files, index sha256 {static_sha}")
        return 0
    if nuitka is None:
        print(
            "SKIP: Nuitka is not installed for this interpreter "
            f"({sys.executable}). No bundle was built and no artifact is claimed.\n"
            "Install it with: " + sys.executable + " -m pip install nuitka\n"
            "Then re-run: python scripts/build_bundle.py build",
            file=sys.stderr,
        )
        return SKIP_EXIT

    missing = _missing_build_inputs(root)
    if missing:
        print(
            "build: missing required inputs: " + ", ".join(missing) + "\n"
            "Run: python scripts/sbom.py && python scripts/third_party_notices.py",
            file=sys.stderr,
        )
        return 1
    _prepare_output(output, args.force)
    _secure_rmtree(root / "build" / "nuitka")
    (root / "build").mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    log_path = root / "build" / "nuitka-build.log"
    started = time.monotonic()
    print(f"build: Nuitka {nuitka}; log {log_path.relative_to(root).as_posix()}")
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    duration = time.monotonic() - started
    if result.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
        print("build: FAIL Nuitka exited " + str(result.returncode), file=sys.stderr)
        print("\n".join(tail), file=sys.stderr)
        return 1

    candidates = sorted(
        p for p in (root / "build" / "nuitka").glob("*.dist") if p.is_dir()
    )
    if not candidates:
        print("build: FAIL Nuitka produced no *.dist directory", file=sys.stderr)
        return 1
    dist_dir = candidates[-1]
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, output)
    exe = output / EXE_NAME
    if not exe.is_file():
        found = sorted(p.name for p in output.glob("*.exe"))
        print(
            f"build: FAIL expected {EXE_NAME}; found {found or 'no .exe'} "
            "(stable exe name is part of the AppLocker rule)",
            file=sys.stderr,
        )
        return 1
    _copy_support_files(root, output)
    manifest = _manifest(
        root,
        output,
        command=command,
        nuitka=nuitka,
        duration=duration,
        static_count=static_count,
        static_index_sha=static_sha,
    )
    (output / MARKER_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"build: wrote {output.relative_to(root).as_posix()} "
        f"({len(manifest['files'])} files, {duration:.0f}s, unsigned)"
    )
    print(f"build: exe sha256 {_sha256(exe)}")
    return 0


def _http_health(port: int) -> tuple[int, str]:
    """GET /health on loopback: the status and the start of the body.

    Status 0 with the failure text means no HTTP response arrived at all, which
    is how the smoke loop tells a dead process from a live one.
    """
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status, response.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)


def _free_port() -> int:
    """An ephemeral loopback port, bound and released, for the smoke run."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stop(pid: int) -> None:
    """Kill a process and its children, so a smoke run leaves nothing behind.

    Best effort: a process that is already gone is not an error.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
        )
    else:  # pragma: no cover - the product target is Windows
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def _verify_manifest(output: Path) -> list[str]:
    """Every mismatch between the bundle and its manifest, as readable lines.

    An empty list means the bundle verifies: listed files exist at the recorded
    size and hash, and nothing unlisted sits in the directory.
    """
    manifest_path = output / MARKER_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read {manifest_path}: {exc}"]
    errors: list[str] = []
    listed: set[str] = set()
    for item in manifest.get("files") or []:
        relative = str(item.get("path"))
        listed.add(relative)
        path = output / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
            continue
        if path.stat().st_size != item.get("size"):
            errors.append(f"size mismatch: {relative}")
        if _sha256(path) != item.get("sha256"):
            errors.append(f"sha256 mismatch: {relative}")
    for path in output.rglob("*"):
        if not path.is_file() or path.name == MARKER_NAME:
            continue
        relative = path.relative_to(output).as_posix()
        if relative not in listed:
            errors.append(f"unlisted file: {relative}")
    return errors


def verify(args: argparse.Namespace) -> int:
    """Check the bundle on disk against its manifest.json.

    Returns 0 and prints PASS when every listed file matches its recorded size
    and sha256 and no unlisted file is present; otherwise 1, with one line per
    problem on stderr.
    """
    output = args.output.resolve()
    errors = _verify_manifest(output)
    if errors:
        print("verify: FAIL", file=sys.stderr)
        for error in errors:
            print("  " + error, file=sys.stderr)
        return 1
    manifest = json.loads((output / MARKER_NAME).read_text(encoding="utf-8"))
    print(
        f"verify: PASS {len(manifest.get('files') or [])} files match manifest.json "
        f"(version {manifest.get('version')})"
    )
    return 0


def smoke(args: argparse.Namespace) -> int:
    """Start the built executable and check that it serves /health.

    Returns 0 when the server answers 200 or 401 (401 proves the HTTP server and
    auth gate are live, since the bootstrap token never leaves the process), 1
    when it does not, and SKIP_EXIT when there is no executable to start. A run
    writes build/smoke-report.json either way.
    """
    output = args.output.resolve()
    exe = (args.exe or (output / EXE_NAME)).resolve()
    if not exe.is_file():
        print(
            f"SKIP: no built executable at {exe}. Nuitka is not installed in "
            "this environment, so no build was attempted and no smoke result "
            "is claimed. Run 'python scripts/build_bundle.py build' on a "
            "machine with Nuitka first.",
            file=sys.stderr,
        )
        return SKIP_EXIT
    manifest_errors = _verify_manifest(output) if not args.exe else []
    if manifest_errors:
        print("smoke: FAIL bundle manifest does not match", file=sys.stderr)
        for error in manifest_errors:
            print("  " + error, file=sys.stderr)
        return 1
    port = args.port or _free_port()
    with tempfile.TemporaryDirectory(prefix="agentdesk-smoke-") as data_dir:
        env = dict(os.environ)
        env["AGENTDESK_DATA"] = data_dir
        env.setdefault("PYTHONUTF8", "1")
        log_path = REPO_ROOT / "build" / "smoke.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(exe), "--port", str(port), "--no-browser"],
                cwd=str(exe.parent),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        status = 0
        body = ""
        try:
            deadline = started + args.timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                status, body = _http_health(port)
                if status in (200, 401):
                    break
                time.sleep(0.4)
            elapsed = time.monotonic() - started
            alive = process.poll() is None
            payload: dict[str, Any] = {
                "exe": exe.name,
                "exe_sha256": _sha256(exe),
                "port": port,
                "http_status": status,
                "response_excerpt": body[:500],
                "startup_seconds": round(elapsed, 2),
                "process_alive": alive,
                "authenticated": status == 200,
                "note": (
                    "HTTP 401 is the expected unauthenticated /health response: "
                    "the bootstrap token is held in memory only, so a smoke test "
                    "cannot read it. 401 proves the HTTP server and auth gate are "
                    "live; 200 additionally proves the health payload."
                ),
                "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
            if status == 200:
                try:
                    payload["health"] = json.loads(body)
                except json.JSONDecodeError:
                    payload["health_error"] = "health body was not JSON"
            SMOKE_REPORT.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            if status not in (200, 401) or not alive:
                log_tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
                print(
                    f"smoke: FAIL exe did not serve /health (status {status}, "
                    f"alive={alive}); see {log_path}",
                    file=sys.stderr,
                )
                print("\n".join(log_tail), file=sys.stderr)
                return 1
            print(
                f"smoke: PASS {EXE_NAME} served /health on 127.0.0.1:{port} "
                f"with HTTP {status} in {elapsed:.1f}s (unsigned build)"
            )
            print(f"smoke: report {SMOKE_REPORT.relative_to(REPO_ROOT).as_posix()}")
            return 0
        finally:
            if process.poll() is None and not args.keep:
                _stop(process.pid)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def main(argv: list[str] | None = None) -> int:
    """Parse the subcommand and return its exit code.

    No subcommand, or a leading flag, means build, so the bare command keeps
    working; argparse's own exits are turned back into codes.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv = ["build", *argv]
    parser = argparse.ArgumentParser(
        prog="build_bundle.py",
        description="Build/smoke/verify the Nexuus Bot Nuitka one-folder bundle.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="build dist/agent-desk")
    build_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build_parser.add_argument("--force", action="store_true")
    build_parser.add_argument(
        "--allow-downloads", action="store_true",
        help="let Nuitka download its own toolchain components (explicit opt-in)",
    )
    build_parser.add_argument(
        "--dry-run", action="store_true",
        help="print the exact command without building",
    )
    build_parser.set_defaults(func=build)

    smoke_parser = sub.add_parser("smoke", help="start the built exe and check /health")
    smoke_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    smoke_parser.add_argument("--exe", type=Path, default=None)
    smoke_parser.add_argument("--port", type=int, default=0)
    smoke_parser.add_argument("--timeout", type=float, default=60.0)
    smoke_parser.add_argument("--keep", action="store_true")
    smoke_parser.set_defaults(func=smoke)

    verify_parser = sub.add_parser("verify", help="check files against manifest.json")
    verify_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    verify_parser.set_defaults(func=verify)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())