"""The deterministic CI gate: every check the paid runners ran, one
command, zero GitHub minutes.

GitHub Actions on a private repo bills per minute and the account's
spending limit broke (every 2026-11-13 run was refused before any job
started). This script replaces the hosted matrix with the same gates,
run locally in a fixed order under a pinned environment, so the verdict
depends only on the code:

    python tools/ci_local.py

Gates, in the workflow's order (a superset where local runs are free):

1.  py-grammar       every src/tests/tools file parses under the 3.10
                     grammar (the declared floor; this stood in for the
                     3.10 legs of the hosted matrix)
2.  pytest           the full suite over a fresh temp data dir
3.  frontend-install npm ci ONLY when node_modules is missing
                     (deterministic install from the lockfile)
4.  frontend-check   tsc --noEmit (the workflow's typecheck gate)
5.  frontend-tests   the vitest suite (local-only addition)
6.  licenses         tools/license_manifest.py and the committed
                     manifest must be byte-current (git diff --exit-code)
7.  registry-ci      tools/registry_ci.py over every plugin in
                     registry/plugins/ (a superset of the hosted
                     changed-plugins review)

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
    for base in ("src", "tests", "tools"):
        for path in (ROOT / base).rglob("*.py"):
            if "node_modules" in path.parts or ".worktrees" in path.parts:
                continue
            count += 1
            try:
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))
            except SyntaxError as exc:
                bad.append(f"{path.relative_to(ROOT)}: {exc}")
    if bad:
        return False, f"{count} files, {len(bad)} 3.10 syntax errors: " + "; ".join(bad[:3])
    return True, f"{count} files parse under 3.10"


def _pytest_gate(env: dict) -> tuple[bool, str]:
    """The full suite over the pinned fresh data dir."""
    proc = subprocess.run(
        [PYTHON, "-m", "pytest", "tests", "-q", "--no-header"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "(no output)"
    return proc.returncode == 0, summary


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
    """The manifest regenerates byte-identical (the workflow's two steps)."""
    proc = subprocess.run(
        [PYTHON, "tools/license_manifest.py"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip().splitlines()[-1][:200]
    diff = subprocess.run(
        ["git", "diff", "--exit-code", "THIRD-PARTY-LICENSES.md"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    if diff.returncode != 0:
        return False, "THIRD-PARTY-LICENSES.md is stale; regenerate and commit it"
    return True, "manifest clean and current"


def _registry_gate(env: dict) -> tuple[bool, str]:
    """Registry CI over every committed plugin directory."""
    plugin_dirs = sorted(p.name for p in (ROOT / "registry" / "plugins").iterdir() if p.is_dir())
    args = [PYTHON, "tools/registry_ci.py", "--registry", "registry"]
    for name in plugin_dirs:
        args += ["--plugins", f"registry/plugins/{name}"]
    proc = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
    tail = (proc.stdout or "").strip().splitlines()
    return proc.returncode == 0, tail[-1][:160] if tail else f"exit {proc.returncode}"


GATES = [
    ("py-grammar", _grammar_gate),
    ("pytest", _pytest_gate),
    ("frontend-check", _frontend_check),
    ("frontend-tests", _frontend_tests),
    ("licenses", _license_gate),
    ("registry-ci", _registry_gate),
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
    print(f"agent-desk local CI  (data dir: {data_dir})")
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
