"""Shared test posture for the server suite.

The committed SPA build decides what GET / serves: the SPA shell when
static/spa/index.html exists, the server-rendered dashboard when it does
not. Tests default to the no-build posture so the dashboard renderers
stay covered exactly as before, whether or not the bundle is present in
this checkout; the SPA tests re-point app.SPA_DIR at the real build.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.server import app as server_app


@pytest.fixture(autouse=True)
def no_spa_build(monkeypatch, tmp_path):
    """Serve the rendered dashboard under test: SPA_DIR points nowhere."""
    monkeypatch.setattr(server_app, "SPA_DIR", tmp_path / "no-spa-build")
