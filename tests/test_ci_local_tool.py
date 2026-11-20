"""The local CI gate is a pinned contract, not a loose script (#60).

GitHub Actions billed per minute and the account's spending limit broke,
so the hosted matrix is replaced by tools/ci_local.py: the same gates,
one command, deterministic environment. These tests pin the contract so
the gate cannot silently lose a check.
"""

import ast
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "ci_local.py"


def _source() -> str:
    return TOOL.read_text(encoding="utf-8")


def test_the_tool_parses_under_the_3_10_grammar():
    ast.parse(_source(), feature_version=(3, 10))


def test_every_gate_of_the_hosted_matrix_is_present():
    source = _source()
    # the exact gates the hosted workflow ran, by their distinctive marks
    for mark in (
        '"pytest"',                 # the suite
        "tools/license_manifest.py",  # the license gate
        '"git", "diff", "--exit-code"',  # the manifest currency check
        "tools/registry_ci.py",     # the registry review
        '"npm", "run", "check"',    # tsc --noEmit
    ):
        assert mark in source, f"the local CI gate lost the {mark} check"


def test_the_environment_is_pinned_for_determinism():
    source = _source()
    for key in ("AGENTDESK_DATA", "AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY",
                "AGENTDESK_LLM_MODEL", "AGENTDESK_REGISTRY", "AGENTDESK_CALENDAR_FILE"):
        assert f'"{key}"' in source, f"the gate does not pin {key}"
    # a fresh data dir per run, removed afterwards
    assert "tempfile.mkdtemp" in source and "shutil.rmtree" in source


def test_the_registry_gate_checks_every_plugin_in_one_call():
    source = _source()
    # registry_ci takes one comma-separated --plugins value; a repeated flag
    # keeps only the last path, which silently shrank the gate to one plugin
    assert '",".join(' in source
    assert 'args += ["--plugins", f"registry/plugins/{name}"]' not in source


def test_the_registry_gate_reviews_the_branch_against_its_base():
    source = _source()
    # Retirement removes ids from the index, so the gate compares the new
    # index to the mainline base and tells the review which removals the
    # archive accounts for. Without the base the history leg is skipped;
    # without the archive every deliberate retirement reads as truncation.
    for mark in (
        '"git", "merge-base", "HEAD", ref',
        '"git", "show", f"{merge.stdout.strip()}:registry/index.json"',
        '"--archive", "archive/plugins"',
        '"--base-index", str(base_index)',
    ):
        assert mark in source, f"the registry gate lost {mark}"


def test_a_missing_check_is_a_failure_never_a_skip():
    source = _source()
    # the gate runner turns every exception into a FAIL line
    assert "except Exception" in source
    # and a failed gate drives the exit code
    assert "return 1" in source
