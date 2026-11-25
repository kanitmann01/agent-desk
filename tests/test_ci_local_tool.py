"""The local CI gate is a pinned contract, not a loose script (#60).

GitHub Actions billed per minute and the account's spending limit broke,
so the hosted matrix is replaced by tools/ci_local.py: the same gates,
one command, deterministic environment. These tests pin the contract so
the gate cannot silently lose a check.
"""

import ast
import sys
import types
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "ci_local.py"


def _source() -> str:
    return TOOL.read_text(encoding="utf-8")


def _gate():
    """Import the gate module so its legs can be run against a fake checkout."""
    if str(TOOL.parent) not in sys.path:
        sys.path.insert(0, str(TOOL.parent))
    import ci_local
    return ci_local


def _grammar_over(checkout: Path):
    """Run the grammar gate with ROOT pointed at a fake checkout."""
    ci_local = _gate()
    saved = ci_local.ROOT
    ci_local.ROOT = checkout
    try:
        return ci_local._grammar_gate({})
    finally:
        ci_local.ROOT = saved


def test_the_tool_parses_under_the_3_10_grammar():
    ast.parse(_source(), feature_version=(3, 10))


def test_the_grammar_gate_covers_worktree_checkouts_and_the_scripts_tree(tmp_path):
    # The skip must be tested against the path below the checkout root,
    # not the absolute path: this repo keeps its worktrees under
    # .worktrees/, and the absolute test skipped the whole tree (the
    # docstring gate relativizes for exactly this reason). The bad file
    # lives in scripts/, which the floor must cover too (audit tooling F3
    # and F7: the baseline worktree run passed on 0 files).
    checkout = tmp_path / ".worktrees" / "gate"
    (checkout / "src").mkdir(parents=True)
    (checkout / "scripts").mkdir()
    (checkout / "src" / "good.py").write_text("X = 1\n", encoding="utf-8")
    (checkout / "scripts" / "bad.py").write_text(
        "try:\n    pass\nexcept* ValueError:\n    pass\n", encoding="utf-8")
    ok, detail = _grammar_over(checkout)
    assert ok is False, "a 3.11-only syntax slip in scripts/ passed the floor"
    assert "bad.py" in detail


def test_the_grammar_gate_fails_when_it_finds_no_files(tmp_path):
    # Three roots with zero Python files can only mean the walk is wrong;
    # an empty pass must never read as a green light.
    checkout = tmp_path / ".worktrees" / "empty"
    (checkout / "src").mkdir(parents=True)
    ok, _detail = _grammar_over(checkout)
    assert ok is False


def test_every_gate_of_the_hosted_matrix_is_present():
    source = _source()
    # the exact gates the hosted workflow runs, by their distinctive marks
    for mark in (
        '"pytest"',                 # the suite
        "scripts/sbom.py",            # the SBOM the license chain reads
        "scripts/license_gate.py",    # the license gate over it
        '"--check"',                 # the notices currency check
        "tools/registry_ci.py",     # the registry review
        '"npm", "run", "check"',    # tsc --noEmit
    ):
        assert mark in source, f"the local CI gate lost the {mark} check"
    # the legacy manifest tool could be factually wrong and still pass
    # its byte-diff gate (audit tooling F6); it is deleted, not watched
    assert "license_manifest" not in source


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


def test_the_pytest_gate_adds_xdist_only_when_it_is_installed():
    ci_local = _gate()
    serial = [ci_local.PYTHON, "-m", "pytest", "tests", "-q", "--no-header"]
    # the fallback is the exact invocation the gate shipped with; xdist only
    # appends its worker flag, so selectors and reported counts stay identical.
    assert ci_local._pytest_args(False) == serial
    parallel = ci_local._pytest_args(True)
    assert parallel[:len(serial)] == serial
    assert parallel[-2] == "-n"
    # eight is the measured stable ceiling on the 20-core Windows host;
    # the flag must stay a positive worker count, never "auto".
    assert parallel[-1].isdigit() and 1 <= int(parallel[-1]) <= 8


def test_the_pytest_gate_reports_which_mode_it_chose(monkeypatch):
    ci_local = _gate()
    seen: list[list[str]] = []

    class _Done:
        returncode = 0
        stdout = "3212 passed, 2 skipped in 120.00s\n"

    def fake_run(args, **_kwargs):
        seen.append(list(args))
        return _Done()

    monkeypatch.setattr(ci_local, "subprocess",
                        types.SimpleNamespace(run=fake_run))
    for parallel, expect_mode in ((True, "parallel -n"),
                                  (False, "serial")):
        monkeypatch.setattr(ci_local, "_xdist_available", lambda p=parallel: p)
        ok, detail = ci_local._pytest_gate({})
        assert ok is True
        assert expect_mode in detail, detail
        assert ("-n" in seen[-1]) is parallel


def test_the_pytest_gate_names_the_tests_that_failed(monkeypatch):
    ci_local = _gate()

    class _Failed:
        returncode = 1
        stdout = (
            "_____ test_a _____\n"
            "E   assert 1 == 2\n"
            "=========================== short test summary info "
            "===========================\n"
            "FAILED tests/test_a.py::test_a - assert 1 == 2\n"
            "FAILED tests/test_b.py::test_b\n"
            "ERROR tests/test_c.py\n"
            "FAILED tests/test_d.py::test_d\n"
            "1 failed, 3507 passed, 1 skipped, 13 warnings in 101.73s\n"
        )

    monkeypatch.setattr(ci_local, "_xdist_available", lambda: True)
    monkeypatch.setattr(
        ci_local, "subprocess", types.SimpleNamespace(run=lambda args, **_kw: _Failed()))
    ok, detail = ci_local._pytest_gate({})
    # the counts stay first, the names follow, and the list is capped so one
    # line still holds the verdict
    assert ok is False
    assert detail.startswith("parallel -n 8: 1 failed, 3507 passed")
    assert "FAILED tests/test_a.py::test_a - assert 1 == 2" in detail
    assert "FAILED tests/test_b.py::test_b" in detail
    assert "ERROR tests/test_c.py" in detail
    assert "test_d" not in detail


def test_the_pytest_gate_keeps_its_summary_when_no_test_line_exists(monkeypatch):
    ci_local = _gate()

    class _Crashed:
        returncode = 2
        stdout = "ERROR: not found: /no/such/dir\n(no match)\n"

    monkeypatch.setattr(
        ci_local, "subprocess", types.SimpleNamespace(run=lambda args, **_kw: _Crashed()))
    ok, detail = ci_local._pytest_gate({})
    assert ok is False
    assert detail.endswith("(no match)")
    assert "|" not in detail
