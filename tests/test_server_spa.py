"""SPA shell serving: the committed build behind "/", its assets, and the
honest fallback.

GET / serves static/spa/index.html when the build exists and the
server-rendered dashboard when it does not; the posture per test comes
from re-pointing app.SPA_DIR (conftest defaults it to nowhere). The last
section reads the COMMITTED bundle in this checkout: it must exist, be
self-hosted only, and carry no inline script, so the strict script CSP
holds without exception.
"""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.server import app as server_app

COMMITTED_SPA_DIR = ROOT / "src" / "agentdesk" / "server" / "static" / "spa"

# What Vite emits for the shell: one external module script, one external
# stylesheet, nothing inline, nothing remote.
SYNTHETIC_INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Agent Desk</title>
<script type="module" crossorigin src="/static/spa/assets/index-deadbeef.js"></script>
<link rel="stylesheet" href="/static/spa/assets/index-deadbeef.css">
</head>
<body><div id="root"></div></body>
</html>
"""


class ShellScan(HTMLParser):
    """Collect script and link tags, counting inline script bodies."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict] = []
        self.inline_script_chars = 0
        self.links: list[dict] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            self.scripts.append(a)
            self._in_script = "src" not in a
        if tag == "link":
            self.links.append(a)

    def handle_data(self, data):
        if self._in_script:
            self.inline_script_chars += len(data.strip())

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False


def _real_spa(monkeypatch):
    monkeypatch.setattr(server_app, "SPA_DIR", COMMITTED_SPA_DIR)


@pytest.fixture()
def booted():
    server = server_harness.Booted()
    try:
        yield server
    finally:
        server.close()


def test_slash_serves_the_spa_shell_when_the_build_exists(booted, monkeypatch, tmp_path):
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text(SYNTHETIC_INDEX, encoding="utf-8")
    monkeypatch.setattr(server_app, "SPA_DIR", spa)
    headers = booted.exchange()
    status, resp_headers, body = booted.request("GET", "/", headers)
    assert status == 200
    assert resp_headers["Content-Type"].startswith("text/html")
    page = body.decode("utf-8")
    scan = ShellScan()
    scan.feed(page)
    # CSP-safe shell: every script external, module-typed, self-hosted.
    assert len(scan.scripts) == 1
    assert scan.scripts[0].get("src") == "/static/spa/assets/index-deadbeef.js"
    assert scan.scripts[0].get("type") == "module"
    assert scan.inline_script_chars == 0
    assert resp_headers["Cache-Control"] == "no-store"


def test_slash_falls_back_to_the_rendered_dashboard_without_a_build(booted, monkeypatch, tmp_path):
    monkeypatch.setattr(server_app, "SPA_DIR", tmp_path / "does-not-exist")
    headers = booted.exchange()
    status, _h, body = booted.request("GET", "/", headers)
    assert status == 200
    page = body.decode("utf-8")
    # The rendered fallback, not the shell: widget articles and its own script.
    assert 'data-widget-id="sales-24h"' in page
    assert "/static/app.js" in page
    assert "static/spa" not in page


def test_spa_assets_serve_with_correct_mime(booted, monkeypatch, tmp_path):
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text(SYNTHETIC_INDEX, encoding="utf-8")
    (spa / "assets" / "index-deadbeef.js").write_text("console.log(1)", encoding="utf-8")
    (spa / "assets" / "index-deadbeef.css").write_text("body{}", encoding="utf-8")
    (spa / "assets" / "logo-deadbeef.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(server_app, "SPA_DIR", spa)
    headers = booted.exchange()
    for path, mime in [
        ("/static/spa/assets/index-deadbeef.js", "text/javascript"),
        ("/static/spa/assets/index-deadbeef.css", "text/css"),
        ("/static/spa/assets/logo-deadbeef.svg", "image/svg+xml"),
    ]:
        status, resp_headers, body = booted.request("GET", path, headers)
        assert status == 200, path
        assert resp_headers["Content-Type"].startswith(mime), path
        assert resp_headers["Cache-Control"] == "no-store", path


def test_spa_assets_refuse_paths_outside_the_build(booted, monkeypatch, tmp_path):
    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text(SYNTHETIC_INDEX, encoding="utf-8")
    monkeypatch.setattr(server_app, "SPA_DIR", spa)
    headers = booted.exchange()
    for path in [
        "/static/spa/../app.py",
        "/static/spa/%2e%2e/app.py",
        "/static/spa/../../pyproject.toml",
        "/static/spa/assets/missing-deadbeef.js",
    ]:
        status, _h, _b = booted.request("GET", path, headers)
        assert status == 404, path


def test_committed_bundle_exists_and_is_referenced():
    """The build artifact is committed, so end users never need node."""
    index = COMMITTED_SPA_DIR / "index.html"
    assert index.is_file(), (
        "static/spa/index.html is missing: run npm ci && npm run build in "
        "frontend/ and commit the output"
    )
    page = index.read_text(encoding="utf-8")
    # No remote resource URLs: the app is offline by construction.
    for banned in ("http://", "https://", "//cdn."):
        assert banned not in page, banned
    scan = ShellScan()
    scan.feed(page)
    assert scan.inline_script_chars == 0, "no inline script under the strict CSP"
    assert scan.scripts, "the shell must load the SPA bundle"
    for script in scan.scripts:
        src = script.get("src", "")
        assert src.startswith("/static/spa/"), src
        # Every referenced asset is itself committed (no half-committed build).
        relative = src[len("/static/spa/"):]
        assert (COMMITTED_SPA_DIR / relative).is_file(), src
    for link in scan.links:
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        assert href.startswith("/static/spa/") or href.startswith("data:"), href
        if href.startswith("/static/spa/"):
            assert (COMMITTED_SPA_DIR / href[len("/static/spa/"):]).is_file(), href


def test_committed_bundle_references_only_known_static_kinds():
    """Every asset file in the committed build has a served MIME type."""
    if not COMMITTED_SPA_DIR.is_dir():
        pytest.fail("static/spa/ is missing: the SPA build must be committed")
    for asset in COMMITTED_SPA_DIR.rglob("*"):
        if asset.is_file() and asset.name != "index.html":
            suffix = asset.suffix.lower()
            assert suffix in server_app._SPA_MIME, (
                f"{asset.name}: no MIME mapping in app._SPA_MIME"
            )
