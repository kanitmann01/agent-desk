"""Report and stdout-summary rendering tests (pure string building)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from probe_fakes import gate

from nexuusbot.probe.core import (
    FAIL,
    GATE_EDR,
    GATE_EXEC,
    GATE_FLOW,
    GATE_KEYS,
    GATE_ONEDRIVE,
    GATE_UV,
    PASS,
    UNKNOWN,
)
from nexuusbot.probe.report import render_report, render_summary
from nexuusbot.probe.verdict import aggregate_verdict, verdict_line

CONTEXT = {
    "generated": "2026-01-01 12:00:00",
    "python": "3.14.0",
    "platform": "Windows-10",
    "user": "probe.user",
    "workdir": r"C:\Users\probe.user\probe-run",
}


def sample_results():
    return [
        gate(
            GATE_EXEC,
            1,
            PASS,
            evidence=("command: python -I probe_hello.py", "rc=0, stdout: PROBE_OK"),
            title="User-space execution",
        ),
        gate(
            GATE_UV,
            2,
            PASS,
            evidence=("command: uv pip install six", "rc=0, stdout: Installed 1 package"),
        ),
        gate(
            GATE_FLOW,
            3,
            UNKNOWN,
            evidence=("GET https://make.powerautomate.com -> HTTP 200",),
            note="manual check required: try to create a personal cloud flow in the browser",
        ),
        gate(
            GATE_ONEDRIVE,
            4,
            PASS,
            evidence=("sync root: OneDrive - Contoso", "probe file copied"),
            note="sync confirmation is manual",
        ),
        gate(
            GATE_EDR,
            5,
            UNKNOWN,
            evidence=("detection method: tasklist /svc", "none detected"),
            note="no EDR visible to a standard user",
        ),
    ]


class TestReportRendering:
    def test_report_contains_all_five_gates_with_status_and_evidence(self):
        report = render_report(sample_results(), aggregate_verdict(sample_results()), CONTEXT)

        for key in GATE_KEYS:
            assert key in report, f"gate {key} missing from report"
        assert report.count("Status:") == 5
        # Every gate section carries at least one evidence bullet.
        assert report.count("Evidence:") == 5
        assert "- command: python -I probe_hello.py" in report

    def test_final_line_is_exactly_the_verdict_line(self):
        results = sample_results()
        verdict = aggregate_verdict(results)
        report = render_report(results, verdict, CONTEXT)

        final_line = [line for line in report.splitlines() if line.strip()][-1]
        assert final_line == verdict_line(verdict) == "VERDICT: GO"

    def test_blank_line_precedes_the_final_verdict_line(self):
        report = render_report(sample_results(), aggregate_verdict(sample_results()), CONTEXT)

        assert report.endswith("\n\nVERDICT: GO\n")

    def test_reshape_report_final_line_names_failed_gates(self):
        results = sample_results()
        results[1] = gate(GATE_UV, 2, FAIL, evidence=("install failed",))
        verdict = aggregate_verdict(results)
        report = render_report(results, verdict, CONTEXT)

        final_line = [line for line in report.splitlines() if line.strip()][-1]
        assert final_line.startswith("VERDICT: RESHAPE (")
        assert "gate 2" in final_line

    def test_notes_are_included_for_manual_gates(self):
        report = render_report(sample_results(), aggregate_verdict(sample_results()), CONTEXT)

        assert "manual check required" in report

    def test_report_includes_context_header(self):
        report = render_report(sample_results(), aggregate_verdict(sample_results()), CONTEXT)

        assert "# Nexuus Bot environment probe" in report
        assert "2026-01-01 12:00:00" in report
        assert "3.14.0" in report

    def test_report_carries_no_old_product_name(self):
        report = render_report(sample_results(), aggregate_verdict(sample_results()), CONTEXT)

        for form in ("Agent Desk", "AgentDesk", "agent-desk"):
            assert form not in report

    def test_gate_headings_use_title_and_keep_the_machine_key(self):
        report = render_report(sample_results(), aggregate_verdict(sample_results()), CONTEXT)

        assert "## Gate 1: User-space execution (exec-user-space)" in report
        # The summary section keeps bare keys so tools can parse it.
        assert "- Gate 1 (exec-user-space): PASS" in report


class TestStdoutSummary:
    def test_summary_lists_each_gate_and_ends_with_verdict(self):
        results = sample_results()
        verdict = aggregate_verdict(results)
        summary = render_summary(results, verdict)
        lines = summary.strip().splitlines()

        assert lines[-1] == "VERDICT: GO"
        gate_lines = [line for line in lines if line.startswith("Gate ")]
        assert len(gate_lines) == 5
        assert any(
            line.startswith("Gate 1: User-space execution")
            and "(exec-user-space)" in line
            and line.endswith(": PASS")
            for line in gate_lines
        )

    def test_summary_includes_go_notes(self):
        results = sample_results()
        results[1] = gate(GATE_UV, 2, UNKNOWN, note="install uv manually per the docs")
        verdict = aggregate_verdict(results)
        summary = render_summary(results, verdict)

        assert "uv" in summary
        assert lines_verdict(summary) == verdict_line(verdict)

    def test_summary_opens_with_the_product_name(self):
        summary = render_summary(sample_results(), aggregate_verdict(sample_results()))

        assert summary.splitlines()[0] == "Nexuus Bot environment probe"


def lines_verdict(text):
    return [line for line in text.splitlines() if line.strip()][-1]
