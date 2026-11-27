"""The demo walkthrough and the presenter script stay real (ticket #69).

The walkthrough script is the demo's regression net and DEMO.md is the
presenter's script; both drift silently if nobody pins them. These
checks are deliberately cheap: the script must parse as Python and name
the surfaces it drives, and DEMO.md must exist and mention every rail
page plus the steps the demo promises. The full path itself is proven
by running `python tools/demo_walkthrough.py`, not by pytest.
"""
import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

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


class _BootStopped(Exception):
    """Stop the tool immediately after its factory call."""


class _GateResult:
    def __init__(self, key, number, title, status, evidence=(), note=""):
        self.key = key
        self.number = number
        self.title = title
        self.status = status
        self.evidence = tuple(evidence)
        self.note = note


class _ServerFactory:
    def __init__(self):
        self.create_calls = []

    def create_server(self, **kwargs):
        self.create_calls.append(kwargs)
        raise _BootStopped


def _install_fake_agentdesk(monkeypatch, factory):
    """Close every import the boot uses, so no production runner can execute."""
    agentdesk = types.ModuleType("agentdesk")
    agentdesk.__path__ = []
    server_package = types.ModuleType("agentdesk.server")
    server_package.__path__ = []
    server_app = types.ModuleType("agentdesk.server.app")
    server_app.create_server = factory.create_server
    server_package.app = server_app
    probe_package = types.ModuleType("agentdesk.probe")
    probe_package.__path__ = []
    core = types.ModuleType("agentdesk.probe.core")
    core.GateResult = _GateResult
    core.UNKNOWN = "UNKNOWN"
    capabilities = types.ModuleType("agentdesk.capabilities")
    capabilities.GATES = (
        ("exec-user-space", 1, "User-space execution"),
        ("uv-tls-bootstrap", 2, "uv bootstrap under corporate TLS"),
        ("power-automate-flows", 3, "Power Automate personal cloud flows"),
        ("onedrive-sync", 4, "OneDrive sync root"),
        ("edr-identity", 5, "EDR / AV identity"),
        ("embeddings", 6, "Endpoint embeddings"),
    )
    for module in (agentdesk, server_package, server_app, probe_package, core,
                   capabilities):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def test_desk_boot_passes_every_inert_gate_runner(tmp_path, monkeypatch):
    """The shared constructor for Desk A and B injects every UNKNOWN runner."""
    factory = _ServerFactory()
    _install_fake_agentdesk(monkeypatch, factory)
    spec = importlib.util.spec_from_file_location(
        "demo_walkthrough_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "before"))
    with pytest.raises(_BootStopped):
        module.Desk("A", tmp_path / "desk-a", 0)
    assert len(factory.create_calls) == 1
    runners = factory.create_calls[0].get("gate_runners")
    assert runners is not None
    assert set(runners) == {key for key, _number, _title in
                            sys.modules["agentdesk.capabilities"].GATES}
    assert {runner().status for runner in runners.values()} == {"UNKNOWN"}


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

