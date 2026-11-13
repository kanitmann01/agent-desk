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


def test_demo_md_exists_and_covers_the_rail_and_the_story():
    text = DEMO.read_text(encoding="utf-8")
    for page in RAIL_PAGES:
        assert page in text, f"DEMO.md does not mention {page}"
    for needle in ("Add plugin", "Add widget", "Publish to the registry",
                   "From the registry", "Re-test", "Generate a fresh code",
                   "Pair", "Customize", "Test connection",
                   "tools/agent-desk.cmd", "demo_walkthrough.py"):
        assert needle in text, f"DEMO.md lost its {needle!r} step"
