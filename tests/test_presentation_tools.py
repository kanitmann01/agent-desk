"""The deck tools a plugin declares, run by the host and nothing else.

The seam is the tool layer: a catalog built from a template pack's
manifest, four operations with host-owned schemas, and one root folder
that every path stays inside. No plugin code executes.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.presentations.tools import (
    ToolError,
    build_deck,
    inspect_file,
    render_file,
    resolve_in_root,
    run_tool,
    tool_catalog,
)


def _catalog():
    return {row["name"]: row for row in tool_catalog()}


def test_the_shipped_pack_declares_the_four_deck_tools():
    catalog = _catalog()
    assert list(catalog) == [
        "presentation_outline",
        "presentation_create",
        "presentation_inspect",
        "presentation_render",
    ]
    assert catalog["presentation_create"]["plugin"] == "presentation-starter"
    assert catalog["presentation_create"]["template"] == "starter"
    assert catalog["presentation_create"]["inputSchema"]["additionalProperties"] is False


def test_outline_returns_slides_from_a_brief(tmp_path):
    result = run_tool("presentation_outline", {"brief": "the Q3 business review"}, tmp_path)
    assert result["template"] == "starter"
    assert result["recipe"] == "briefing"
    assert result["outline"]["title"] == "the Q3 business review"
    assert len(result["outline"]["slides"]) >= 3


def test_create_writes_a_valid_deck_under_the_root(tmp_path):
    result = run_tool(
        "presentation_create",
        {"brief": "the Q3 business review", "render": False},
        tmp_path,
    )
    path = tmp_path / result["file"]
    assert path.is_file()
    assert result["file"].startswith("tool-")
    assert result["file"].endswith("/deck.pptx")
    assert result["slides"] >= 3
    assert result["bytes"] > 10_000
    assert zipfile.is_zipfile(path)

    seen = run_tool("presentation_inspect", {"file": result["file"]}, tmp_path)
    assert seen["ok"] is True
    assert seen["problems"] == []
    assert len(seen["slides"]) == result["slides"]


def test_create_uses_a_supplied_outline(tmp_path):
    outline = {
        "title": "A named deck",
        "slides": [
            {"role": "title", "title": "A named deck"},
            {"role": "content", "title": "One point", "bullets": ["Only this"]},
        ],
    }
    result = run_tool("presentation_create", {"outline": outline}, tmp_path)
    seen = run_tool("presentation_inspect", {"file": result["file"]}, tmp_path)
    flat = [text for slide in seen["slides"] for text in slide["texts"]]
    assert "A named deck" in flat
    assert "One point" in flat
    assert "Only this" in flat


def test_create_requires_a_brief_or_an_outline(tmp_path):
    with pytest.raises(ToolError) as caught:
        run_tool("presentation_create", {}, tmp_path)
    assert caught.value.status == 400


def test_an_unknown_tool_is_a_404(tmp_path):
    with pytest.raises(ToolError) as caught:
        run_tool("presentation.delete", {}, tmp_path)
    assert caught.value.status == 404


def test_a_tool_no_pack_declares_is_not_runnable(tmp_path):
    with pytest.raises(ToolError) as caught:
        run_tool("presentation_outline", {"brief": "x"}, tmp_path, packs=[])
    assert caught.value.status == 404
    assert "declares" in caught.value.message


def test_an_unknown_field_is_refused(tmp_path):
    with pytest.raises(ToolError) as caught:
        run_tool("presentation_outline", {"brief": "x", "shell": "rm -rf"}, tmp_path)
    assert caught.value.status == 400
    assert "shell" in caught.value.message


def test_an_unknown_recipe_is_a_404(tmp_path):
    with pytest.raises(ToolError) as caught:
        run_tool(
            "presentation_outline",
            {"brief": "x", "recipe": "no-such-recipe"},
            tmp_path,
        )
    assert caught.value.status == 404


def test_resolve_in_root_refuses_traversal_and_absolute_paths(tmp_path):
    (tmp_path / "deck.pptx").write_bytes(b"x")
    for raw in ("../deck.pptx", "/etc/passwd", "C:/deck.pptx", "C:\\deck.pptx", ""):
        with pytest.raises(ToolError) as caught:
            resolve_in_root(tmp_path, raw)
        assert caught.value.status in (400, 404)
    assert resolve_in_root(tmp_path, "deck.pptx").name == "deck.pptx"


def test_resolve_in_root_can_allow_a_pdf_for_download(tmp_path):
    (tmp_path / "preview").mkdir()
    (tmp_path / "preview" / "deck.pdf").write_bytes(b"%PDF")
    found = resolve_in_root(tmp_path, "preview/deck.pdf", suffixes=(".pptx", ".pdf", ".png"))
    assert found.name == "deck.pdf"
    with pytest.raises(ToolError):
        resolve_in_root(tmp_path, "preview/deck.pdf")


def test_render_without_an_office_renderer_says_so(tmp_path):
    created = run_tool("presentation_create", {"brief": "the Q3 review"}, tmp_path)
    result = run_tool("presentation_render", {"file": created["file"]}, tmp_path)
    assert result["file"] == created["file"]
    assert result["renderer"] in ("none", "powerpoint", "libreoffice")
    if result["renderer"] == "none":
        assert result["pdf"] == ""
        assert result["images"] == []
        assert result["note"]


def test_inspect_says_what_is_wrong_with_a_broken_package(tmp_path):
    broken = tmp_path / "broken.pptx"
    with open(broken, "wb") as handle:
        with zipfile.ZipFile(handle, "w") as archive:
            archive.writestr("hello.txt", "not a deck")
    result = inspect_file(broken)
    assert result["ok"] is False
    assert result["problems"]


def test_build_deck_refuses_an_unknown_variant(tmp_path):
    pack = next(pack for pack in _packs())
    with pytest.raises(ToolError) as caught:
        build_deck(
            {"title": "x", "slides": [{"role": "title", "title": "x"}]},
            pack, "briefing", "neon", tmp_path,
        )
    assert caught.value.status == 400


def _packs():
    from agentdesk.presentations.packs import load_packs

    return load_packs()
