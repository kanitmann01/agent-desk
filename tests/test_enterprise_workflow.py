"""The hosted workflow is a pinned contract, like the local gate.

The registry is the product's supply chain, and the append-only history
check is the one leg that needs the base branch's index. These tests pin
that enterprise.yml runs the same registry tool the local gate runs,
over every plugin, against a base index: without the job, a PR deleting
an old release merges green (audit tooling F2). The vendored-source grep
extension is pinned here too (audit tooling F8): the SBOM sees packages,
the grep is the tripwire for a component pasted in beside them.
"""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "enterprise.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_workflow_runs_the_registry_review_over_every_plugin():
    text = workflow_text()
    # the same tool the local gate runs, so the validator stays byte-identical
    assert "tools/registry_ci.py" in text
    assert "--plugins" in text
    assert "registry/plugins" in text


def test_the_registry_review_checks_history_against_the_base_branch():
    text = workflow_text()
    # the append-only check bites only when CI hands the tool the base
    # index; a PR deleting an old release must fail this job
    for mark in ("merge-base", "registry/index.json", "--base-index", "--archive"):
        assert mark in text, f"the registry review lost {mark}"


def test_the_vendored_source_sweep_names_the_strong_copyleft_licences():
    text = workflow_text()
    # AGPL and SSPL can never be excepted by the license gate; the grep
    # extends the same tripwire to files that never pass through the SBOM
    for mark in ("AGPL", "SSPL", "commons"):
        assert mark in text, f"the vendored-source sweep lost {mark}"
