"""Text has to fit the box: one shorten, then a continuation slide.

The point size stays 14. Shorten uses the presentation timeout.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.presentations.fit import fit_outline, slot_budget
from agentdesk.presentations.ooxml import read_parts
from agentdesk.presentations.writer import slide_texts

RECIPE = json.loads(
    (ROOT / "registry/plugins/presentation-starter/recipes/briefing.json").read_text(encoding="utf-8")
)


def test_the_budget_matches_the_recipe_region_at_14_pt():
    region = [0.9, 1.7, 11.5, 4.6]
    budget = slot_budget(region, 14)
    # 11.5in * 72 / (14 * 0.5) * 1.10, and the height the same way.
    assert budget["charsPerLine"] == 130
    assert budget["lines"] == 21
    assert budget["minPt"] == 14


def test_a_long_reply_is_shortened_once_then_split():
    calls = []

    def shorten(text, limit, timeout):
        calls.append((limit, timeout))
        return text  # still too long, so the slide splits

    outline = {
        "title": "Q3",
        "slides": [
            {"role": "title", "title": "Q3"},
            {"role": "content", "title": "Context", "bullets": ["word " * 800], "notes": "Sources: none."},
            {"role": "closing"},
        ],
    }
    fitted, notes = fit_outline(outline, RECIPE, shorten, 30)
    content = [slide for slide in fitted["slides"] if slide["role"] == "content"]
    assert len(calls) == 1
    assert calls[0][1] == 30
    assert len(content) == 2
    assert content[1]["title"].endswith("(cont.)")
    assert "Context (shortened)" in notes
    assert "Context (cont.)" in notes


def test_the_run_page_lists_a_continuation_and_the_type_stays_14_pt():
    def llm(prompt, timeout=30):
        if "Shorten this" in prompt:
            return "word " * 800
        if "Presentation plan" in prompt:
            return json.dumps({"sections": [
                {"id": "context", "title": "Context"},
                {"id": "findings", "title": "Findings"},
                {"id": "next", "title": "What we do next"},
            ]})
        return json.dumps({
            "title": "Context",
            "bullets": ["word " * 800],
            "citations": [],
        })

    booted = server_harness.Booted(llm=llm)
    booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
    try:
        auth = booted.exchange()
        body = json.loads(booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "the Q3 review",
             "template": "starter", "variant": "dark", "recipe": "briefing"},
            auth,
        )[2])
        assert body["status"] == "ok", body
        assert any(item.endswith("(cont.)") for item in body["artifact"]["fit"])
        page = booted.request("GET", "/agents", auth)[2].decode("utf-8")
        assert "Slides adjusted to fit" in page
        blob = booted.request("GET", f"/agents/runs/{body['id']}/download", auth)[2]
        titles = [row["texts"][0] for row in slide_texts(blob) if row["texts"]]
        assert any(title.endswith("(cont.)") for title in titles)
        xml = b"\n".join(read_parts(blob).values())
        assert b'sz="1400"' in xml
    finally:
        booted.close()
