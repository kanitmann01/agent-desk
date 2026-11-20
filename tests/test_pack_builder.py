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

sys.path.insert(0, str(ROOT / "tools"))
import pack_builder


def _dirty(variant: str = "dark") -> bytes:
    """A shell plus the leftovers a downloaded template tends to carry."""
    parts = read_parts(build_shell(variant=variant, body_placeholder=False))
    parts["[trash]/0000.dat"] = b"leftover"
    parts["ppt/changesInfos/changesInfo1.xml"] = b"<changes/>"
    parts["customXml/item1.xml"] = b"<p>sharepoint</p>"
    core = parts["docProps/core.xml"].decode("utf-8")
    core = core.replace("</cp:coreProperties>",
                        "<dc:creator>Sample Author</dc:creator>"
                        "<cp:lastModifiedBy>Sample Author</cp:lastModifiedBy>"
                        "</cp:coreProperties>")
    parts["docProps/core.xml"] = core.encode("utf-8")
    master = parts["ppt/slideMasters/slideMaster1.xml"].decode("utf-8")
    master = master.replace("Arial", "Tahom (Body)", 1)
    master = master.replace("</p:cSld>", "14-08-2026</p:cSld>", 1)
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
    text = "\n".join(
        data.decode("utf-8", "replace") for name, data in parts.items() if name.endswith(".xml")
    )
    assert "Sample Author" not in text
    assert "Tahom (Body)" not in text
    assert "Tahoma" in text
    assert "14-08-2026" not in text
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
