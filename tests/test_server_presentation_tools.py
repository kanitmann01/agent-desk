"""The deck tools over HTTP: list, create, download, and refuse.

The seam is the booted server. A client with a session lists the tools a
plugin declares, runs one without a model endpoint, and fetches the file
back through the same session gate.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.fixture()
def env():
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def _json(body):
    return json.loads(body)


def test_the_catalog_lists_the_declared_tools(env, auth):
    status, _headers, body = env.request("GET", "/api/presentation/tools", auth)
    assert status == 200
    names = [row["name"] for row in _json(body)["tools"]]
    assert names == [
        "presentation_outline",
        "presentation_create",
        "presentation_inspect",
        "presentation_render",
    ]


def test_the_agents_page_names_the_deck_tools(env, auth):
    status, _headers, body = env.request("GET", "/agents", auth)
    assert status == 200
    page = body.decode("utf-8")
    assert "Deck tools (for agents and scripts)" in page
    assert "presentation_create" in page
    assert "agentdesk.presentations.cli" in page


def test_create_writes_a_deck_and_the_url_downloads_it(env, auth):
    status, _headers, body = env.post_json(
        "/api/presentation/tools",
        {"tool": "presentation_create", "brief": "the Q3 business review"},
        auth,
    )
    assert status == 200
    result = _json(body)
    assert result["file"].endswith("/deck.pptx")
    assert result["url"] == "/presentations/files/" + result["file"]
    assert result["slides"] >= 3

    status, headers, deck = env.request("GET", result["url"], auth)
    assert status == 200
    assert headers["Content-Type"] == PPTX
    assert deck[:2] == b"PK"
    assert len(deck) == result["bytes"]


def test_a_file_url_decodes_its_name(env, auth):
    deck = Path(env.server.presentation_dir) / "tool deck.pptx"
    deck.write_bytes(b"PK\x03\x04")
    status, headers, body = env.request(
        "GET", "/presentations/files/tool%20deck.pptx", auth
    )
    assert status == 200
    assert headers["Content-Type"] == PPTX
    assert body == b"PK\x03\x04"


def test_inspect_reads_a_created_deck_back(env, auth):
    _status, _headers, body = env.post_json(
        "/api/presentation/tools",
        {"tool": "presentation_create", "brief": "the Q3 review"},
        auth,
    )
    created = _json(body)
    status, _headers, body = env.post_json(
        "/api/presentation/tools",
        {"tool": "presentation_inspect", "file": created["file"]},
        auth,
    )
    assert status == 200
    seen = _json(body)
    assert seen["ok"] is True
    assert len(seen["slides"]) == created["slides"]


def test_an_unknown_tool_is_a_404(env, auth):
    status, _headers, body = env.post_json(
        "/api/presentation/tools", {"tool": "presentation.delete"}, auth
    )
    assert status == 404
    assert "delete" in _json(body)["error"]


def test_a_body_without_a_tool_is_a_400(env, auth):
    status, _headers, body = env.post_json(
        "/api/presentation/tools", {"brief": "x"}, auth
    )
    assert status == 400
    assert "tool" in _json(body)["error"]


def test_an_unknown_field_is_refused(env, auth):
    status, _headers, body = env.post_json(
        "/api/presentation/tools",
        {"tool": "presentation_outline", "brief": "x", "command": "whoami"},
        auth,
    )
    assert status == 400
    assert "command" in _json(body)["error"]


def test_a_path_outside_the_root_is_refused(env, auth):
    status, _headers, body = env.post_json(
        "/api/presentation/tools",
        {"tool": "presentation_inspect", "file": "../secret.pptx"},
        auth,
    )
    assert status == 400
    assert "inside" in _json(body)["error"]


def test_a_missing_file_url_is_a_404(env, auth):
    status, _headers, body = env.request(
        "GET", "/presentations/files/tool-0000/deck.pptx", auth
    )
    assert status == 404
    assert "not found" in _json(body)["error"]


def test_the_tools_need_the_session_gate(env):
    status, _headers, body = env.request(
        "GET", "/api/presentation/tools", env.host_header()
    )
    assert status == 401
    assert b"Session required" in body
