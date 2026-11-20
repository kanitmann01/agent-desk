"""The deck file: a shell plus an outline comes back as a .pptx someone can open.

The seam is the package itself (slide text, notes, relationships) and the
download route. A title-only shell is a synthetic fixture with no brand strings.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.presentations.ooxml import build_shell, read_parts
from agentdesk.presentations.writer import outline_for, package_problems, slide_texts, write_deck

PACK = ROOT / "registry" / "plugins" / "presentation-starter"
RECIPE = json.loads((PACK / "recipes" / "briefing.json").read_text(encoding="utf-8"))
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def test_a_starter_deck_reopens_with_the_recipe_order_and_notes():
    shell = (PACK / "shells" / "starter-dark.pptx").read_bytes()
    before = read_parts(shell)
    blob = write_deck(shell, RECIPE, outline_for("the Q3 review", RECIPE))
    assert package_problems(blob) == []
    rows = slide_texts(blob)
    assert rows[0]["texts"] == ["the Q3 review"]
    assert rows[1]["texts"] == ["Context"]
    assert "Prepared from the desk." in rows[2]["texts"]
    assert rows[2]["notes"] == "Sources: none supplied for this preview."
    assert rows[-1]["texts"] == ["Thank you"]
    assert all("Title goes here" not in " ".join(row["texts"]) for row in rows)
    after = read_parts(blob)
    for name, data in before.items():
        if "slideLayout" in name or "slideMaster" in name:
            assert after[name] == data


def test_a_title_only_shell_is_filled_in_the_recipe_region():
    shell = build_shell(variant="light", body_placeholder=False)
    blob = write_deck(shell, RECIPE, outline_for("a competitor note", RECIPE))
    assert package_problems(blob) == []
    parts = read_parts(blob)
    content = parts["ppt/slides/slide3.xml"].decode("utf-8")
    assert 'name="Body"' in content
    assert 'type="body"' not in content
    assert 'x="822960"' in content and 'y="1554480"' in content
    joined = b"\n".join(parts.values()).decode("utf-8", "replace").lower()
    assert "title goes here" not in joined


def test_the_download_serves_only_the_run_file(tmp_path):
    booted = server_harness.Booted()
    try:
        auth = booted.exchange()
        booted.server.settings.set("llm_base", "http://127.0.0.1:9/v1")
        status, _h, body = booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "the Q3 review",
             "template": "starter", "variant": "dark", "recipe": "briefing"},
            auth,
        )
        payload = json.loads(body)
        assert status == 200 and payload["status"] == "ok"
        run_id = payload["id"]
        status, headers, blob = booted.request("GET", f"/agents/runs/{run_id}/download", auth)
        assert status == 200
        assert headers["Content-Type"] == PPTX
        assert package_problems(blob) == []
        assert slide_texts(blob)[0]["texts"] == ["the Q3 review"]
        rows = [row for row in audit_store.entries(booted.server.audit_conn)
                if row["action"] == "agents.download"]
        assert len(rows) == 1
        assert rows[0]["target"] == "presentation"
        assert "the Q3 review" not in rows[0]["detail"]
        # A foreign path, and a run that never wrote a file, are both a 404.
        status, _h, _b = booted.request("GET", f"/agents/runs/{run_id}/../download", auth)
        assert status == 404
        status, _h, _b = booted.request("GET", "/agents/runs/999/download", auth)
        assert status == 404
        outside = Path(booted.server.presentation_dir) / "escape.pptx"
        outside.write_bytes(b"nope")
        stored = booted.server.agents.get(run_id)
        stored["artifact"]["file"] = "../escape.pptx"
        # The store row is what the route reads; rewrite it through the store's connection.
        booted.server.agents.conn.execute(
            "UPDATE agent_runs SET artifact = ? WHERE id = ?",
            (json.dumps(stored["artifact"]), run_id),
        )
        booted.server.agents.conn.commit()
        status, _h, _b = booted.request("GET", f"/agents/runs/{run_id}/download", auth)
        assert status == 404
    finally:
        booted.close()
