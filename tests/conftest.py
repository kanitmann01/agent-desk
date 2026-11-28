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

from nexuusbot.server import app as server_app
from nexuusbot.server import memory_api as server_memory_api


@pytest.fixture(autouse=True)
def no_spa_build(monkeypatch, tmp_path):
    """Serve the rendered dashboard under test: SPA_DIR points nowhere.

    The memory api mixin reads its own SPA_DIR import, so both module
    namespaces are repointed."""
    monkeypatch.setattr(server_app, "SPA_DIR", tmp_path / "no-spa-build")
    monkeypatch.setattr(server_memory_api, "SPA_DIR", tmp_path / "no-spa-build")


@pytest.fixture(autouse=True)
def sandbox_localappdata(monkeypatch, tmp_path):
    """Keep every test away from the real Windows notification store.

    A desk built by the app resolves the real notification store through
    LOCALAPPDATA at call time (%LOCALAPPDATA%/Microsoft/Windows/
    Notifications/wpndatabase.db), so a test that turns the mail watcher
    or the Outlook alerts feeder on would otherwise put the real store in
    reach of a poll. The sandbox holds no store, which is also the state
    the feeder's unavailable cause is verified against."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
