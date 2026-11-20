"""Template packs: the shipped starter, the user directory, the picker, the leak check.

The seam is the agents page and the run route. A pack the loader does not
list cannot be chosen, and a denylisted fingerprint fails the scan.
"""

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.llm import NO_ENDPOINT_CAUSE
from agentdesk.presentations.leak import load_hashes, scan
from agentdesk.presentations.ooxml import SAMPLE_TEXT, build_shell, read_parts
from agentdesk.presentations.packs import load_packs
from agentdesk.registry.install import install_from_registry, tree_digest
from agentdesk.registry.index import load_index
from agentdesk.validator.core import validate_plugin

PACK = ROOT / "registry" / "plugins" / "presentation-starter"
REGISTRY = ROOT / "registry"


def _ready(env):
    env.server.settings.set("llm_base", "http://127.0.0.1:9/v1")


def test_the_shipped_starter_validates_and_pins_its_digest():
    verdict = validate_plugin(PACK)
    assert verdict.ok, verdict.failures
    index = load_index((REGISTRY / "index.json").read_text(encoding="utf-8"))
    entry = index.plugin("presentation-starter")
    release = entry.release_for("0.1.0")
    assert release.sha256 == tree_digest(PACK)
    assert release.source == "local"
    assert release.signature == ""
    excel = index.plugin("excel-report").release_for("0.1.0")
    assert excel.signature == release.signature


def test_installing_the_starter_uses_the_registry_pin(tmp_path):
    record = install_from_registry(
        REGISTRY, "presentation-starter", version="0.1.0", destination=tmp_path,
    )
    assert record["ok"] is True
    assert record["sha256"] == tree_digest(PACK)
    assert (tmp_path / "presentation-starter-0.1.0" / "manifest.json").is_file()


def test_the_shipped_shells_are_the_neutral_builder():
    dark = (PACK / "shells" / "starter-dark.pptx").read_bytes()
    light = (PACK / "shells" / "starter-light.pptx").read_bytes()
    assert dark == build_shell(variant="dark", body_placeholder=True)
    assert light == build_shell(variant="light", body_placeholder=True)
    parts = read_parts(dark)
    joined = b"\n".join(parts.values())
    assert b"Title Slide" in joined and b"Content" in joined
    assert SAMPLE_TEXT.encode() in parts["ppt/slides/slide1.xml"]
    assert b"Thank you" in parts["ppt/slideLayouts/slideLayout4.xml"]


def test_the_loader_lists_the_starter_and_lets_an_install_win(tmp_path):
    shipped = load_packs(REGISTRY, tmp_path)
    assert [pack.id for pack in shipped] == ["starter"]
    assert shipped[0].source == "shipped"
    override = tmp_path / "local-starter"
    override.mkdir()
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    manifest["contributes"]["presentationTemplates"][0]["name"] = "Desk local"
    (override / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    packs = load_packs(REGISTRY, tmp_path)
    assert [pack.id for pack in packs] == ["starter"]
    assert packs[0].name == "Desk local"
    assert packs[0].source == "installed"


def test_the_leak_check_fails_a_denylisted_token_and_passes_the_starter():
    token = "denylistprobe"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    empty = load_hashes(ROOT / "tools" / "brand_leak_hashes.txt")
    assert empty == set()
    assert scan([PACK], empty) == []
    assert scan([PACK / "guidance" / "SKILL.md"], {digest}) == []
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        path = Path(folder) / "note.txt"
        path.write_text(f"see {token} here", encoding="utf-8")
        assert scan([path], {digest}) == [str(path)]
        media = Path(folder) / "mark.png"
        media.write_bytes(b"not-a-real-image")
        media_hash = hashlib.sha256(media.read_bytes()).hexdigest()
        assert scan([media], {media_hash}) == [str(media)]


def test_a_token_inside_a_pptx_fails_the_leak_check(tmp_path):
    token = "leakprobetoken"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    inner_png = b"\x89PNG-inner"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("docProps/core.xml", f"<dc:title>{token}</dc:title>")
        archive.writestr("ppt/media/mark.png", inner_png)
    deck = tmp_path / "shell.pptx"
    deck.write_bytes(buf.getvalue())
    assert scan([deck], {digest}) == [str(deck)]
    assert scan([deck], {hashlib.sha256(inner_png).hexdigest()}) == [str(deck)]
    # The committed list stays empty. The hash above exists only in this test.
    assert load_hashes(ROOT / "tools" / "brand_leak_hashes.txt") == set()


def test_a_thumb_or_shell_outside_the_pack_is_not_served(tmp_path):
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"\x89PNG-secret")
    pack_dir = tmp_path / "templates" / "escape"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(json.dumps({
        "id": "escape",
        "version": "0.1.0",
        "contributes": {"presentationTemplates": [{
            "id": "escape",
            "name": "Escape",
            "variants": {"dark": str(secret), "light": "../secret.png"},
            "recipes": ["../secret.png"],
            "thumbs": {"dark": "../secret.png", "light": str(secret)},
        }]},
    }), encoding="utf-8")
    pack = load_packs(ROOT / "registry", tmp_path / "templates")
    escape = next(item for item in pack if item.id == "escape")
    assert escape.thumb_path("dark") is None
    assert escape.thumb_path("light") is None
    assert escape.shell_path("dark") is None
    assert escape.shell_path("light") is None
    assert escape.recipe("secret") is None


def test_the_picker_is_disabled_until_the_endpoint_is_configured():
    booted = server_harness.Booted()
    try:
        auth = booted.exchange()
        status, _h, body = booted.request("GET", "/agents", auth)
        page = body.decode("utf-8")
        assert status == 200
        assert "Starter" in page
        assert 'value="starter"' in page
        assert "Generic briefing" in page and "QBR" in page and "Competitor brief" in page
        assert 'name="variant"' in page
        assert "/agents/templates/starter/dark.png" in page
        assert NO_ENDPOINT_CAUSE in page
        assert "disabled" in page
        status, headers, png = booted.request("GET", "/agents/templates/starter/dark.png", auth)
        assert status == 200
        assert png.startswith(b"\x89PNG")
        assert headers["Content-Type"].startswith("image/png")
        status, _h, missing = booted.request(
            "GET", "/agents/templates/starter/../../etc/passwd", auth
        )
        assert status == 404
    finally:
        booted.close()


def test_a_configured_run_records_the_template_variant_and_recipe():
    booted = server_harness.Booted()
    try:
        auth = booted.exchange()
        _ready(booted)
        status, _h, body = booted.request("GET", "/agents", auth)
        page = body.decode("utf-8")
        assert 'class="template-tiles">' in page
        assert 'class="template-tiles" disabled' not in page
        status, _h, body = booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "the Q3 review",
             "template": "starter", "variant": "light", "recipe": "qbr"},
            auth,
        )
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ok"
        artifact = payload["artifact"]
        assert artifact["templateId"] == "starter"
        assert artifact["variant"] == "light"
        assert artifact["recipe"] == "qbr"
        assert artifact["digest"] == tree_digest(PACK)
        assert artifact["phase"] == "selected"
        assert "file" not in artifact
        status, _h, page = booted.request("GET", "/agents", auth)
        assert b"recipe qbr" in page
    finally:
        booted.close()


def test_the_endpoint_switch_off_disables_the_tiles_with_the_pinned_sentence():
    booted = server_harness.Booted()
    try:
        auth = booted.exchange()
        _ready(booted)
        booted.server.settings.set("endpoint_enabled", False)
        status, _h, body = booted.request("GET", "/agents", auth)
        page = body.decode("utf-8")
        assert status == 200
        assert "turned off in settings" in page
        assert "disabled" in page
        status, _h, body = booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "the Q3 review",
             "template": "starter", "variant": "dark", "recipe": "briefing"},
            auth,
        )
        payload = json.loads(body)
        assert payload["status"] == "degraded"
        assert "turned off in settings" in payload["cause"]
        assert payload["artifact"] is None
    finally:
        booted.close()


def test_a_form_post_records_the_choice_without_javascript():
    booted = server_harness.Booted()
    try:
        auth = booted.exchange()
        _ready(booted)
        raw = "agent=presentation&brief=the+Q3+review&template=starter&variant=dark&recipe=briefing"
        body = raw.encode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
            **auth,
        }
        status, headers_out, _b = booted.request("POST", "/agents/run", headers, body)
        assert status == 303
        assert headers_out["Location"] == "/agents"
        stored = booted.server.agents.recent()
        assert stored[0]["artifact"]["recipe"] == "briefing"
        assert stored[0]["artifact"]["templateId"] == "starter"
    finally:
        booted.close()
