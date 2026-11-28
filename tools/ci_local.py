"""The deterministic local CI gate: the same checks the hosted workflow
runs, one command, zero GitHub minutes.

Born when the account's spending limit broke (every 2026-11-13 hosted
run was refused before any job started); the hosted workflow is green
again, and this script remains the local complement: the same gates,
run offline in a fixed order under a pinned environment, so the verdict
depends only on the code:

    python tools/ci_local.py

Gates, in the workflow's order (a superset where local runs are free):

1.  py-grammar       every src/tests/tools/scripts file parses under the
                     3.10 grammar (the declared floor; this stood in for
                     the 3.10 legs of the hosted matrix)
2.  pytest           the full suite over a fresh temp data dir, in
                     parallel when pytest-xdist is installed (serial,
                     the original invocation, when it is not)
3.  frontend-install npm ci ONLY when node_modules is missing
                     (deterministic install from the lockfile)
4.  frontend-check   tsc --noEmit (the workflow's typecheck gate)
5.  frontend-tests   the vitest suite (local-only addition)
6.  licenses         the authoritative SBOM chain the hosted license
                     job runs: sbom.py, license_gate.py over its
                     output, and the notices --check currency leg
7.  registry-ci      tools/registry_ci.py over every plugin in
                     registry/plugins/, against the index at the
                     branch's mainline merge-base, with archive/plugins
                     exempting deliberate retirements (a superset of the
                     hosted changed-plugins review)

Determinism contract: the environment is pinned (fresh AGENTDESK_DATA,
every AGENTDESK_* override emptied, explicit cwd), the gate list is the
fixed GATES constant below, and the exit code is 0 exactly when every
gate passed. Nothing is skipped silently: a missing tool is a named
failure, never a pass.

The honest gap versus the hosted matrix: cross-OS coverage. This gate
runs on the machine that runs it (Windows today, macOS works too); the
hosted runners added macOS and 3.12 beyond that. The suite keeps its
platform risks behind injectable seams (clocks, adapters, os knobs), so
the local verdict is the best bill-free signal available.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The pinned environment every gate runs under: no ambient AGENTDESK_*
# variable can leak in, and the suite always sees a fresh data dir.
PINNED_ENV = {
    "AGENTDESK_DATA": "",       # replaced by the per-run temp dir
    "AGENTDESK_LLM_BASE": "",
    "AGENTDESK_LLM_KEY": "",
    "AGENTDESK_LLM_MODEL": "",
    "AGENTDESK_REGISTRY": "",
    "AGENTDESK_CALENDAR_FILE": "",
}

PYTHON = sys.executable


def _grammar_gate(env: dict) -> tuple[bool, str]:
    """Every Python file parses under the 3.10 grammar (the floor)."""
    import ast
    bad: list[str] = []
    count = 0
    for base in ("src", "tests", "tools", "scripts"):
        for path in (ROOT / base).rglob("*.py"):
            # Relativize before the skip test: this gate may itself run
            # from a checkout under .worktrees/, and matching the
            # absolute path would skip the whole tree (docstring_gate
            # relativizes for exactly this reason).
            try:
                parts = path.relative_to(ROOT).parts
            except ValueError:
                parts = path.parts
            if "node_modules" in parts or ".worktrees" in parts:
                continue
            count += 1
            try:
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))
            except SyntaxError as exc:
                bad.append(f"{path.relative_to(ROOT)}: {exc}")
    if bad:
        return False, f"{count} files, {len(bad)} 3.10 syntax errors: " + "; ".join(bad[:3])
    if count == 0:
        return False, "no Python files under src/tests/tools/scripts; the walk is broken, not the floor"
    return True, f"{count} files parse under 3.10"


def _xdist_available() -> bool:
    """True when pytest-xdist is importable for this interpreter."""
    try:
        import xdist  # noqa: F401 - importability is the whole check
    except ImportError:
        return False
    return True


def _pytest_args(parallel: bool) -> list[str]:
    """The pytest invocation, parallel when xdist is installed.

    xdist gets one worker per logical core, capped at eight. The cap is
    measured, not guessed: on this 20-core Windows host, full runs at 12
    and 20 workers intermittently failed with WinError 10048 (ephemeral
    loopback ports exhausted by the suite's HTTP traffic), while eight
    workers stayed green across repeated runs at roughly 95 seconds.
    Without xdist the command is exactly the serial invocation this gate
    has always used.
    """
    args = [PYTHON, "-m", "pytest", "tests", "-q", "--no-header"]
    if parallel:
        workers = min(os.cpu_count() or 1, 8)
        args += ["-n", str(workers)]
    return args


def failed_test_lines(output: str, limit: int = 3) -> list[str]:
    """The `FAILED` and `ERROR` summary lines of a pytest run, newest last.

    pytest ends its output with one such line per failed test in both the
    serial and the xdist invocation, so the gate reads them without adding a
    report flag to the command. A count alone sends the reader back into a
    hundred-second run to learn which test to look at; on a load flake the
    name is the only thing that cannot be recovered afterwards. At most
    `limit` lines are returned, each cut to one readable length.
    """
    lines = [line.strip() for line in output.splitlines()
             if line.startswith(("FAILED ", "ERROR "))]
    return [line[:200] for line in lines[:limit]]


def _pytest_gate(env: dict) -> tuple[bool, str]:
    """The full suite over the pinned fresh data dir.

    A failing run names its failed tests after the summary line.
    """
    parallel = _xdist_available()
    proc = subprocess.run(
        _pytest_args(parallel),
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "(no output)"
    if proc.returncode != 0:
        failed = failed_test_lines(proc.stdout or "")
        if failed:
            summary += " | " + "; ".join(failed)
    workers = _pytest_args(True)[-1]
    mode = f"parallel -n {workers}" if parallel else "serial (xdist not installed)"
    return proc.returncode == 0, f"{mode}: {summary}"


def _frontend_check(env: dict) -> tuple[bool, str]:
    """tsc --noEmit, the workflow's typecheck gate."""
    proc = subprocess.run(
        ["npm", "run", "check"], cwd=ROOT / "frontend",
        env=env, capture_output=True, text=True, shell=(os.name == "nt"),
    )
    if proc.returncode != 0:
        lines = (proc.stdout or proc.stderr or "").strip().splitlines()
        return False, lines[-1][:200] if lines else "tsc failed with no output"
    return True, "tsc --noEmit clean"


def _frontend_tests(env: dict) -> tuple[bool, str]:
    """The vitest suite (a local-only addition over the hosted gates)."""
    proc = subprocess.run(
        ["npm", "test", "--", "--run"], cwd=ROOT / "frontend",
        env=env, capture_output=True, text=True, shell=(os.name == "nt"),
    )
    tail = [l for l in (proc.stdout or "").strip().splitlines() if "Tests" in l]
    return proc.returncode == 0, tail[-1][:120] if tail else f"exit {proc.returncode}"


def _license_gate(env: dict) -> tuple[bool, str]:
    """The SBOM license chain the hosted license-gate job runs."""
    chain = (
        ("sbom", [PYTHON, "scripts/sbom.py"]),
        ("license-gate", [PYTHON, "scripts/license_gate.py",
                          "build/sbom.cdx.json", "--report",
                          "build/license-report.txt"]),
        ("notices", [PYTHON, "scripts/third_party_notices.py", "--check"]),
    )
    for name, args in chain:
        proc = subprocess.run(args, cwd=ROOT, env=env,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            lines = (proc.stdout or proc.stderr or "").strip().splitlines()
            tail = lines[-1][:160] if lines else f"exit {proc.returncode}"
            return False, f"{name}: {tail}"
    return True, "sbom, license gate and notices all clean"


def _registry_base_index(env: dict) -> Path | None:
    """The mainline registry index for the append-only history check.

    The retirement path is only trustworthy when CI actually compares the
    new index to the branch's base, so the gate asks git for the merge-base
    with the mainline and reads the index at that commit. A checkout without
    git, without a mainline ref, or without the file returns None; the
    registry review then skips the history leg instead of inventing one.
    """
    for ref in ("main", "origin/main"):
        merge = subprocess.run(
            ["git", "merge-base", "HEAD", ref], cwd=ROOT, env=env,
            capture_output=True, text=True,
        )
        if merge.returncode != 0 or not merge.stdout.strip():
            continue
        show = subprocess.run(
            ["git", "show", f"{merge.stdout.strip()}:registry/index.json"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        if show.returncode != 0 or not show.stdout.strip():
            continue
        fd, name = tempfile.mkstemp(
            prefix="agentdesk-base-index-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(show.stdout)
        return Path(name)
    return None


def _brand_leak_gate(env: dict) -> tuple[bool, str]:
    """Committed template packs against the hash denylist."""
    proc = subprocess.run(
        [PYTHON, "tools/brand_leak.py"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, tail[-1][:160] if tail else f"exit {proc.returncode}"


def _registry_gate(env: dict) -> tuple[bool, str]:
    """Registry CI over every committed plugin directory and its base."""
    plugin_dirs = sorted(p.name for p in (ROOT / "registry" / "plugins").iterdir() if p.is_dir())
    args = [PYTHON, "tools/registry_ci.py", "--registry", "registry"]
    if plugin_dirs:
        args += ["--plugins", ",".join(f"registry/plugins/{name}" for name in plugin_dirs)]
    if (ROOT / "archive" / "plugins").is_dir():
        args += ["--archive", "archive/plugins"]
    base_index = _registry_base_index(env)
    if base_index is not None:
        args += ["--base-index", str(base_index)]
    try:
        proc = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
    finally:
        if base_index is not None:
            base_index.unlink(missing_ok=True)
    tail = (proc.stdout or "").strip().splitlines()
    return proc.returncode == 0, tail[-1][:160] if tail else f"exit {proc.returncode}"


GATES = [
    ("py-grammar", _grammar_gate),
    ("pytest", _pytest_gate),
    ("frontend-check", _frontend_check),
    ("frontend-tests", _frontend_tests),
    ("licenses", _license_gate),
    ("registry-ci", _registry_gate),
    ("brand-leak", _brand_leak_gate),
]


def main() -> int:
    """Run every gate in GATES and return 0 only when all of them pass.

    Runs under PINNED_ENV plus a fresh temporary AGENTDESK_DATA directory that
    is removed afterwards; npm ci runs first when frontend/node_modules is
    missing. A gate that raises counts as failed instead of aborting the run.
    Prints one line per gate with its duration and detail, then the tally and
    "CI PASS", or the names of the failed gates and exit 1.
    """
    started = time.time()
    data_dir = tempfile.mkdtemp(prefix="agentdesk-ci-")
    env = {**os.environ, **PINNED_ENV, "AGENTDESK_DATA": data_dir}
    print(f"Nexuus Bot local CI  (data dir: {data_dir})")
    print(f"checkout: {ROOT}")
    print("-" * 72)
    results: list[tuple[str, bool, str, float]] = []
    try:
        if not (ROOT / "frontend" / "node_modules").is_dir():
            print("node_modules missing: npm ci (deterministic, from the lockfile)")
            subprocess.run(["npm", "ci"], cwd=ROOT / "frontend", shell=(os.name == "nt"), check=True)
        for name, gate in GATES:
            t0 = time.time()
            try:
                ok, detail = gate(env)
            except Exception as exc:  # noqa: BLE001 - a broken gate is a failed gate
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            seconds = time.time() - t0
            results.append((name, ok, detail, seconds))
            print(f"{'PASS' if ok else 'FAIL'}  {name:<16} {seconds:6.1f}s  {detail}")
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    print("-" * 72)
    failed = [name for name, ok, _d, _s in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} gates passed in {time.time() - started:.0f}s")
    if failed:
        print("FAILED gates: " + ", ".join(failed))
        return 1
    print("CI PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
