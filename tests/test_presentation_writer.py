"""The deck file: a shell plus an outline comes back as a .pptx someone can open.

The seam is the package itself (slide text, notes, relationships) and the
download route. A title-only shell is a synthetic fixture with no brand strings.
"""

import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.presentations.ooxml import build_shell, pack_zip, read_parts
from agentdesk.presentations.writer import (
    content_point_size, outline_for, package_problems, slide_texts, write_deck,
)

PACK = ROOT / "registry" / "plugins" / "presentation-starter"
RECIPE = json.loads((PACK / "recipes" / "briefing.json").read_text(encoding="utf-8"))
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _scripted_llm():
    """Plan and fill replies so the download test does not need a network."""
    def llm(prompt, timeout=30):
        if "Presentation plan" in prompt:
            return json.dumps({"sections": [
                {"id": "context", "title": "Context"},
                {"id": "findings", "title": "Findings"},
                {"id": "next", "title": "What we do next"},
            ]})
        return json.dumps({
            "title": "From the mock",
            "bullets": ["Prepared from the desk."],
            "citations": [],
        })
    return llm


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
        booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
        booted.server.llm = _scripted_llm()
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
        assert 'attachment; filename="deck.pptx"' in headers["Content-Disposition"]
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


def test_a_dark_layout_keeps_its_art_footer_and_readable_text():
    shell = _dark_shell_with_art()
    before = read_parts(shell)
    outline = outline_for("a launch note \x0bwith a break", RECIPE)
    outline["slides"][0]["title"] = "Launch \x00note"
    blob = write_deck(shell, RECIPE, outline)
    assert package_problems(blob) == []
    after = read_parts(blob)
    for name, data in before.items():
        if "slideLayout" in name or "slideMaster" in name or name == "ppt/media/art.png":
            assert after[name] == data
    slide = after["ppt/slides/slide1.xml"].decode("utf-8")
    assert "Launch note" in slide
    assert "\x00" not in slide and "\x0b" not in slide
    assert "<p:bg>" not in slide
    assert "1C1C1F" not in slide
    assert "Arial" not in slide
    assert 'name="Art"' not in slide
    assert 'name="Footer"' not in slide
    assert "Page footer" in after["ppt/slideLayouts/slideLayout1.xml"].decode("utf-8")
    assert "SAMPLE NOTE LEAK" not in "\n".join(
        data.decode("utf-8", "replace") for data in after.values()
    )
    assert "ppt/media/sample-only.png" not in after
    assert "docProps/thumbnail.jpeg" not in after
    notes_rels = after["ppt/notesMasters/_rels/notesMaster1.xml.rels"].decode("utf-8")
    assert "relationships/theme" in notes_rels
    assert b"KEEPNOTESMASTER" in after["ppt/notesMasters/notesMaster1.xml"]


def test_an_unknown_layout_is_not_named_in_the_error():
    recipe = {"id": "briefing", "slides": [{"role": "title", "layout": "Missing Layout"}]}
    try:
        write_deck(build_shell(), recipe, {"title": "x", "slides": [{"role": "title", "title": "x"}]})
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert "Missing" not in message
    assert "no layout named" not in message


def test_package_problems_catches_duplicates_missing_types_and_skips_external_links():
    good = write_deck(build_shell(), RECIPE, outline_for("a note", RECIPE))
    parts = read_parts(good)
    rels = parts["ppt/_rels/presentation.xml.rels"].decode("utf-8")
    rels = rels.replace(
        "</Relationships>",
        '<Relationship Id="rIdExt" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="https://example.com/deck" TargetMode="External"/></Relationships>',
    )
    parts["ppt/_rels/presentation.xml.rels"] = rels.encode("utf-8")
    assert package_problems(pack_zip(parts)) == []
    broken = dict(parts)
    broken["ppt/media/orphan.bin"] = b"not-typed"
    problems = package_problems(pack_zip(broken))
    assert any("no content type" in item for item in problems)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", b"<p/>")
        archive.writestr("ppt/slides/slide1.xml", b"<p/>")
    assert any("duplicate" in item for item in package_problems(buf.getvalue()))


def test_an_untyped_or_obj_placeholder_is_the_body_at_least_14_pt():
    for ph in ('<p:ph idx="1"/>', '<p:ph type="obj" idx="1"/>'):
        shell = _shell_with_body_tag(ph, "800")
        outline = outline_for("a note", RECIPE)
        outline["slides"][2]["bullets"] = ["Kept \ud800word"]
        blob = write_deck(shell, RECIPE, outline)
        assert package_problems(blob) == []
        slide = read_parts(blob)["ppt/slides/slide3.xml"].decode("utf-8")
        assert 'idx="1"' in slide
        assert 'type="body"' not in slide
        assert 'sz="1400"' in slide
        assert 'indent="-285750"' in slide
        assert "Kept word" in slide
        assert "\ud800" not in slide
        assert content_point_size(shell, RECIPE) == 14
    larger = _shell_with_body_tag('<p:ph idx="1"/>', "1800")
    assert content_point_size(larger, RECIPE) == 18
    written = read_parts(write_deck(larger, RECIPE, outline_for("a note", RECIPE)))
    body = written["ppt/slides/slide3.xml"].decode("utf-8")
    assert 'sz="1800"' not in body
    assert 'sz="1400"' not in body


def test_master_text_styles_set_the_title_and_body_size():
    shell = _office_style_shell()
    blob = write_deck(shell, RECIPE, outline_for("a note", RECIPE))
    assert package_problems(blob) == []
    parts = read_parts(blob)
    slide = parts["ppt/slides/slide3.xml"].decode("utf-8")
    title, body = slide.split('name="Body"', 1)
    assert "sz=" not in title
    assert "sz=" not in body
    assert content_point_size(shell, RECIPE) == 32
    from agentdesk.presentations.writer import _resolved_pt, _find_layout, _placeholder
    layout = _find_layout(parts, "Content")
    # The written package still has the master styles. Resolve from the shell.
    shell_parts = read_parts(shell)
    layout = _find_layout(shell_parts, "Title Slide")
    title_ph = _placeholder(shell_parts[layout], "ctrTitle")
    assert _resolved_pt(shell_parts, layout, title_ph["ph"]) == 44


def _shell_with_body_tag(ph: str, hundredths: str) -> bytes:
    """The starter shell with the content body placeholder rewritten."""
    parts = read_parts(build_shell())
    layout = parts["ppt/slideLayouts/slideLayout3.xml"].decode("utf-8")
    layout = layout.replace('<p:ph type="body" idx="1"/>', ph)
    layout = layout.replace('sz="1400"', f'sz="{hundredths}"')
    parts["ppt/slideLayouts/slideLayout3.xml"] = layout.encode("utf-8")
    return pack_zip(parts)


def _office_style_shell() -> bytes:
    """A Title and Content shell whose sizes live only on the master.

    Layout placeholders declare no size. The master text styles say
    44 pt for titles and 32 pt for body text, which is what a default
    Office template does.
    """
    parts = read_parts(build_shell())
    for name in list(parts):
        if name.startswith("ppt/slideLayouts/") and name.endswith(".xml"):
            parts[name] = re.sub(br'\s*sz="\d+"', b"", parts[name])
    master = parts["ppt/slideMasters/slideMaster1.xml"].decode("utf-8")
    styles = (
        "<p:txStyles>"
        '<p:titleStyle><a:lvl1pPr><a:defRPr sz="4400"/></a:lvl1pPr></p:titleStyle>'
        '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="3200"/></a:lvl1pPr></p:bodyStyle>'
        '<p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle>'
        "</p:txStyles>"
    )
    master = master.replace("</p:sldMaster>", styles + "</p:sldMaster>")
    parts["ppt/slideMasters/slideMaster1.xml"] = master.encode("utf-8")
    return pack_zip(parts)


def _dark_shell_with_art() -> bytes:
    """A dark layout with art and a footer. No brand names, no brand colours."""
    parts = read_parts(build_shell(variant="dark"))
    layout = parts["ppt/slideLayouts/slideLayout1.xml"].decode("utf-8")
    art = (
        '<p:sp><p:nvSpPr><p:cNvPr id="7" name="Art"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:sp>'
        '<p:sp><p:nvSpPr><p:cNvPr id="8" name="Footer"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="40"/></a:xfrm></p:spPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" dirty="0">'
        '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:rPr>'
        '<a:t>Page footer</a:t></a:r></a:p></p:txBody></p:sp>'
    )
    layout = layout.replace('val="1C1C1F"', 'val="111111"').replace("</p:spTree>", art + "</p:spTree>")
    parts["ppt/slideLayouts/slideLayout1.xml"] = layout.encode("utf-8")
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = (
        parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"].decode("utf-8").replace(
            "</Relationships>",
            '<Relationship Id="rIdArt" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="../media/art.png"/></Relationships>',
        )
    ).encode("utf-8")
    parts["ppt/media/art.png"] = b"\x89PNG-art"
    parts["ppt/media/sample-only.png"] = b"\x89PNG-sample"
    parts["ppt/slides/_rels/slide1.xml.rels"] = (
        parts["ppt/slides/_rels/slide1.xml.rels"].decode("utf-8").replace(
            "</Relationships>",
            '<Relationship Id="rIdSample" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="../media/sample-only.png"/>'
            '<Relationship Id="rIdNotes" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" '
            'Target="../notesSlides/notesSlide1.xml"/></Relationships>',
        )
    ).encode("utf-8")
    parts["ppt/notesSlides/notesSlide1.xml"] = b'<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><a xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>SAMPLE NOTE LEAK</a:t></a></p:spTree></p:cSld></p:notes>'
    parts["ppt/notesSlides/_rels/notesSlide1.xml.rels"] = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
    )
    parts["ppt/notesMasters/notesMaster1.xml"] = (
        b'<p:notesMaster xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        b"KEEPNOTESMASTER</p:notesMaster>"
    )
    parts["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
    )
    parts["docProps/thumbnail.jpeg"] = b"\xff\xd8\xff-thumb"
    types = parts["[Content_Types].xml"].decode("utf-8")
    if 'Extension="png"' not in types:
        types = types.replace(
            "</Types>",
            '<Default Extension="png" ContentType="image/png"/>'
            '<Default Extension="jpeg" ContentType="image/jpeg"/></Types>',
        )
    parts["[Content_Types].xml"] = types.encode("utf-8")
    return pack_zip(parts)
