"""The side-car smoke's honest absence path (spec 023, ticket 023-3).

The smoke itself is opt-in evidence a person runs on a machine with the
side-car installed; no test ever starts the real side-car. What the
suite can pin hermetically is the refusal: on a machine without the
pinned venv the tool says so, names the installer, and exits non-zero
without running a turn or touching a real data folder.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "engine_sidecar_check.py"


def _minimal_env() -> dict[str, str]:
    """The pinned environment a subprocess needs, with the desk unconfigured."""
    needed = ("SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOMEDRIVE",
              "HOMEPATH", "USERPROFILE", "LOCALAPPDATA")
    env = {name: os.environ[name] for name in needed if name in os.environ}
    env["AGENTDESK_DATA"] = ""
    return env


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
    keys_package = types.ModuleType("agentdesk.keys")
    keys_package.__path__ = []
    secrets = types.ModuleType("agentdesk.keys.secrets")

    class KeychainSecrets:
        def __init__(self, backend):
            self.backend = backend

    class MemoryKeychain:
        pass

    secrets.KeychainSecrets = KeychainSecrets
    secrets.MemoryKeychain = MemoryKeychain
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
    for module in (agentdesk, server_package, server_app, keys_package, secrets,
                   probe_package, core, capabilities):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def test_temp_desk_boot_passes_every_inert_gate_runner(tmp_path, monkeypatch):
    """The throwaway desk injects every UNKNOWN runner and starts no sidecar."""
    factory = _ServerFactory()
    _install_fake_agentdesk(monkeypatch, factory)
    spec = importlib.util.spec_from_file_location(
        "engine_sidecar_check_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "before"))
    with pytest.raises(_BootStopped):
        module._boot_temp_desk(tmp_path)
    assert len(factory.create_calls) == 1
    runners = factory.create_calls[0].get("gate_runners")
    assert runners is not None
    assert set(runners) == {key for key, _number, _title in
                            sys.modules["agentdesk.capabilities"].GATES}
    assert {runner().status for runner in runners.values()} == {"UNKNOWN"}


def test_the_smoke_names_the_refusal_without_the_sidecar():
    """No installed venv: the tool refuses by name and points at the installer."""
    with tempfile.TemporaryDirectory(prefix="agentdesk-smoke-absent-") as folder:
        result = subprocess.run(
            [sys.executable, str(TOOL), "--home", folder],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
            env=_minimal_env(),
        )
        output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "no side-car is installed" in output
    assert "install_engine_sidecar.py" in output
    assert "PASS" not in output
