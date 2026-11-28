"""The first-plugin smoke injects inert runners before any server can start."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "smoke_first_plugin.py"


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


def _install_fake_host(monkeypatch, factory):
    """Close every import the boot uses, so no production runner can execute."""
    host = types.ModuleType("nexuusbot")
    host.__path__ = []
    server_package = types.ModuleType("nexuusbot.server")
    server_package.__path__ = []
    server_app = types.ModuleType("nexuusbot.server.app")
    server_app.create_server = factory.create_server
    server_package.app = server_app
    probe_package = types.ModuleType("nexuusbot.probe")
    probe_package.__path__ = []
    core = types.ModuleType("nexuusbot.probe.core")
    core.GateResult = _GateResult
    core.UNKNOWN = "UNKNOWN"
    capabilities = types.ModuleType("nexuusbot.capabilities")
    capabilities.GATES = (
        ("exec-user-space", 1, "User-space execution"),
        ("uv-tls-bootstrap", 2, "uv bootstrap under corporate TLS"),
        ("power-automate-flows", 3, "Power Automate personal cloud flows"),
        ("onedrive-sync", 4, "OneDrive sync root"),
        ("edr-identity", 5, "EDR / AV identity"),
        ("embeddings", 6, "Endpoint embeddings"),
    )
    for module in (host, server_package, server_app, probe_package, core,
                   capabilities):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def test_boot_passes_every_inert_gate_runner(tmp_path, monkeypatch):
    """The smoke reaches its factory, injects every UNKNOWN runner, and stops."""
    factory = _ServerFactory()
    _install_fake_host(monkeypatch, factory)
    spec = importlib.util.spec_from_file_location(
        "smoke_first_plugin_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "before"))
    with pytest.raises(_BootStopped):
        module.main()
    assert len(factory.create_calls) == 1
    runners = factory.create_calls[0].get("gate_runners")
    assert runners is not None
    assert set(runners) == {key for key, _number, _title in
                            sys.modules["nexuusbot.capabilities"].GATES}
    assert {runner().status for runner in runners.values()} == {"UNKNOWN"}
