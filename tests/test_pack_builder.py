"""The local pack builder: a dirty shell becomes a clean pack outside the repo.

The seam is the installed directory and the Agents page that lists it.
"""

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.presentations.ooxml import build_shell, pack_zip, read_parts
from agentdesk.presentations.packs import load_packs
from agentdesk.presentations.writer import package_problems

sys.path.insert(0, str(ROOT / "tools"))
import pack_builder


def _dirty(variant: str = "dark") -> bytes:
    """A shell plus the leftovers a downloaded template tends to carry."""
    parts = read_parts(build_shell(variant=variant, body_placeholder=False))
    parts["[trash]/0000.dat"] = b"leftover"
    parts["ppt/changesInfos/changesInfo1.xml"] = b"<changes/>"
    parts["customXml/item1.xml"] = b"<p>sharepoint</p>"
    parts["ppt/notesSlides/notesSlide1.xml"] = b"<p:notes>orphan</p:notes>"
    parts["ppt/notesSlides/_rels/notesSlide1.xml.rels"] = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="../notesMasters/missing.xml"/>'
        b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="../slides/missing.xml"/>'
        b'<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/missing.png"/>'
        b'<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/also-missing.png"/>'
        b"</Relationships>"
    )
    parts["ppt/media/image1.png"] = b"\x89PNG"
    parts["docProps/thumbnail.jpeg"] = b"\xff\xd8\xff"
    parts["ppt/revisionInfo.xml"] = b"<p:revisionInfo/>"
    parts["ppt/commentAuthors.xml"] = b"<p:cmAuthorLst/>"
    parts["docProps/custom.xml"] = b"<Properties/>"
    app = parts["docProps/app.xml"].decode("utf-8")
    app = app.replace("</Properties>", "<Company>Example Co</Company></Properties>")
    parts["docProps/app.xml"] = app.encode("utf-8")
    layout_rel = parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"].decode("utf-8")
    layout_rel = layout_rel.replace(
        "</Relationships>",
        '<Relationship Id="rIdPic" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="../media/image1.png"/></Relationships>',
    )
    parts["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = layout_rel.encode("utf-8")
    core = parts["docProps/core.xml"].decode("utf-8")
    core = core.replace("</cp:coreProperties>",
                        "<dc:creator>Sample Author</dc:creator>"
                        "<cp:lastModifiedBy>Sample Author</cp:lastModifiedBy>"
                        "</cp:coreProperties>")
    parts["docProps/core.xml"] = core.encode("utf-8")
    master = parts["ppt/slideMasters/slideMaster1.xml"].decode("utf-8")
    master = master.replace('typeface="Arial"', 'typeface="NotAFont (Body)"', 1)
    master = master.replace("</p:cSld>", "03-04-2005</p:cSld>", 1)
    parts["ppt/slideMasters/slideMaster1.xml"] = master.encode("utf-8")
    return pack_zip(parts)


def test_a_dirty_shell_becomes_a_clean_pack_outside_the_repo(tmp_path, monkeypatch):
    dark = tmp_path / "dark.pptx"
    light = tmp_path / "light.pptx"
    dark.write_bytes(_dirty("dark"))
    light.write_bytes(_dirty("light"))
    install = tmp_path / "templates"
    monkeypatch.setenv("AGENTDESK_TEMPLATES", str(install))
    code = pack_builder.main([
        "--id", "local-shell", "--name", "Local shell",
        "--dark", str(dark), "--light", str(light),
    ])
    assert code == 0
    pack = install / "local-shell"
    assert pack.is_dir()
    assert ROOT.resolve() not in pack.resolve().parents
    parts = read_parts((pack / "shells" / "dark.pptx").read_bytes())
    assert "ppt/slides/slide1.xml" not in parts
    assert any(name.startswith("ppt/slideLayouts/") for name in parts)
    assert "[trash]/0000.dat" not in parts
    assert "ppt/changesInfos/changesInfo1.xml" not in parts
    assert "customXml/item1.xml" not in parts
    assert not any(name.startswith("ppt/notesSlides/") for name in parts)
    assert not any(name.startswith("ppt/media/") for name in parts)
    assert "docProps/thumbnail.jpeg" not in parts
    assert "ppt/revisionInfo.xml" not in parts
    assert "ppt/commentAuthors.xml" not in parts
    assert "docProps/custom.xml" not in parts
    text = "\n".join(
        data.decode("utf-8", "replace") for name, data in parts.items() if name.endswith(".xml")
    )
    assert "Sample Author" not in text
    assert "NotAFont" not in text
    assert 'typeface="Arial"' in text
    assert "03-04-2005" not in text
    assert "Example Co" not in text
    assert package_problems((pack / "shells" / "dark.pptx").read_bytes()) == []
    stale = pack / "recipes" / "stale.json"
    stale.write_text("{}\n", encoding="utf-8")
    pack_builder.main([
        "--id", "local-shell", "--name", "Local shell",
        "--dark", str(dark), "--light", str(light),
    ])
    assert not stale.exists()
    recipes = sorted(path.name for path in (pack / "recipes").iterdir())
    assert recipes == ["briefing.json", "competitor-brief.json", "qbr.json"]
    briefing = json.loads((pack / "recipes" / "briefing.json").read_text(encoding="utf-8"))
    layouts = {slide["role"]: slide["layout"] for slide in briefing["slides"]}
    assert layouts["title"] == "Title Slide"
    assert layouts["content"] == "Content"
    packs = load_packs(ROOT / "registry", install)
    ids = [item.id for item in packs]
    assert "starter" in ids and "local-shell" in ids
    local = next(item for item in packs if item.id == "local-shell")
    assert set(local.variants) == {"dark", "light"}
    assert local.source == "installed"


def test_the_command_refuses_to_write_inside_the_repository(tmp_path):
    shell = tmp_path / "one.pptx"
    shell.write_bytes(_dirty())
    inside = ROOT / "registry" / "plugins" / "should-not-exist"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "pack_builder.py"),
         "--id", "nope", "--dark", str(shell), "--out", str(inside)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "project tree" in result.stderr or "project tree" in result.stdout
    assert not inside.exists()


def test_the_picker_lists_the_installed_pack(tmp_path, monkeypatch):
    dark = tmp_path / "dark.pptx"
    dark.write_bytes(_dirty("dark"))
    install = tmp_path / "templates"
    monkeypatch.setenv("AGENTDESK_TEMPLATES", str(install))
    pack_builder.main(["--id", "local-shell", "--name", "Local shell", "--dark", str(dark)])
    booted = server_harness.Booted()
    try:
        auth = booted.exchange()
        booted.server.settings.set("llm_base", "http://127.0.0.1:9/v1")
        status, _h, body = booted.request("GET", "/agents", auth)
        page = body.decode("utf-8")
        assert status == 200
        assert "Local shell" in page
        assert 'value="local-shell"' in page
        assert "Generic briefing" in page and "QBR" in page and "Competitor brief" in page
    finally:
        booted.close()


def test_layouts_sort_numerically_and_a_divider_is_not_a_vertical_title():
    parts = read_parts(build_shell())
    vertical = parts["ppt/slideLayouts/slideLayout2.xml"].replace(
        b'name="Divider"', b'name="Title and Vertical Text"', 1,
    )
    parts["ppt/slideLayouts/slideLayout10.xml"] = vertical
    names = pack_builder.layout_names(pack_zip(parts))
    assert names.index("Divider") < names.index("Title and Vertical Text")
    mapping = pack_builder._map_layouts(names)
    assert mapping["section"] == "Divider"
    assert mapping["title"] == "Title Slide"
    assert "Vertical" not in mapping["section"] and "Vertical" not in mapping["title"]


def test_a_narrow_shell_scales_the_body_region(tmp_path, monkeypatch):
    parts = read_parts(build_shell())
    presentation = parts["ppt/presentation.xml"].decode("utf-8")
    presentation = presentation.replace('cx="12192000"', 'cx="9144000"')
    parts["ppt/presentation.xml"] = presentation.encode("utf-8")
    dark = tmp_path / "narrow.pptx"
    dark.write_bytes(pack_zip(parts))
    install = tmp_path / "templates"
    monkeypatch.setenv("AGENTDESK_TEMPLATES", str(install))
    pack_builder.main(["--id", "narrow", "--dark", str(dark)])
    briefing = json.loads((install / "narrow" / "recipes" / "briefing.json").read_text(encoding="utf-8"))
    region = next(slide["slots"]["body"]["region"] for slide in briefing["slides"] if slide["role"] == "content")
    width_in = 9144000 / 914400
    assert region[0] + region[2] <= width_in
