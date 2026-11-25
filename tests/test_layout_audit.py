"""Unit tests for the pure parts of tools/layout_audit.py.

Playwright is not needed and never imported here. The browser probe and the
selftest are exercised by `python tools/layout_audit.py --selftest`; these
tests cover the matrix, coverage accounting, fixture loading and pending
verdict rules that can be checked without a browser.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import layout_audit as audit  # noqa: E402


def _args(**overrides):
    """A CLI namespace with the defaults the pure functions expect."""
    values = {
        "conditions": "fresh",
        "widths": "1024,1280,800,1920",
        "themes": "unkey,coforge,momentuum",
        "routes": "",
        "no_stress": False,
        "only_condition": "",
        "fail_on": "none",
        "allow_partial": False,
        "record_api": "",
        "api_fixture": "",
        "mock_delay_ms": 0,
        "slow_ms": 0,
        "pending_audit": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _matrix_for(planned):
    """One measured matrix row per planned combination."""
    rows = []
    for combo in planned:
        view = combo["view"]
        rows.append({
            "condition": combo["condition"], "width": combo["width"],
            "theme": combo["theme"], "route": view["path"],
            "state": view.get("state", ""), "stress": combo["stress"],
            "status": "measured", "note": "", "http": 200,
            "final_url": "", "ms": 1,
        })
    return rows


def test_build_combos_rejects_unsupported_width():
    """A width outside the four supported viewports is a hard error."""
    with pytest.raises(audit.AuditError, match="unsupported width"):
        audit.build_combos(_args(widths="1500"))


def test_build_combos_rejects_unknown_theme():
    """A theme outside the three shipped themes is a hard error."""
    with pytest.raises(audit.AuditError, match="unsupported theme"):
        audit.build_combos(_args(themes="bogus"))


def test_build_combos_rejects_unknown_condition():
    """A condition outside the fixed list is a hard error."""
    with pytest.raises(audit.AuditError, match="unsupported condition"):
        audit.build_combos(_args(conditions="bogus"))


def test_build_combos_rejects_route_that_matches_nothing():
    """A route filter that matches no view or overlay is a hard error."""
    with pytest.raises(audit.AuditError, match="no route or overlay"):
        audit.build_combos(_args(routes="nomatch-anywhere"))


def test_build_combos_rejects_empty_band():
    """A valid filter combination that yields no rows is a hard error."""
    with pytest.raises(audit.AuditError, match="no combinations"):
        audit.build_combos(_args(conditions="data", widths="800", themes="unkey"))


def test_build_combos_contains_the_three_bands_for_fresh():
    """fresh has base, theme and extreme rows; long-values has only base."""
    fresh = audit.build_combos(_args(conditions="fresh"))
    widths = {(combo["width"], combo["theme"]) for combo in fresh}
    assert (1024, "unkey") in widths
    assert (1280, "coforge") in widths
    assert (800, "unkey") in widths
    long_values = audit.build_combos(_args(conditions="long-values"))
    assert long_values
    assert {combo["width"] for combo in long_values} == {1024, 1280}
    assert {combo["theme"] for combo in long_values} == {"unkey"}


def test_planned_combos_match_each_condition_child():
    """The parent's plan is the union of the children's own plans."""
    args = _args(conditions="fresh,data")
    planned = audit._planned_combos(args, ["fresh", "data"])
    expected = []
    for condition in ("fresh", "data"):
        child = argparse.Namespace(**vars(args))
        child.only_condition = condition
        child.conditions = condition
        expected.extend(audit._combo_key(combo)
                        for combo in audit.build_combos(child))
    assert [audit._combo_key(combo) for combo in planned] == expected


def _seed_run_folder(tmp_path, planned, findings=None):
    """Write the child JSON files a merge reads."""
    (tmp_path / "findings.fresh.json").write_text(
        json.dumps(findings or []), encoding="utf-8")
    (tmp_path / "matrix.fresh.json").write_text(
        json.dumps(planned), encoding="utf-8")


def _finding():
    """One high finding for the fail-on tests."""
    return {
        "kind": "content-spill", "severity": "high", "stress": False,
        "route": "/", "state": "legacy-dashboard", "condition": "fresh",
        "width": 800, "theme": "unkey", "selector": "div.x",
        "container": "div.x", "classes": "x", "text": "x",
        "metrics": {"over": 5}, "rect": {},
    }


def test_merge_outputs_exits_zero_when_every_row_is_measured(tmp_path):
    """A complete matrix and no findings is a clean exit."""
    args = _args(conditions="fresh", widths="800")
    planned = audit._planned_combos(args, ["fresh"])
    _seed_run_folder(tmp_path, _matrix_for(planned))
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 0


def test_merge_outputs_marks_a_missing_row_as_incomplete(tmp_path):
    """A planned row with no matrix row exits 3 even with --fail-on none."""
    args = _args(conditions="fresh", widths="800")
    planned = audit._planned_combos(args, ["fresh"])
    rows = _matrix_for(planned)
    _seed_run_folder(tmp_path, rows[:-1])
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 3


def test_allow_partial_keeps_a_missing_row_from_failing(tmp_path):
    """--allow-partial suppresses the coverage exit code."""
    args = _args(conditions="fresh", widths="800", allow_partial=True)
    planned = audit._planned_combos(args, ["fresh"])
    rows = _matrix_for(planned)
    _seed_run_folder(tmp_path, rows[:-1])
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 0


def test_nonzero_child_exit_is_incomplete_even_with_a_full_matrix(tmp_path):
    """A child failure is coverage evidence even when its matrix is full."""
    args = _args(conditions="fresh", widths="800")
    planned = audit._planned_combos(args, ["fresh"])
    _seed_run_folder(tmp_path, _matrix_for(planned))
    results = [{"condition": "fresh", "exit": 9}]
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, results) == 3


def test_fail_on_high_fails_for_a_high_finding(tmp_path):
    """--fail-on high exits 1 when a high finding is present."""
    args = _args(conditions="fresh", widths="800", fail_on="high")
    planned = audit._planned_combos(args, ["fresh"])
    _seed_run_folder(tmp_path, _matrix_for(planned), [_finding()])
    assert audit._merge_outputs(args, tmp_path, ["fresh"], 0.1, []) == 1


def test_load_api_fixture_reads_a_path_map(tmp_path):
    """The fixture loader returns the path-to-body map, null included."""
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({"/api/dashboard": {"a": 1},
                                "/api/skip": None}), encoding="utf-8")
    loaded = audit._load_api_fixture(path)
    assert loaded["/api/dashboard"] == {"a": 1}
    assert loaded["/api/skip"] is None


def test_load_api_fixture_rejects_a_non_object(tmp_path):
    """A fixture whose top level is a list is a named error."""
    path = tmp_path / "fixture.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(audit.AuditError, match="must be a JSON object"):
        audit._load_api_fixture(path)


def test_pending_verdicts():
    """Every pending verdict is reached by its own evidence shape."""
    control = {"text": "Save", "tag": "button"}
    state = {"control": {"disabled": False}, "indicators": [],
             "labelChanged": False, "ariaBusy": False}
    verdict, _ = audit._pending_verdict(
        control, state, [], [], False, True, ["structure-or-text"])
    assert verdict == "instant"

    verdict, evidence = audit._pending_verdict(
        control, state, [], [], False, False, [])
    assert verdict == "dead"
    assert evidence["signatureChanged"] is False

    busy = dict(state, ariaBusy=True)
    verdict, _ = audit._pending_verdict(control, busy, [{"method": "POST"}], [], False)
    assert verdict == "meets"

    disabled = {"control": {"disabled": True}, "indicators": [],
                "labelChanged": False, "ariaBusy": False}
    verdict, _ = audit._pending_verdict(
        control, disabled, [{"method": "POST"}], [], False)
    assert verdict == "disabled-only"

    verdict, _ = audit._pending_verdict(
        control, state, [{"method": "POST"}], [], False)
    assert verdict == "silent"

    indicator = dict(state, indicators=[{"path": "div.skel", "text": ""}])
    verdict, _ = audit._pending_verdict(
        control, indicator, [{"method": "POST"}], [], False)
    assert verdict == "meets"

    verdict, _ = audit._pending_verdict(control, state, [], [], True)
    assert verdict == "native-dialog"

    wait = dict(state, waitVisible=True)
    verdict, _ = audit._pending_verdict(
        control, wait, [{"method": "POST"}], [], False)
    assert verdict == "meets"

    aria_disabled = {"control": {"disabled": False, "ariaDisabled": "true"},
                     "indicators": [], "labelChanged": False, "ariaBusy": False}
    verdict, _ = audit._pending_verdict(
        control, aria_disabled, [{"method": "POST"}], [], False)
    assert verdict == "disabled-only"


def _signature(**overrides):
    """A complete page signature with one field at a time changed."""
    value = {
        "html": "<body><p>Before</p><button>Act</button></body>",
        "htmlAttrs": [["data-theme", "unkey"]],
        "scroll": [0, 0],
        "location": "/inbox",
        "title": "Inbox, Agent Desk",
    }
    value.update(overrides)
    return value


def test_signature_sees_each_part_of_the_page():
    """Structure, document attributes, scroll, path and hash all count."""
    before = _signature()
    assert audit._signature_changed(before, before) is False
    assert audit._signature_changed(
        before, _signature(html="<body><p>After</p></body>")) is True
    assert audit._signature_changed(
        before, _signature(htmlAttrs=[["data-theme", "coforge"]])) is True
    assert audit._signature_changed(
        before, _signature(scroll=[0, 240])) is True
    assert audit._signature_changed(
        before, _signature(location="/inbox#card-1")) is True
    assert audit._signature_changed(
        before, _signature(title="Card, Agent Desk")) is True


def test_signature_reasons_name_every_change():
    """The reasons list is the readable evidence beside a changed signature."""
    reasons = audit._signature_reasons(_signature(), _signature(
        html="<body>changed</body>", htmlAttrs=[["data-theme", "coforge"]],
        scroll=[0, 10], location="/inbox#card-1", title="Card"))
    assert reasons == ["structure-or-text", "document-attributes", "scroll",
                       "location", "title"]
    assert audit._signature_reasons(_signature(), {"unavailable": "gone"}) == [
        "navigation-or-unavailable"]


def test_box_changed_compares_width_and_height_with_one_pixel_noise():
    """A busy box is flagged only when width or height moves by more than 1px."""
    before = {"width": 100.0, "height": 24.0}
    assert audit._box_changed(before, {"width": 102.0, "height": 24.0}) is True
    assert audit._box_changed(before, {"width": 101.0, "height": 24.0}) is False
    assert audit._box_changed(before, {"width": 100.0, "height": 26.0}) is True
    assert audit._box_changed(before, {"width": 100.5, "height": 24.5}) is False
    assert audit._box_changed(None, before) is False
    assert audit._box_changed(before, {"width": 120.0, "height": 24.0}, True) is False
    assert audit._box_changed(before, {"width": 120.0, "height": 30.0}, True) is True
    assert audit._box_delta(before, {"width": 116.0, "height": 24.0}) == (16.0, 0.0)


def test_pending_fail_thresholds():
    """Silent and dead are high, disabled-only is medium, the rest never fail."""
    silent = [{"verdict": "silent"}]
    dead = [{"verdict": "dead"}]
    disabled = [{"verdict": "disabled-only"}]
    meets = [{"verdict": "meets"}]
    assert audit._pending_fail(silent, "high") is True
    assert audit._pending_fail(dead, "high") is True
    assert audit._pending_fail(disabled, "high") is False
    assert audit._pending_fail(disabled, "medium") is True
    assert audit._pending_fail(meets, "any") is False
    assert audit._pending_fail(silent, "none") is False
    assert audit._pending_fail(dead, "none") is False


def test_overflow_fixture_is_a_local_widget_with_the_planned_overlays():
    """The overflow fixture is a local manual metric and keeps four rows."""
    manifest = json.loads((audit.OVERFLOW_FIXTURE / "manifest.json").read_text(
        encoding="utf-8"))
    widget = manifest["contributes"]["widgets"][0]
    assert widget["dataSource"]["type"] == "manual-metric"
    assert len(manifest["name"]) > 60
    assert (audit.OVERFLOW_FIXTURE / manifest["sample"]).is_file()
    assert audit.OVERFLOW_CONDITIONS == ("plugins", "full")
    args = _args(conditions="plugins,full", widths="1024,1280", themes="unkey")
    combos = audit.build_combos(args)
    overlays = [combo for combo in combos
                if combo["view"].get("state") == "overlay-widget-menu"]
    assert len(overlays) == 4
    assert {combo["condition"] for combo in overlays} == {"plugins", "full"}


def test_relative_records_drop_the_run_folder_prefix(tmp_path):
    """Evidence paths in findings.json are relative to the run folder."""
    path = tmp_path / "crops" / "a.png"
    records = audit._relative_records([{"crop": str(path)}], tmp_path)
    assert records[0]["crop"] == "crops/a.png"
