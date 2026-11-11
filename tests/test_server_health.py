"""Health endpoint tests through the real HTTP seam.

Health is authenticated like everything else (the ground rule is that the
server authenticates every request) and reports the honest source table:
named sources, none connected in the skeleton.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agentdesk
import server_harness


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def test_health_requires_a_session(booted):
    status, _headers, _body = booted.request("GET", "/health", booted.host_header())
    assert status == 401


def test_health_reports_app_version_sources_and_uptime(booted):
    headers = booted.exchange()
    status, resp_headers, body = booted.request("GET", "/health", headers)
    assert status == 200
    assert resp_headers["Content-Type"].startswith("application/json")
    payload = json.loads(body)
    assert payload["app"] == "agent-desk"
    assert payload["version"] == agentdesk.__version__
    assert payload["uptime_seconds"] >= 0


def test_health_source_table_is_honest(booted):
    headers = booted.exchange()
    _status, _resp_headers, body = booted.request("GET", "/health", headers)
    payload = json.loads(body)
    sources = {s["id"]: s for s in payload["sources"]}
    assert set(sources) == {"excel-watch", "calendar-bridge", "research-endpoint"}
    for source in sources.values():
        assert source["status"] == "not_connected"
        assert source["detail"]
