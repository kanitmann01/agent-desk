"""The engine boundary's contract: one call runs a turn, two backends behind it.

These tests drive the boundary's public surface only (spec 023, ticket
023-3): the side-car is exercised through an injected spawn, so no test
ever starts the real process, and the fixed-loop fallback through the
smallest stand-in for the supervised loop. The boundary scan is the
other half of the contract: nothing outside src/agentdesk/engine may
import a backend by name, and this file holds itself to the same rule,
which is why even the command grammar is pinned through run_turn.
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

from agentdesk.engine import (
    ConnectionSpec,
    EngineUnavailable,
    TOOL_SPECS,
    prompt_for,
    run_turn,
)
from agentdesk.ledger.store import Ledger

# The backend modules only the engine package may name.
BACKENDS = ("sidecar", "fallback")
# The live trees the scan walks: the product, its tools and scripts, and
# the tests that hold the rule.
SCAN_ROOTS = (
    ROOT / "src" / "agentdesk",
    ROOT / "tools",
    ROOT / "scripts",
    ROOT / "tests",
)

CONNECTION = ConnectionSpec(base_url="http://127.0.0.1:9/v1", api_key="sk-test",
                            model="mock-chat")


class _FixedLoop:
    """The smallest stand-in for the supervised loop: one pass, one entry."""

    def __init__(self, ledger: Ledger) -> None:
        """Hold the ledger the pass records into."""
        self.ledger = ledger

    def run_pass(self) -> list[dict]:
        """Record one undoable change and answer today's step-row shape."""
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
                if parts[:2] == ["agentdesk", "engine"] and len(parts) > 2 \
                        and parts[2] in BACKENDS:
                    hits.append(f"{path}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            parts = (node.module or "").split(".")
            if parts[:2] == ["agentdesk", "engine"] and (
                    (len(parts) > 2 and parts[2] in BACKENDS)
                    or any(name in BACKENDS for name in names)):
                hits.append(f"{path}: from {node.module} import {', '.join(names)}")
            elif node.level > 0 and (
                    (node.module or "").split(".")[-1] in BACKENDS
                    or any(name in BACKENDS for name in names)):
                hits.append(f"{path}: relative import of {', '.join(names)}")
    return hits


def test_nothing_outside_the_engine_package_imports_a_backend():
    """A backend import anywhere outside src/agentdesk/engine fails the scan."""
    hits: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(ROOT)
            if relative.parts[:3] == ("src", "agentdesk", "engine"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            hits.extend(_backend_import_hits(relative, tree))
    assert hits == [], (
        "the engine's backends are importable only inside "
        "src/agentdesk/engine; found: " + "; ".join(hits))


def test_the_sidecar_command_grammar_is_pinned():
    """One turn spawns exactly the verified v0.23.3 command, contained."""
    home = _installed_home()
    spy = _SpawnSpy(stdout=_call_events([]))
    context = "the desk's names"
    result = run_turn(context, connection=CONNECTION, home=home, spawn=spy)

    assert result.backend == "sidecar"
    assert len(spy.calls) == 1
    call = spy.calls[0]
    prompt = prompt_for(context)
    assert call["argv"] == [
        str(_pinned_cli(home)), "chat", "-q", prompt, "--oneshot",
        "--format", "stream-json", "--base-url", "http://127.0.0.1:9/v1",
        "--api-key", "sk-test", "--model", "mock-chat", "--yolo",
    ]
    # The process is contained: its home folder is the side-car folder.
    assert call["cwd"] == home
    assert call["env"]["HOME"] == str(home)
    assert call["env"]["USERPROFILE"] == str(home)
    assert result.events[-1]["type"] == "result"


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
    assert result.actions == ()
    assert "the endpoint refused the key" in result.note


def test_an_empty_stream_is_a_named_failure():
    """A side-car that answers nothing is a failed turn, never silence."""
    home = _installed_home()
    spy = _SpawnSpy(returncode=0, stdout="")
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert result.actions == ()
    assert "no events" in result.note


def test_absent_sidecar_falls_back_to_the_fixed_loop():
    """Without the venv the turn is one fixed-loop pass, its entries as actions."""
    empty_home = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-absent-"))
    ledger = Ledger(":memory:")
    result = run_turn("ctx", home=empty_home, loop=_FixedLoop(ledger))
    assert result.backend == "fallback"
    assert [action.tool for action in result.actions] == ["recommend.added"]
    assert result.actions[0].undo_kinds == ("card-added",)
    assert result.actions[0].entry_id is not None
    assert "deskcheck ok" in result.note


def test_without_any_backend_the_turn_is_refused():
    """No side-car and no loop is EngineUnavailable, never a silent pass."""
    empty_home = Path(tempfile.mkdtemp(prefix="agentdesk-sidecar-none-"))
    with pytest.raises(EngineUnavailable):
        run_turn("ctx", home=empty_home, loop=None)


def test_unreadable_lines_stay_visible_in_the_stream():
    """A line the grammar cannot read becomes an unreadable event kind."""
    home = _installed_home()
    spy = _SpawnSpy(stdout="not json at all\n")
    result = run_turn("ctx", connection=CONNECTION, home=home, spawn=spy)
    assert [event["type"] for event in result.events] == ["unreadable"]


def test_availability_is_the_pinned_cli_file_inside_the_home():
    """Availability reads the home given, not the machine, and is False without it."""
    assert run_turn.__module__ == "agentdesk.engine"
    from agentdesk.engine import available

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
