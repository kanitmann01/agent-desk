"""The demo readiness tool boots, walks and reports (spec 022, ticket 022-6).

The tool is the spec's measure of "done", so its own contract is pinned
here: it runs hermetically, prints one line per check and the metric
line, exits by the count, and leaves nothing behind (no changed
environment variable, no temporary folder). Which checks pass belongs to
the product; nothing here requires any of them to, so this test is green
on a checkout where the product does not yet have the behaviour.

    tools/demo_readiness.py
"""

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "demo_readiness.py"


@pytest.fixture(scope="module")
def readiness():
    """The tool as a module, by path (tools is not a package)."""
    spec = importlib.util.spec_from_file_location("demo_readiness_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _leftovers() -> list[str]:
    """The walk's temporary folders still present in the temp directory."""
    return sorted(name for name in os.listdir(tempfile.gettempdir())
                  if name.startswith("agentdesk-ready-"))


def test_the_walk_reports_every_check_and_the_metric(readiness, capsys):
    before = {name: os.environ.get(name)
              for name in ("AGENTDESK_DATA",) + readiness.PINNED_EMPTY}
    folders = _leftovers()

    code = readiness.main()

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    verdicts = [line for line in lines if line.startswith(("PASS R", "FAIL R"))]
    # A new check is a new number (spec 022's frozen-list rule); 24 and
    # 25 belong to the sibling slices, so the walk's numbers jump there.
    assert [int(line[6:8]) for line in verdicts] == list(readiness.CHECK_NUMBERS)
    assert len(verdicts) == readiness.CHECK_COUNT
    assert readiness.CHECK_NUMBERS[-1] == 29
    assert all(line.startswith(("PASS R", "FAIL R")) for line in verdicts)
    passed = sum(line.startswith("PASS") for line in verdicts)
    assert lines[-1] == f"METRIC ready={passed}"
    assert code == (0 if passed == readiness.CHECK_COUNT else 1)
    # Nothing the walk touched outlives it.
    assert {name: os.environ.get(name) for name in before} == before
    assert _leftovers() == folders


def test_the_mock_endpoint_lists_models_and_remembers_what_it_was_sent(readiness):
    mock = readiness._load_mock()
    assert "mock-chat" in mock.MODELS
    reply = mock.reply_for(
        "You turn a conversation snippet into a few durable memory facts.\n\ncontent:\n"
        "You: Remember this: The Acme renewal is due December 15\nAssistant: Noted.")
    assert "The Acme renewal is due December 15" in reply
    quiet = mock.reply_for(
        "You turn a conversation snippet into a few durable memory facts.\n\ncontent:\n"
        "You: What changed?\nAssistant: Nothing.")
    assert '"facts": []' in quiet
    # The engine turn gets two calls the boundary's vocabulary knows, so
    # the side-car smoke proves the action path and not only the stream.
    engine = json.loads(mock.reply_for(
        "You act for a small business desk.\n\nThe desk's context:\n{}"))
    assert [call["tool"] for call in engine] == ["desk_names", "add_card"]
