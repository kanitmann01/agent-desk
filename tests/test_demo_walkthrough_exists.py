"""The demo walkthrough and the presenter script stay real (ticket #69).

The walkthrough script is the demo's regression net and DEMO.md is the
presenter's script; both drift silently if nobody pins them. These
checks are deliberately cheap: the script must parse as Python and name
the surfaces it drives, and DEMO.md must exist and mention every rail
page plus the steps the demo promises. The full path itself is proven
by running `python tools/demo_walkthrough.py`, not by pytest.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "demo_walkthrough.py"
DEMO = ROOT / "DEMO.md"

RAIL_PAGES = ("/inbox", "/assistant", "/activity", "/memory", "/mail",
              "/capabilities", "/plugins", "/peers", "/settings")


def test_the_walkthrough_script_parses_and_names_its_steps():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SCRIPT))  # a SyntaxError fails
    functions = {node.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    for step in ("step_boot", "step_sample_data_on", "step_inbox_actions",
                 "step_endpoint_strict_save", "step_wizard_create",
                 "step_publish", "step_registry_install",
                 "step_connect_workbook", "step_pair", "step_peer_update",
                 "step_customize"):
        assert step in functions, f"the walkthrough lost its {step}"
    # the exit contract: non-zero on any failure
    assert "WALKTHROUGH FAILED" in source and "WALKTHROUGH PASS" in source


def test_demo_md_is_one_morning_and_still_names_where_the_rest_lives():
    """DEMO.md is one person's morning (spec 022), not a tour, so a person
    following it can answer "where did X go" from its appendix: every rail
    page is named, and each step of the older tour that still exists is
    pointed at, not described again."""
    # Line wraps are not meaning: compare with every run of space as one.
    text = " ".join(DEMO.read_text(encoding="utf-8").split())
    for page in RAIL_PAGES:
        assert page in text, f"DEMO.md does not mention {page}"
    for needle in ("Add plugin", "Describe a plugin in plain English",
                   "Publish to the registry", "from the registry",
                   "re-test", "Generate a fresh code", "Pair", "Customize",
                   "Test connection", "agent-desk.cmd", "demo_walkthrough.py",
                   "demo_readiness.py"):
        assert needle in text, f"DEMO.md lost its {needle!r} step"
    # The story itself: three steps, the morning loop, the fallbacks.
    for beat in ("Add your AI key", "Open your sales workbook",
                 "Connect your calendar", "Try it with sample data",
                 "Forget everything", "Learn automatically",
                 "If something fails", "The day before"):
        assert beat in text, f"DEMO.md lost its {beat!r} beat"

