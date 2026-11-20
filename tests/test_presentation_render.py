"""Optional previews: a fake renderer, a timeout, and a skip when none is installed.

The seam is the run page and the audit line. The deck still downloads
when previews are unavailable.
"""

import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.presentations.ooxml import build_shell
from agentdesk.presentations.render import render_deck

PNG = b"\x89PNG\r\n\x1a\n"


def _ready(booted, runner):
    booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
    booted.server.presentation_runner = runner


def _fake(argv, timeout):
    out = Path(argv[argv.index("--outdir") + 1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "deck.pdf").write_bytes(b"%PDF-1.4")
    (out / "slide1.png").write_bytes(PNG)
    return SimpleNamespace(returncode=0, renderer="libreoffice")


def test_a_fake_renderer_shows_a_preview_and_names_itself():
    booted = server_harness.Booted()
    _ready(booted, _fake)
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "the Q3 review",
             "template": "starter", "variant": "dark", "recipe": "briefing"},
            auth,
        )
        import json
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert payload["artifact"]["renderer"] == "libreoffice"
        page = booted.request("GET", "/agents", auth)[2].decode("utf-8")
        assert "Download PDF" in page
        assert "slide1.png" in page
        run_id = payload["id"]
        status, headers, png = booted.request(
            "GET", f"/agents/runs/{run_id}/download?part=slide1.png", auth
        )
        assert status == 200 and png.startswith(b"\x89PNG")
        rows = [row for row in audit_store.entries(booted.server.audit_conn)
                if row["action"] == "agents.run"]
        assert "renderer libreoffice" in rows[-1]["detail"]
    finally:
        booted.close()


def test_a_missing_renderer_keeps_the_deck_and_says_so():
    def fail(argv, timeout):
        return SimpleNamespace(returncode=1, renderer="none")

    booted = server_harness.Booted()
    _ready(booted, fail)
    try:
        auth = booted.exchange()
        import json
        payload = json.loads(booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "the Q3 review",
             "template": "starter", "variant": "dark", "recipe": "briefing"},
            auth,
        )[2])
        assert payload["status"] == "ok"
        assert payload["artifact"]["renderer"] == "none"
        assert payload["artifact"]["file"].endswith("deck.pptx")
        page = booted.request("GET", "/agents", auth)[2].decode("utf-8")
        assert "Previews are unavailable." in page
        rows = [row for row in audit_store.entries(booted.server.audit_conn)
                if row["action"] == "agents.run"]
        assert "renderer none" in rows[-1]["detail"]
    finally:
        booted.close()


def test_a_hung_renderer_does_not_hold_the_call():
    def hang(argv, timeout):
        time.sleep(timeout + 5)
        return SimpleNamespace(returncode=0)

    shell = build_shell()
    folder = Path("/tmp/agentdesk-render-hang")
    folder.mkdir(exist_ok=True)
    pptx = folder / "deck.pptx"
    pptx.write_bytes(shell)
    started = time.time()
    result = render_deck(pptx, folder / "preview", runner=hang, timeout=0.2)
    assert time.time() - started < 2
    assert result["renderer"] == "none"
    assert result["note"] == "Previews are unavailable."


@pytest.mark.skipif(shutil.which("soffice") is None and shutil.which("libreoffice") is None,
                    reason="no LibreOffice installed")
def test_libreoffice_renders_a_real_deck(tmp_path):
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(build_shell())
    result = render_deck(pptx, tmp_path / "preview")
    assert result["renderer"] == "libreoffice"
    assert (tmp_path / result["pdf"]).is_file()
