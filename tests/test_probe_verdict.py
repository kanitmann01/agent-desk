"""Verdict aggregation truth table, exit-code mapping and verdict line format.

Pure logic only: builds GateResults directly, no side effects.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from probe_fakes import gate

from agentdesk.probe.core import (
    EXIT_GO,
    EXIT_NO_GO,
    EXIT_RESHAPE,
    FAIL,
    GATE_EDR,
    GATE_EXEC,
    GATE_FLOW,
    GATE_ONEDRIVE,
    GATE_UV,
    PASS,
    UNKNOWN,
    VERDICT_GO,
    VERDICT_NO_GO,
    VERDICT_RESHAPE,
)
from agentdesk.probe.verdict import aggregate_verdict, verdict_line


def base_gates(**overrides):
    """The five gates with statuses that can be overridden per test."""
    statuses = {
        GATE_EXEC: PASS,
        GATE_UV: PASS,
        GATE_FLOW: UNKNOWN,
        GATE_ONEDRIVE: PASS,
        GATE_EDR: UNKNOWN,
    }
    statuses.update(overrides)
    return [
        gate(GATE_EXEC, 1, statuses[GATE_EXEC]),
        gate(GATE_UV, 2, statuses[GATE_UV]),
        gate(GATE_FLOW, 3, statuses[GATE_FLOW]),
        gate(GATE_ONEDRIVE, 4, statuses[GATE_ONEDRIVE]),
        gate(GATE_EDR, 5, statuses[GATE_EDR]),
    ]


class TestVerdictTruthTable:
    def test_gates_1_and_2_pass_is_go_even_with_manual_unknowns(self):
        verdict = aggregate_verdict(base_gates())

        assert verdict.name == VERDICT_GO
        assert verdict.exit_code == EXIT_GO
        assert verdict_line(verdict) == "VERDICT: GO"

    def test_gate2_unknown_uv_absent_is_go_with_a_note(self):
        g2 = gate(GATE_UV, 2, UNKNOWN, note="install uv manually per the docs")
        gates = base_gates()
        gates[1] = g2

        verdict = aggregate_verdict(gates)

        assert verdict.name == VERDICT_GO
        assert verdict.notes and "uv" in verdict.notes[0].lower()

    def test_gate1_fail_is_no_go_regardless_of_others(self):
        for other in (PASS, FAIL, UNKNOWN):
            verdict = aggregate_verdict(base_gates(**{GATE_EXEC: FAIL, GATE_UV: other}))

            assert verdict.name == VERDICT_NO_GO
            assert verdict.exit_code == EXIT_NO_GO

    def test_gate2_fail_is_reshape_naming_gate_2_and_remediation(self):
        verdict = aggregate_verdict(base_gates(**{GATE_UV: FAIL}))

        assert verdict.name == VERDICT_RESHAPE
        assert verdict.exit_code == EXIT_RESHAPE
        assert "gate 2" in verdict.detail
        assert GATE_UV in verdict.detail
        assert "proxy" in verdict.detail  # remediation clause

    def test_gate3_network_unreachable_is_reshape_naming_gate_3(self):
        verdict = aggregate_verdict(base_gates(**{GATE_FLOW: FAIL}))

        assert verdict.name == VERDICT_RESHAPE
        assert "gate 3" in verdict.detail
        assert GATE_FLOW in verdict.detail

    def test_gate4_not_writable_is_reshape_naming_gate_4(self):
        verdict = aggregate_verdict(base_gates(**{GATE_ONEDRIVE: FAIL}))

        assert verdict.name == VERDICT_RESHAPE
        assert "gate 4" in verdict.detail
        assert GATE_ONEDRIVE in verdict.detail

    def test_reshape_names_every_failed_gate_in_order(self):
        verdict = aggregate_verdict(base_gates(**{GATE_UV: FAIL, GATE_ONEDRIVE: FAIL}))

        assert verdict.name == VERDICT_RESHAPE
        assert "gate 2" in verdict.detail and "gate 4" in verdict.detail
        assert verdict.detail.index("gate 2") < verdict.detail.index("gate 4")

    def test_gate5_never_changes_the_verdict(self):
        for status in (PASS, UNKNOWN):
            verdict = aggregate_verdict(base_gates(**{GATE_EDR: status}))
            assert verdict.name == VERDICT_GO

    def test_input_order_does_not_matter(self):
        gates = base_gates(**{GATE_UV: FAIL})
        shuffled = list(reversed(gates))

        assert aggregate_verdict(shuffled).detail == aggregate_verdict(gates).detail

    def test_missing_gate_is_an_error(self):
        gates = base_gates()
        gates.pop(2)  # drop gate 3

        with pytest.raises(ValueError):
            aggregate_verdict(gates)


class TestVerdictLineFormat:
    def test_go_line_is_exact(self):
        assert verdict_line(aggregate_verdict(base_gates())) == "VERDICT: GO"

    def test_reshape_line_is_single_line_with_detail(self):
        verdict = aggregate_verdict(base_gates(**{GATE_UV: FAIL, GATE_ONEDRIVE: FAIL}))
        line = verdict_line(verdict)

        assert line.startswith("VERDICT: RESHAPE (")
        assert line.endswith(")")
        assert "\n" not in line

    def test_no_go_line_names_gate_1(self):
        line = verdict_line(aggregate_verdict(base_gates(**{GATE_EXEC: FAIL})))

        assert line.startswith("VERDICT: NO-GO (")
        assert "gate 1" in line and GATE_EXEC in line

    def test_exit_codes_map_to_verdicts(self):
        assert EXIT_GO == 0
        assert EXIT_RESHAPE == 3
        assert EXIT_NO_GO == 4
