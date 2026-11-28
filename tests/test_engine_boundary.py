"""The engine boundary's contract: one call runs a turn, two backends behind it.

These tests drive the boundary's public surface only (spec 023, ticket
023-3): the side-car is exercised through an injected spawn, so no test
ever starts the real side-car, and the fixed-loop fallback through the
smallest stand-in for the supervised loop. The boundary scan is the
other half of the contract: nothing outside src/nexuusbot/engine may
import a backend by name, and this file holds itself to the same rule,
which is why even the command grammar is pinned through run_turn. The
two process tests are the exception the rule is meant to allow: the
output and timeout caps live in the spawned process's own pipe handling,
so they reach the package's module object for the private spawn rather
than importing a backend by name, and the child they start is this
interpreter, never the side-car.
"""

import ast
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nexuusbot.engine as engine_pkg
from nexuusbot.engine import (
    ARG_MAX_CHARS,
    ConnectionSpec,
    EngineUnavailable,
    MAX_ACTIONS_PER_TURN,
    PROMPT_MAX_CHARS,
    TOOL_SPECS,
    prompt_for,
    run_turn,
)
from nexuusbot.ledger.store import Ledger

# The backend modules only the engine package may name.
BACKENDS = ("sidecar", "fallback")
# The live trees the scan walks: the product, its tools and scripts, and
# the tests that hold the rule.
SCAN_ROOTS = (
    ROOT / "src" / "nexuusbot",
    ROOT / "tools",
    ROOT / "scripts",
    ROOT / "tests",
)

CONNECTION = ConnectionSpec(base_url="http://127.0.0.1:9/v1", api_key="sk-test",
                            model="mock-chat")


class _FixedLoop:
    """The smallest stand-in for the supervised loop: one pass, one entry."""

    def __init__(self, ledger: Ledger, *, running: bool = False) -> None:
        """Hold the ledger the pass records into and its running state."""
        self.ledger = ledger
        self._running = running
        self.passes = 0

    def is_running(self) -> bool:
        """The loop's own re-entry guard, as AgentLoop answers it."""
        return self._running

    def run_pass(self) -> list[dict]:
        """Record one undoable change and answer today's step-row shape."""
        self.passes += 1
        self.ledger.record(
            actor="agent", action="recommend.added",
            subject="recommendation/engine:test", why="The pass suggests this.",
            undo_kind="card-added")
        return [{"name": "deskcheck", "ok": True, "ms": 1, "note": ""}]


class _SpawnSpy:
    """A spawn that never runs a process: it records and answers canned text."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        """Pin the answer the fake process gives."""
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[dict] = []

    def __call__(self, argv, *, cwd, env, timeout_s):
        """Record one call with the containment facts the run chose."""
        self.calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env),
                           "timeout_s": timeout_s})
        return SimpleResult(self.returncode, self.stdout, self.stderr)


class SimpleResult:
    """The three fields the boundary reads from a finished process."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        """Hold the exit code and captured output."""
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _pinned_cli(home: Path) -> Path:
    """Where the pinned CLI sits, stated here independently of the code:
    Windows venvs use Scripts and .exe, POSIX ones use bin."""
    scripts = "Scripts" if os.name == "nt" else "bin"
    name = "hermes.exe" if os.name == "nt" else "hermes"
    return Path(home) / "venv" / scripts / name


def _installed_home() -> Path:
    """A side-car home that looks installed: the pinned CLI file exists."""
    home = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-home-"))
    cli = _pinned_cli(home)
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("", encoding="utf-8")
    return home


def _stream(*events: dict) -> str:
    """The side-car stdout for these events: one JSON object per line."""
    return "".join(json.dumps(event) + "\n" for event in events)


def _call_events(calls: list[dict]) -> str:
    """The stream for a turn whose result event carries these tool calls."""
    return _stream(
        {"type": "system/init", "session": "s1"},
        {"type": "text", "text": "reading the desk"},
        {"type": "result", "text": json.dumps(calls)},
    )


def _backend_import_hits(path: Path, tree: ast.AST) -> list[str]:
    """The backend names one file's syntax tree imports, if any."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[:2] == ["nexuusbot", "engine"] and len(parts) > 2 \
                        and parts[2] in BACKENDS:
                    hits.append(f"{path}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            parts = (node.module or "").split(".")
            if parts[:2] == ["nexuusbot", "engine"] and (
                    (len(parts) > 2 and parts[2] in BACKENDS)
                    or any(name in BACKENDS for name in names)):
                hits.append(f"{path}: from {node.module} import {', '.join(names)}")
            elif node.level > 0 and (
                    (node.module or "").split(".")[-1] in BACKENDS
                    or any(name in BACKENDS for name in names)):
                hits.append(f"{path}: relative import of {', '.join(names)}")
    return hits


def test_nothing_outside_the_engine_package_imports_a_backend():
    """A backend import anywhere outside src/nexuusbot/engine fails the scan."""
    hits: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(ROOT)
            if relative.parts[:3] == ("src", "nexuusbot", "engine"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            hits.extend(_backend_import_hits(relative, tree))
    assert hits == [], (
        "the engine's backends are importable only inside "
        "src/nexuusbot/engine; found: " + "; ".join(hits))


def test_the_sidecar_command_grammar_is_pinned():
    """One turn spawns exactly the verified v0.23.3 command, contained.

    The safe toolset and the user-config ignore keep the process to the
    desk's own tools; the key is in the child's environment and never in
    argv; the prompt is capped by prompt_for.
    """
    home = _installed_home()
    spy = _SpawnSpy(stdout=_call_events([]))
    context = "the desk's names"
    result = run_turn(context, connection=CONNECTION, home=home, spawn=spy)

    assert result.backend == "sidecar"
    assert result.ok is True
    assert len(spy.calls) == 1
    call = spy.calls[0]
    prompt = prompt_for(context)
    assert call["argv"] == [
        str(_pinned_cli(home)), "chat", "-q", prompt, "--oneshot",
        "--format", "stream-json", "--base-url", "http://127.0.0.1:9/v1",
        "--model", "mock-chat", "-t", "safe", "--ignore-user-config",
    ]
    assert "--yolo" not in call["argv"]
    assert "--api-key" not in call["argv"]
    assert "sk-test" not in " ".join(call["argv"])
    # The key rides the child's environment, set for this child only.
    assert call["env"]["OPENAI_API_KEY"] == "sk-test"
    # The process is contained: its home folder is the side-car folder,
    # every writable location points inside it, and the desk's own
    # variables (a planted key included) are not inherited.
    assert call["cwd"] == home
    assert call["env"]["HOME"] == str(home)
    assert call["env"]["USERPROFILE"] == str(home)
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
                 "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMP", "TEMP",
                 "HERMES_HOME"):
        assert Path(call["env"][name]).is_relative_to(home), name
    assert "AGENTDESK_LLM_KEY" not in call["env"]
    assert result.events[-1]["type"] == "result"


def test_a_planted_desk_secret_is_not_inherited(monkeypatch):
    """The child environment is an allowlist, not a copy of os.environ."""
    home = _installed_home()
    monkeypatch.setenv("AGENTDESK_LLM_KEY", "sk-planted-secret")
    monkeypatch.setenv("AGENTDESK_LLM_BASE", "https://planted.example/v1")
    spy = _SpawnSpy(stdout=_call_events([]))
    run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    env = spy.calls[0]["env"]
    assert "AGENTDESK_LLM_KEY" not in env
    assert "AGENTDESK_LLM_BASE" not in env
    assert "sk-planted-secret" not in json.dumps(env)
    # The plumbing a process needs to start is kept.
    for name in ("PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT"):
        if os.environ.get(name):
            assert env[name] == os.environ[name]


def test_a_turn_parses_events_into_actions_with_ledger_shapes():
    """The result event's calls come out as actions carrying undo kinds."""
    home = _installed_home()
    spy = _SpawnSpy(stdout=_call_events([
        {"tool": "add_card", "args": {"title": "T", "body": "B", "why": "W"}},
        {"tool": "propose_fact", "args": {"text": "F"}},
        {"tool": "desk_names", "args": {}},
    ]))
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert [event["type"] for event in result.events] == [
        "system/init", "text", "result"]
    assert [action.tool for action in result.actions] == [
        "add_card", "propose_fact", "desk_names"]
    assert result.actions[0].undo_kinds == ("card-added",)
    assert result.actions[1].undo_kinds == ("memory-fact", "card-added")
    assert result.actions[2].read_only
    assert result.actions[0].args == {"title": "T", "body": "B", "why": "W"}


def test_unknown_and_incomplete_calls_are_refused_at_the_boundary():
    """A call the vocabulary does not know, or one without its arguments, is named and dropped."""
    home = _installed_home()
    spy = _SpawnSpy(stdout=_call_events([
        {"tool": "format_the_disk", "args": {}},
        {"tool": "add_card", "args": {"body": "no title"}},
    ]))
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert result.actions == ()
    assert "format_the_disk" in result.note
    assert "title" in result.note


def test_a_result_that_is_not_a_tool_array_is_refused():
    """Prose or a broken payload draws no actions and says so."""
    home = _installed_home()
    spy = _SpawnSpy(stdout=_stream({"type": "result", "text": "I did nothing today."}))
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert result.actions == ()
    assert "not a JSON array" in result.note


def test_a_failed_sidecar_turn_is_a_result_not_a_crash():
    """A non-zero exit names its cause in the note and proposes nothing."""
    home = _installed_home()
    spy = _SpawnSpy(returncode=1, stderr="the endpoint refused the key\n")
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert result.backend == "sidecar"
    assert result.ok is False
    assert result.actions == ()
    assert "the endpoint refused the key" in result.note


def test_the_key_is_redacted_from_every_failure_sentence():
    """A child that echoes the key cannot carry it into the note or audit."""
    home = _installed_home()
    spy = _SpawnSpy(returncode=1,
                    stderr=f"the endpoint rejected {CONNECTION.api_key}\n")
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert result.ok is False
    assert CONNECTION.api_key not in result.note
    assert "[the key]" in result.note


def test_a_spawn_that_cannot_start_is_a_failed_result():
    """An OSError from the process spawn never raises into the pass."""
    home = _installed_home()

    def broken_spawn(argv, *, cwd, env, timeout_s):
        """One spawn that cannot start, the Windows missing-file shape."""
        raise FileNotFoundError("the CLI vanished")

    result = run_turn("ctx", connection=CONNECTION, home=home,
                      spawn=broken_spawn)
    assert result.backend == "sidecar"
    assert result.ok is False
    assert result.actions == ()
    assert "could not start" in result.note
    assert "the CLI vanished" in result.note


def test_an_empty_stream_is_a_named_failure():
    """A side-car that answers nothing is a failed turn, never silence."""
    home = _installed_home()
    spy = _SpawnSpy(returncode=0, stdout="")
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert result.ok is False
    assert result.actions == ()
    assert "no events" in result.note


def test_a_sidecar_with_no_connection_is_a_failed_turn():
    """The installed side-car without its endpoint did not run, and says so."""
    home = _installed_home()
    result = run_turn("ctx", connection=None, home=home)
    assert result.backend == "sidecar"
    assert result.ok is False
    assert "no connection" in result.note


def test_absent_sidecar_falls_back_to_the_fixed_loop():
    """Without the venv the turn is one fixed-loop pass, its entries as actions."""
    empty_home = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-absent-"))
    ledger = Ledger(":memory:")
    result = run_turn("ctx", home=empty_home, loop=_FixedLoop(ledger))
    assert result.backend == "fallback"
    assert result.ok is True
    assert [action.tool for action in result.actions] == ["recommend.added"]
    assert result.actions[0].undo_kinds == ("card-added",)
    assert result.actions[0].entry_id is not None
    assert "deskcheck ok" in result.note


def test_a_running_loop_is_never_passed_twice():
    """The fallback refuses while a pass runs: no re-entry, no re-execution."""
    empty_home = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-running-"))
    ledger = Ledger(":memory:")
    loop = _FixedLoop(ledger, running=True)
    result = run_turn("ctx", home=empty_home, loop=loop)
    assert result.backend == "fallback"
    assert result.ok is False
    assert result.actions == ()
    assert loop.passes == 0
    assert ledger.entries(limit=10) == []
    assert "already running" in result.note


def test_without_any_backend_the_turn_is_refused():
    """No side-car and no loop is EngineUnavailable, never a silent pass."""
    empty_home = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-none-"))
    with pytest.raises(EngineUnavailable):
        run_turn("ctx", home=empty_home, loop=None)


def test_the_prompt_is_capped_with_a_visible_marker():
    """A huge context cannot build a command line near the OS limit."""
    prompt = prompt_for("x" * (PROMPT_MAX_CHARS * 3))
    assert len(prompt) <= PROMPT_MAX_CHARS
    assert "cut at this length" in prompt
    # A short context is untouched.
    short = prompt_for("the desk's names")
    assert "cut at this length" not in short


def test_more_calls_than_the_turn_cap_are_refused_by_name():
    """At most MAX_ACTIONS_PER_TURN calls become actions; the rest are named."""
    home = _installed_home()
    calls = [{"tool": "desk_names", "args": {}}] * (MAX_ACTIONS_PER_TURN + 2)
    spy = _SpawnSpy(stdout=_call_events(calls))
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert len(result.actions) == MAX_ACTIONS_PER_TURN
    assert any("past the turn's limit" in sentence for sentence in result.refusals)
    assert "past the turn's limit" in result.note


def test_an_overlong_argument_is_refused_not_truncated():
    """A write past its documented length is refused by name."""
    home = _installed_home()
    spy = _SpawnSpy(stdout=_call_events([
        {"tool": "add_card", "args": {
            "title": "T" * (ARG_MAX_CHARS["title"] + 1), "body": "B",
            "why": "W"}},
        {"tool": "propose_fact", "args": {"text": "F"}},
    ]))
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert [action.tool for action in result.actions] == ["propose_fact"]
    assert any("title is longer than" in sentence for sentence in result.refusals)
    assert "title is longer than" in result.note


def test_output_past_the_stdout_cap_kills_the_process():
    """A runaway child is killed at the cap and the turn answers failed.

    The child is this interpreter, not the side-car: the caps are the
    spawn's own and a real pipe is the only way to prove them.
    """
    home = _installed_home()
    sidecar = engine_pkg.sidecar
    cwd = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-cap-"))
    with pytest.raises(engine_pkg.SidecarError, match="too much output"):
        sidecar._spawn(
            [sys.executable, "-c",
             "import sys; sys.stdout.write('x' * 3000000)"],
            cwd=cwd, env=sidecar.contained_env(home), timeout_s=60)


def test_a_turn_past_its_ceiling_is_killed_and_fails():
    """A hung child is killed at the timeout, never waited out."""
    home = _installed_home()
    sidecar = engine_pkg.sidecar
    cwd = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-timeout-"))
    with pytest.raises(engine_pkg.SidecarError, match="time limit"):
        sidecar._spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=cwd, env=sidecar.contained_env(home), timeout_s=0.5)


def test_a_marker_for_another_tag_is_not_available():
    """The install marker pins the tag this build's grammar was verified on."""
    home = _installed_home()
    engine_pkg.write_marker(home, tag=engine_pkg.pinned_tag(), commit="a" * 40)
    assert engine_pkg.available(home) is True
    engine_pkg.write_marker(home, tag="v9.9.9", commit="b" * 40)
    assert engine_pkg.available(home) is False


def test_unreadable_lines_stay_visible_in_the_stream():
    """A line the grammar cannot read becomes an unreadable event kind."""
    home = _installed_home()
    spy = _SpawnSpy(stdout="not json at all\n")
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert [event["type"] for event in result.events] == ["unreadable"]


def test_availability_is_the_pinned_cli_file_inside_the_home():
    """Availability reads the home given, not the machine, and is False without it."""
    assert run_turn.__module__ == "nexuusbot.engine"
    from nexuusbot.engine import available

    assert available(_installed_home())
    assert not available(Path(tempfile.mkdtemp(prefix="agentdesk-empty-")))


def test_actions_carry_the_desk_vocabulary_only():
    """Every declared tool declares a real undo kind or is read-only."""
    known = {"card-added", "memory-fact"}
    for spec in TOOL_SPECS:
        if spec.read_only:
            assert spec.undo_kinds == ()
        else:
            assert spec.undo_kinds
            assert set(spec.undo_kinds) <= known
    assert {spec.name for spec in TOOL_SPECS} == {
        "desk_names", "add_card", "propose_fact", "desk_probes"}
