"""Unit tests for the pure parts of tools/feedback_walkthrough.py.

Playwright is not needed and never launched here. The walk itself is the
browser proof; these tests cover the verdict rules, the six-action plan,
the manifest shape and the path rewriting that the photographs rely on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import feedback_walkthrough as walk  # noqa: E402


def _record(present: bool = True, required: bool = True) -> dict:
    """One record whose early, late and result facts all pass."""
    return {
        "id": "dashboard-research",
        "title": "Dashboard command bar: Research",
        "route": "/",
        "required": required,
        "present": present,
        "early": {
            "busy": True, "pending": True, "same_shape": True,
            "phase": "Asking your AI for a sourced summary", "slow": False,
        },
        "late": {
            "busy": True, "pending": True, "phase": "Asking your AI...",
            "slow": True,
        },
        "result": {
            "ok": True, "pending": False, "idle": True,
        },
        "failures": [],
    }


def _snapshot(**overrides) -> dict:
    """A result snapshot with every action-neutral field present."""
    snapshot = {
        "pending": False, "alerts": [], "answer": [], "reply_count": 0,
        "has_download": False, "has_template": False, "has_degraded": False,
    }
    snapshot.update(overrides)
    return snapshot


def test_the_plan_has_seven_named_actions():
    """The walk plans seven actions; four of them are required."""
    assert [action.id for action in walk.ACTIONS] == [
        "dashboard-research", "dashboard-explain", "dashboard-reply",
        "assistant-ask", "agents-presentation", "wizard-describe", "inbox-draft",
    ]
    required = [action.id for action in walk.ACTIONS if action.required]
    assert required == ["dashboard-research", "assistant-ask",
                        "agents-presentation", "wizard-describe"]


def test_wizard_action_uses_the_describe_form_and_records_the_shape():
    """The wizard action reads the shape and phase facts, not a fixed label."""
    action = next(item for item in walk.ACTIONS if item.id == "wizard-describe")
    assert action.route == "/wizard"
    assert action.mode == "server"
    assert action.fill_selector == "#wizard-description"
    assert 'form[action="/wizard/new/answer"]' in action.trigger
    assert action.region == "main#main"
    assert action.answer == ".aq"
    assert action.result_control == 'form.answer button[type="submit"]'
    assert "data-wait-shape" in walk.SNAPSHOT_JS
    assert "wait_shape" in walk.SNAPSHOT_JS


def test_verdict_met_when_every_rule_holds():
    """A complete early, late and result is the one met case."""
    status, failures = walk._verdict(_record())
    assert status == "met"
    assert failures == []


def test_verdict_absent_optional_does_not_fail():
    """An optional control that is not on the desk is absent, not a failure."""
    status, failures = walk._verdict(_record(present=False, required=False))
    assert status == "absent"
    assert failures == []


def test_verdict_absent_required_is_not_met():
    """A required control that is missing is a failed promise."""
    status, failures = walk._verdict(_record(present=False, required=True))
    assert status == "not met"
    assert "required" in failures[0]


@pytest.mark.parametrize("section,key,bad,needle", [
    ("early", "busy", False, "not busy"),
    ("early", "pending", False, "no placeholder"),
    ("early", "same_shape", False, "shaped wire lines"),
    ("early", "phase", "", "no phase line"),
    ("early", "slow", True, "too soon"),
    ("late", "busy", False, "stopped being busy"),
    ("late", "pending", False, "no placeholder"),
    ("late", "slow", False, "longer-than-usual"),
    ("result", "ok", False, "no successful result"),
    ("result", "pending", True, "still visible"),
    ("result", "idle", False, "still busy"),
])
def test_verdict_names_each_missing_rule(section, key, bad, needle):
    """Every rule has its own failure sentence, not one generic refusal."""
    record = _record()
    record[section][key] = bad
    status, failures = walk._verdict(record)
    assert status == "not met"
    assert any(needle in failure for failure in failures)


def test_result_ready_waits_for_the_placeholder_to_go():
    """A pending snapshot is never a result, even if an old answer remains."""
    action = walk.ACTIONS[0]
    snapshot = _snapshot(pending=True, answer=["old answer"])
    assert walk._result_ready(action, snapshot) is False
    assert walk._result_ready(action, _snapshot(answer=["new answer"])) is True


def test_research_result_accepts_an_answer_and_refuses_an_alert():
    """The research result is the answer paragraph, not its alert line."""
    action = next(item for item in walk.ACTIONS if item.id == "dashboard-research")
    assert walk._result_ok(action, _snapshot(answer=["The summary."])) is True
    assert walk._result_ok(action, _snapshot(answer=[""], alerts=["No answer."])) is False


def test_assistant_result_refuses_a_degraded_turn():
    """An assistant reply counts only when it is not the degraded line."""
    action = next(item for item in walk.ACTIONS if item.id == "assistant-ask")
    assert walk._result_ok(
        action, _snapshot(reply_count=1, answer=["A real answer."])) is True
    assert walk._result_ok(
        action, _snapshot(reply_count=1, has_degraded=True)) is False


def test_presentation_result_names_the_deck():
    """A deck download or template line is the presentation's result."""
    action = next(item for item in walk.ACTIONS if item.id == "agents-presentation")
    assert walk._result_ok(action, _snapshot(has_download=True)) is True
    assert walk._result_ok(action, _snapshot(has_template=True)) is True
    assert walk._result_ok(
        action, _snapshot(has_template=True, has_degraded=True)) is False


def test_metric_line_uses_the_parent_spelling():
    """The metric line keeps the hyphenated not-met key the parent parses."""
    records = [_record(), _record(present=False, required=False)]
    records[1]["status"] = "absent"
    records[0]["status"] = "met"
    assert walk._metric_line(records) == (
        "METRIC actions=2 met=1 not-met=0 absent=1")


def test_counts_ignore_unknown_statuses():
    """Only the three verdicts are counted."""
    assert walk._counts([
        {"status": "met"}, {"status": "absent"}, {"status": "not met"},
        {"status": "pending"},
    ]) == {"met": 1, "not met": 1, "absent": 1}


def test_manifest_fails_when_a_present_action_fails():
    """One not-met record makes the manifest verdict fail."""
    records = [_record(), _record()]
    records[0]["status"] = "met"
    records[1]["status"] = "not met"
    document = walk._manifest(records, {"mock_delay_ms": 12000})
    assert document["verdict"] == "fail"
    assert document["counts"] == {"met": 1, "not met": 1, "absent": 0}
    assert document["tool"] == "feedback_walkthrough"


def test_manifest_passes_with_optional_absences():
    """An optional absence does not turn the run red."""
    records = [_record(), _record(present=False, required=False)]
    records[0]["status"] = "met"
    records[1]["status"] = "absent"
    document = walk._manifest(records, {"mock_delay_ms": 12000})
    assert document["verdict"] == "pass"


def test_relative_records_keep_only_the_photo_suffix(tmp_path):
    """A photo path in the manifest is relative to the run folder."""
    path = tmp_path / "photos" / "dashboard-research-early.png"
    records = [{"photos": {"early": str(path), "late": ""}}]
    relative = walk._relative_records(records, tmp_path)
    assert relative[0]["photos"]["early"] == "photos/dashboard-research-early.png"
    assert relative[0]["photos"]["late"] == ""


def test_manifest_is_json_serializable():
    """Every record and the manifest itself survive a JSON round trip."""
    record = _record()
    record["status"] = "met"
    document = walk._manifest([record], {"mock_delay_ms": 12000})
    assert json.loads(json.dumps(document))["actions"][0]["status"] == "met"
