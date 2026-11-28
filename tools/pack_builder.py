"""Turn your own .pptx shells into a presentation pack on this machine.

The pack is written under the user templates directory
(~/.agent-desk/templates, or AGENTDESK_TEMPLATES), never into this
repository. Sample slides, author metadata, SharePoint custom XML,
revision history and leftover package parts are stripped. Dark and light
files are two variants of one template. The three recipes (generic
briefing, QBR, competitor brief) are copied from the shipped starter and
pointed at this shell's layout names.

Example, using shells you already have in Downloads (do not commit the
result):

    python tools/pack_builder.py --id my-template \\
        --dark ~/Downloads/dark.pptx \\
        --light ~/Downloads/light.pptx

Brand packs stay on your machine. This repository ships the format and
one neutral starter only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from nexuusbot.presentations.ooxml import pack_zip, read_parts  # noqa: E402
from nexuusbot.presentations.packs import user_templates_dir  # noqa: E402
from nexuusbot.presentations.thumbs import variant_thumb  # noqa: E402

_SLIDE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
_DROP_PREFIXES = (
    "customXml/", "[trash]/", "ppt/changesInfos/",
    "ppt/notesSlides/", "ppt/media/", "ppt/comments/",
)
_DROP_EXACT = {
    "docProps/thumbnail.jpeg",
    "docProps/custom.xml",
    "ppt/revisionInfo.xml",
    "ppt/commentAuthors.xml",
}
_REL_MARKERS = (
    "customXml/", "[trash]/", "changesInfos/", "notesSlides/",
    "media/", "revisionInfo", "commentAuthors", "thumbnail.jpeg",
    "/custom.xml", "comments/",
)
# The starter recipes are written for a 13.333in by 7.5in slide.
_STANDARD_CX = 12192000
_STANDARD_CY = 6858000


def clean_shell(blob: bytes) -> bytes:
    """A shell with sample slides and package leftovers removed.

    Layouts stay. A typeface that is really a role label (it contains
    parentheses) becomes Arial, and a hard-coded calendar date in a
    layout is cleared. Notes, media, thumbnails, revision history,
    comment authors and custom properties are removed, along with the
    relationships that pointed at them.
    """
    parts = read_parts(blob)
    _drop_slides(parts)
    doomed = [
        name for name in parts
        if name.startswith(_DROP_PREFIXES) or name in _DROP_EXACT
    ]
    for name in doomed:
        parts.pop(name, None)
        _drop_override(parts, "/" + name)
    _drop_rels_to(parts, _REL_MARKERS)
    for name, data in list(parts.items()):
        if not name.endswith(".xml"):
            continue
        parts[name] = _clean_text(data.decode("utf-8", "replace")).encode("utf-8")
    return pack_zip(parts)


def layout_names(blob: bytes) -> list[str]:
    """Layout names in file order."""
    names = []
    parts = read_parts(blob)
    layouts = [
        part for part in parts
        if part.startswith("ppt/slideLayouts/slideLayout") and part.endswith(".xml")
    ]
    for name in sorted(layouts, key=_layout_index):
        match = re.search(r'<p:cSld name="([^"]*)"', parts[name].decode("utf-8", "replace"))
        if match and match.group(1):
            names.append(match.group(1))
    return names


def build_pack(out: Path, pack_id: str, name: str, shells: dict[str, bytes]) -> Path:
    """Write one pack. `shells` maps variant name to cleaned pptx bytes.

    Refuses any destination inside this repository.
    """
    destination = out.resolve()
    repo = ROOT.resolve()
    if destination == repo or repo in destination.parents:
        raise SystemExit(f"refusing to write inside the project tree: {destination}")
    if destination.exists():
        for child in destination.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    destination.mkdir(parents=True, exist_ok=True)
    shell_dir = destination / "shells"
    shell_dir.mkdir(exist_ok=True)
    variants = {}
    names: list[str] = []
    for variant, blob in shells.items():
        rel = f"shells/{variant}.pptx"
        (destination / rel).write_bytes(blob)
        variants[variant] = rel
        if not names:
            names = layout_names(blob)
    mapping = _map_layouts(names)
    size = _slide_size(read_parts(next(iter(shells.values()))))
    recipe_dir = destination / "recipes"
    recipe_dir.mkdir(exist_ok=True)
    recipe_paths = []
    source = ROOT / "registry" / "plugins" / "presentation-starter" / "recipes"
    for path in sorted(source.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for slide in document.get("slides") or []:
            role = slide.get("role")
            if role in mapping:
                slide["layout"] = mapping[role]
            _scale_regions(slide, size)
        target = recipe_dir / path.name
        target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        recipe_paths.append(f"recipes/{path.name}")
    thumb_dir = destination / "thumbs"
    thumb_dir.mkdir(exist_ok=True)
    thumbs = {}
    for variant in variants:
        rel = f"thumbs/{variant}.png"
        (destination / rel).write_bytes(variant_thumb(variant if variant in ("dark", "light") else "light"))
        thumbs[variant] = rel
    manifest = {
        "schemaVersion": 2,
        "id": pack_id,
        "name": name,
        "version": "0.1.0",
        "publisher": "local",
        "class": "declarative",
        "engines": {"dashboardHost": ">=0.1.0 <2.0.0"},
        "license": "MIT",
        "category": "communication",
        "tags": ["presentation", "template"],
        "icon": "generic",
        "summary": f"A local presentation template, {name}.",
        "description": "Installed on this machine from your own shells. It is not part of the public repository.",
        "highlights": [
            "Dark and light are variants of one template.",
            "Three recipes: briefing, quarterly review, competitor brief.",
            "Sample slides and package leftovers are removed.",
        ],
        "permissions": {
            "filesystem": {"read": [], "write": []},
            "network": {"allow": []},
            "llm": {"allow": False},
            "shell": "none",
        },
        "activationEvents": ["onCommand:presentation"],
        "contributes": {
            "presentationTemplates": [{
                "id": pack_id,
                "name": name,
                "variants": variants,
                "recipes": recipe_paths,
                "thumbs": thumbs,
            }]
        },
        "sample": "sample.json",
        "minHost": ">=0.1.0",
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (destination / "sample.json").write_text('{"bindings": {}}\n', encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    """Parse the shell paths and write the pack."""
    parser = argparse.ArgumentParser(description="Install a presentation pack from your own shells")
    parser.add_argument("--id", required=True, help="template id, used as the folder name")
    parser.add_argument("--name", default="", help="the name shown on the picker")
    parser.add_argument("--dark", type=Path, required=True)
    parser.add_argument("--light", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="defaults to the user templates directory")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.id):
        parser.error("the id must be a plain name")
    shells = {"dark": clean_shell(args.dark.read_bytes())}
    if args.light is not None:
        shells["light"] = clean_shell(args.light.read_bytes())
    destination = args.out if args.out is not None else user_templates_dir() / args.id
    written = build_pack(destination, args.id, args.name or args.id, shells)
    print(f"installed {written}")
    return 0


def _drop_slides(parts: dict) -> None:
    """Remove sample slides, their relationships and their content types."""
    rels_name = "ppt/_rels/presentation.xml.rels"
    rels = parts.get(rels_name, b"").decode("utf-8", "replace")
    targets = re.findall(
        r'<Relationship[^>]*Type="[^"]*/slide"[^>]*Target="([^"]+)"[^>]*/>', rels
    )
    if not targets:
        targets = re.findall(
            r'<Relationship[^>]*Target="([^"]+)"[^>]*Type="[^"]*/slide"[^>]*/>', rels
        )
    for target in targets:
        slide = "ppt/" + target.lstrip("/") if not target.startswith("ppt/") else target
        if target.startswith("slides/"):
            slide = "ppt/" + target
        parts.pop(slide, None)
        rel_part = str(Path(slide).parent / "_rels" / (Path(slide).name + ".rels"))
        # Path may rewrite separators. Keep posix.
        rel_part = slide.rsplit("/", 1)[0] + "/_rels/" + slide.rsplit("/", 1)[1] + ".rels"
        parts.pop(rel_part, None)
        _drop_override(parts, "/" + slide)
    if rels:
        rels = re.sub(r'<Relationship[^>]*Type="[^"]*/slide"[^>]*/>', "", rels)
        parts[rels_name] = rels.encode("utf-8")
    presentation = parts.get("ppt/presentation.xml", b"").decode("utf-8", "replace")
    presentation = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>", "<p:sldIdLst></p:sldIdLst>", presentation)
    parts["ppt/presentation.xml"] = presentation.encode("utf-8")


def _drop_rels_to(parts: dict, markers: tuple[str, ...]) -> None:
    """Drop relationship rows that point at a removed part."""
    for name, data in list(parts.items()):
        if not name.endswith(".rels"):
            continue
        text = data.decode("utf-8", "replace")
        def keep(match: re.Match) -> str:
            """Drop one relationship row when it points at a removed part."""
            target = match.group(0)
            if any(marker in target for marker in markers):
                return ""
            return target
        cleaned = re.sub(r"<Relationship[^>]*/>", keep, text)
        parts[name] = cleaned.encode("utf-8")


def _drop_override(parts: dict, part_name: str) -> None:
    """Remove one content-type override for a part that was dropped."""
    types = parts.get("[Content_Types].xml", b"").decode("utf-8", "replace")
    types = re.sub(rf'<Override PartName="{re.escape(part_name)}"[^>]*/>', "", types)
    parts["[Content_Types].xml"] = types.encode("utf-8")


def _layout_index(name: str) -> int:
    """The numeric layout index, so layout 2 sorts before layout 10."""
    match = re.search(r"slideLayout(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def _slide_size(parts: dict) -> tuple[int, int]:
    """The slide size in EMU, or the standard 16:9 size when the part omits it."""
    xml = parts.get("ppt/presentation.xml", b"").decode("utf-8", "replace")
    match = re.search(r'<p:sldSz\b[^>]*cx="(\d+)"[^>]*cy="(\d+)"', xml)
    if not match:
        return _STANDARD_CX, _STANDARD_CY
    return int(match.group(1)), int(match.group(2))


def _scale_regions(slide: dict, size: tuple[int, int]) -> None:
    """Scale a recipe region from the standard slide onto this shell's size."""
    slots = slide.get("slots") or {}
    body = slots.get("body") or {}
    region = body.get("region")
    if not isinstance(region, list) or len(region) != 4:
        return
    sx = size[0] / _STANDARD_CX
    sy = size[1] / _STANDARD_CY
    body["region"] = [
        round(region[0] * sx, 2), round(region[1] * sy, 2),
        round(region[2] * sx, 2), round(region[3] * sy, 2),
    ]


def _clean_text(text: str) -> str:
    """Clear author fields, role-labelled typefaces, calendar dates and company."""
    def font(match: re.Match) -> str:
        """Replace a typeface that is a role label rather than a family."""
        face = match.group(1)
        if "(" in face or ")" in face:
            return 'typeface="Arial"'
        return match.group(0)

    text = re.sub(r'typeface="([^"]*)"', font, text)
    text = re.sub(r"\b\d{2}-\d{2}-\d{4}\b", "", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", text)
    text = re.sub(r"(<dc:creator>)(.*?)(</dc:creator>)", r"\1\3", text)
    text = re.sub(r"(<cp:lastModifiedBy>)(.*?)(</cp:lastModifiedBy>)", r"\1\3", text)
    text = re.sub(r"(<Company>)(.*?)(</Company>)", r"\1\3", text)
    return text


def _map_layouts(names: list[str]) -> dict[str, str]:
    """Role to the shell's layout name. Keywords win, then position."""
    unused = list(names)

    def take(pred) -> str:
        """The first unused layout matching `pred`, else one that is not a vertical title."""
        for name in list(unused):
            if pred(name.lower()):
                unused.remove(name)
                return name
        for name in list(unused):
            if "vertical" not in name.lower():
                unused.remove(name)
                return name
        if unused:
            return unused.pop(0)
        return "Content"

    def take_named(exact: str, pred) -> str:
        """An exact layout name when the shell has it, otherwise `pred`."""
        for name in list(unused):
            if name.lower() == exact:
                unused.remove(name)
                return name
        return take(pred)

    # Title first. Closing's fallback would otherwise take Title Slide
    # and leave the title role on Title Only.
    title = take_named(
        "title slide",
        lambda low: "title" in low and "vertical" not in low and "content" not in low and "only" not in low,
    )
    return {
        "title": title,
        "section": take(lambda low: "divider" in low or "section" in low),
        "content": take(lambda low: "content" in low and "vertical" not in low),
        "closing": take(lambda low: "clos" in low or "engage" in low or "thank" in low),
    }


if __name__ == "__main__":
    sys.exit(main())
