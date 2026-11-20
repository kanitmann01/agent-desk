"""Fill a shell from an outline. Standard library only.

Sample slides are removed with their relationships and parts. New slides
are added from the named layouts. A content layout with a body
placeholder is filled through it. A title-only layout gets a text box
in the recipe's region. The layout and master parts are not rewritten.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from agentdesk.presentations.ooxml import (
    CLOSING_TEXT,
    SAMPLE_TEXT,
    _paragraph,
    _rels,
    _run,
    _shape,
    _slide,
    _xml,
    emu,
    pack_zip,
    read_parts,
)

_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_SLIDE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
_LAYOUT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
_NOTES_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
_NOTES_MASTER_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster"
_SLIDE_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
_NOTES_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
_NOTES_MASTER_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"

_LEFTOVER = (SAMPLE_TEXT, "Divider Slide Option")


def outline_for(brief: str, recipe: dict) -> dict:
    """A fixed deck for one brief and recipe, with no model call.

    Two content slides per section, which sits in the recipe's 2-4 range.
    Notes name that no source was supplied, so a later fill can replace them.
    """
    title = " ".join(brief.split())[:60] or "Untitled"
    slides = [{"role": "title", "title": title}]
    for section in recipe.get("sections") or []:
        heading = str(section.get("title") or "Section")
        slides.append({"role": "section", "title": heading[:40]})
        for bullet in (
            [title[:110] or heading, "Prepared from the desk."],
            ["What this section covers.", "One idea on the slide."],
        ):
            slides.append({
                "role": "content",
                "title": heading[:60],
                "bullets": bullet,
                "notes": "Sources: none supplied for this preview.",
            })
    slides.append({"role": "closing"})
    return {"title": title, "slides": slides}


def write_deck(shell: bytes, recipe: dict, outline: dict) -> bytes:
    """A new package: the shell's layouts, plus one slide per outline row."""
    parts = read_parts(shell)
    _drop_sample_slides(parts)
    spec = {row["role"]: row for row in recipe.get("slides") or [] if isinstance(row, dict)}
    ink = _ink(parts)
    notes_master_added = False
    slide_ids = []
    for index, row in enumerate(outline.get("slides") or [], start=1):
        role = str(row.get("role") or "content")
        rule = spec.get(role, {})
        layout_name = str(rule.get("layout") or "Content")
        layout_part = _find_layout(parts, layout_name)
        if layout_part is None:
            raise ValueError(f"no layout named {layout_name}")
        title = _title_for(row, rule, layout_part)
        bullets = [str(item) for item in (row.get("bullets") or []) if str(item).strip()]
        shapes = _title_placeholder(title, ink, role)
        if role == "content":
            if _layout_has_body(layout_part, parts) or not _region(rule):
                shapes += _body_placeholder(bullets, ink)
            else:
                shapes += _body_box(bullets, ink, _region(rule))
        notes = str(row.get("notes") or "")
        slide_name = f"ppt/slides/slide{index}.xml"
        parts[slide_name] = _slide(shapes, _bg(parts, layout_part))
        rels = [("rId1", _LAYOUT_REL, "../" + layout_part.split("ppt/", 1)[1])]
        if notes:
            if not notes_master_added:
                _add_notes_master(parts)
                notes_master_added = True
            notes_name = f"ppt/notesSlides/notesSlide{index}.xml"
            parts[notes_name] = _notes_slide(notes, ink)
            parts[f"ppt/notesSlides/_rels/notesSlide{index}.xml.rels"] = _rels([
                ("rId1", _NOTES_MASTER_REL, "../notesMasters/notesMaster1.xml"),
                ("rId2", _SLIDE_REL, f"../slides/slide{index}.xml"),
            ])
            rels.append(("rId2", _NOTES_REL, f"../notesSlides/notesSlide{index}.xml"))
            _override(parts, f"/{notes_name}", _NOTES_TYPE)
        parts[f"ppt/slides/_rels/slide{index}.xml.rels"] = _rels(rels)
        _override(parts, f"/{slide_name}", _SLIDE_TYPE)
        slide_ids.append(256 + index)
    _point_presentation_at(parts, slide_ids)
    _set_title(parts, str(outline.get("title") or "Deck"))
    return pack_zip(parts)


def package_problems(blob: bytes) -> list[str]:
    """What a person would notice is wrong with the package.

    The zip opens, every relationship target exists, content-type
    overrides name real parts, and leftover placeholder text is gone.
    """
    problems = []
    try:
        parts = read_parts(blob)
    except Exception as exc:  # noqa: BLE001 - a bad zip is the problem
        return [f"package does not open: {exc}"]
    if len(parts) != len(set(parts)):
        problems.append("duplicate part names")
    for name, blob_part in parts.items():
        if not name.endswith(".rels"):
            continue
        base = name.rsplit("/", 1)[0]
        base = "" if base.endswith("_rels") else base
        parent = base[: -len("/_rels")] if base.endswith("/_rels") else base.rsplit("/", 1)[0]
        # rels live in _rels next to the source, or at _rels/.rels for the root
        if name == "_rels/.rels":
            folder = ""
        else:
            folder = name[: -len("/_rels/" + name.rsplit("/", 1)[-1])]
        for target in re.findall(r'Target="([^"]+)"', blob_part.decode("utf-8", "replace")):
            if target.startswith("/"):
                resolved = target.lstrip("/")
            else:
                resolved = _join(folder, target)
            if resolved not in parts:
                problems.append(f"{name} target missing: {target}")
    types = parts.get("[Content_Types].xml", b"").decode("utf-8", "replace")
    for part_name in re.findall(r'PartName="([^"]+)"', types):
        if part_name.lstrip("/") not in parts:
            problems.append(f"content type names a missing part: {part_name}")
    text = "\n".join(
        blob_part.decode("utf-8", "replace")
        for name, blob_part in parts.items()
        if name.endswith(".xml") and "/slides/" in name
    )
    for leftover in _LEFTOVER:
        if leftover in text:
            problems.append(f"leftover template text: {leftover}")
    return problems


def slide_texts(blob: bytes) -> list[dict]:
    """Each slide's visible text and its notes, in slide order."""
    parts = read_parts(blob)
    order = _slide_order(parts)
    rows = []
    for name in order:
        xml = parts[name].decode("utf-8", "replace")
        texts = re.findall(r"<a:t[^>]*>([^<]*)</a:t>", xml)
        notes = ""
        rels_name = name.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
        rels = parts.get(rels_name, b"").decode("utf-8", "replace")
        match = re.search(r'Target="\.\./notesSlides/([^"]+)"', rels)
        if match:
            notes_xml = parts.get(f"ppt/notesSlides/{match.group(1)}", b"").decode("utf-8", "replace")
            notes = " ".join(re.findall(r"<a:t[^>]*>([^<]*)</a:t>", notes_xml))
        rows.append({"texts": texts, "notes": notes})
    return rows


def _drop_sample_slides(parts: dict) -> None:
    """Remove every slide the shell shipped, and the parts that belonged to it."""
    rels_name = "ppt/_rels/presentation.xml.rels"
    rels = parts.get(rels_name, b"").decode("utf-8")
    targets = re.findall(
        r'Id="([^"]+)"[^>]*Type="[^"]*/slide"[^>]*Target="([^"]+)"', rels
    )
    # The attribute order in our shells is Id, Type, Target. Also accept Type first.
    if not targets:
        targets = re.findall(
            r'Type="[^"]*/slide"[^>]*Target="([^"]+)"', rels
        )
        targets = [(f"rId{i}", target) for i, target in enumerate(targets, start=1)]
    for _rid, target in targets:
        slide = _join("ppt", target)
        slide_rels = slide.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
        if slide_rels in parts:
            for notes in re.findall(r'Target="([^"]*notesSlides/[^"]+)"', parts[slide_rels].decode("utf-8")):
                notes_part = _join("ppt/slides", notes) if not notes.startswith("..") else _join("ppt", notes.removeprefix("../"))
                parts.pop(notes_part, None)
                parts.pop(notes_part.replace("ppt/notesSlides/", "ppt/notesSlides/_rels/") + ".rels", None)
                _drop_override(parts, "/" + notes_part)
        parts.pop(slide, None)
        parts.pop(slide_rels, None)
        _drop_override(parts, "/" + slide)
    if rels:
        cleaned = re.sub(
            r'<Relationship[^>]*Type="[^"]*/slide"[^>]*/>', "", rels
        )
        parts[rels_name] = cleaned.encode("utf-8")
    presentation = parts.get("ppt/presentation.xml", b"").decode("utf-8")
    presentation = re.sub(r"<p:sldIdLst>.*?</p:sldIdLst>", "<p:sldIdLst></p:sldIdLst>", presentation)
    parts["ppt/presentation.xml"] = presentation.encode("utf-8")


def _point_presentation_at(parts: dict, slide_ids: list[int]) -> None:
    """Point the presentation at the new slides, in order."""
    rels_name = "ppt/_rels/presentation.xml.rels"
    rels = parts[rels_name].decode("utf-8")
    used = [int(n) for n in re.findall(r'Id="rId(\d+)"', rels)]
    next_id = max(used or [0]) + 1
    additions = []
    sld_ids = []
    for offset, slide_id in enumerate(slide_ids):
        rid = f"rId{next_id + offset}"
        additions.append(
            f'<Relationship Id="{rid}" Type="{_SLIDE_REL}" Target="slides/slide{offset + 1}.xml"/>'
        )
        sld_ids.append(f'<p:sldId id="{slide_id}" r:id="{rid}"/>')
    rels = rels.replace("</Relationships>", "".join(additions) + "</Relationships>")
    parts[rels_name] = rels.encode("utf-8")
    presentation = parts["ppt/presentation.xml"].decode("utf-8")
    presentation = presentation.replace(
        "<p:sldIdLst></p:sldIdLst>",
        "<p:sldIdLst>" + "".join(sld_ids) + "</p:sldIdLst>",
    )
    if "<p:notesMasterIdLst>" not in presentation and "ppt/notesMasters/notesMaster1.xml" in parts:
        presentation = presentation.replace(
            "</p:sldMasterIdLst>",
            '</p:sldMasterIdLst><p:notesMasterIdLst>'
            '<p:notesMasterId id="2147483647" r:id="rIdNotes"/></p:notesMasterIdLst>',
        )
        # The notes master relationship is added with the master.
    parts["ppt/presentation.xml"] = presentation.encode("utf-8")


def _add_notes_master(parts: dict) -> None:
    """One notes master, added the first time a slide carries notes."""
    parts["ppt/notesMasters/notesMaster1.xml"] = _xml(
        '<p:notesMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld name="Notes"><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        "</p:spTree></p:cSld>"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
        'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
        'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        "</p:notesMaster>"
    )
    parts["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = _rels([])
    _override(parts, "/ppt/notesMasters/notesMaster1.xml", _NOTES_MASTER_TYPE)
    rels_name = "ppt/_rels/presentation.xml.rels"
    rels = parts[rels_name].decode("utf-8")
    if "notesMaster" not in rels:
        rels = rels.replace(
            "</Relationships>",
            f'<Relationship Id="rIdNotes" Type="{_NOTES_MASTER_REL}" '
            'Target="notesMasters/notesMaster1.xml"/></Relationships>',
        )
        parts[rels_name] = rels.encode("utf-8")


def _notes_slide(text: str, ink: str) -> bytes:
    """A notes slide whose body is the speaker-note text."""
    body = _shape(
        2, "Notes", emu(0.5), emu(1.2), emu(6), emu(5),
        _paragraph(_run(text, 12, ink)),
        placeholder='<p:ph type="body" idx="1"/>',
    )
    return _xml(
        '<p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f"<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{body}</p:spTree></p:cSld></p:notes>"
    )


def _title_for(row: dict, rule: dict, layout_part: str) -> str:
    """The title to write. A fixed closing slide keeps the shell's words."""
    if rule.get("fixed"):
        return CLOSING_TEXT
    return str(row.get("title") or "").strip()


def _title_placeholder(title: str, ink: str, role: str) -> str:
    """The title placeholder for one role."""
    size = 32 if role in ("title", "closing") else 28 if role == "section" else 24
    y = 2.6 if role in ("title", "closing", "section") else 0.45
    ph = '<p:ph type="title"/>' if role == "section" else '<p:ph type="ctrTitle"/>'
    if role == "content":
        ph = '<p:ph type="title"/>'
    return _shape(2, "Title", emu(0.7), emu(y), emu(11.9), emu(1.1), _paragraph(_run(title, size, ink)), placeholder=ph)


def _body_placeholder(bullets: list[str], ink: str) -> str:
    """The body placeholder, filled with the bullets."""
    return _shape(
        3, "Body", emu(0.9), emu(1.7), emu(11.5), emu(4.6),
        _bullet_paragraphs(bullets, ink, 14),
        placeholder='<p:ph type="body" idx="1"/>',
    )


def _body_box(bullets: list[str], ink: str, region: list) -> str:
    """A text box in the recipe region, for a shell with no body placeholder."""
    x, y, w, h = region
    return _shape(
        3, "Body", emu(x), emu(y), emu(w), emu(h),
        _bullet_paragraphs(bullets, ink, 14),
    )


def _bullet_paragraphs(bullets: list[str], ink: str, size: int) -> str:
    """One bulleted paragraph per line, at the given point size."""
    if not bullets:
        return _paragraph(_run("", size, ink))
    rows = []
    for bullet in bullets:
        rows.append(
            '<a:p><a:pPr marL="342900" indent="-171450">'
            '<a:buFont typeface="Arial"/><a:buChar char="•"/></a:pPr>'
            + _run(bullet, size, ink) + "</a:p>"
        )
    return "".join(rows)


def _find_layout(parts: dict, wanted: str) -> str | None:
    """The layout part whose name matches. A trailing star is a prefix."""
    prefix = wanted.endswith("*")
    stem = wanted[:-1] if prefix else wanted
    for name, blob in parts.items():
        if not name.startswith("ppt/slideLayouts/") or not name.endswith(".xml"):
            continue
        match = re.search(r'<p:cSld name="([^"]*)"', blob.decode("utf-8", "replace"))
        if not match:
            continue
        found = match.group(1)
        if prefix and found.startswith(stem):
            return name
        if found == stem:
            return name
    return None


def _layout_has_body(layout_part: str, parts: dict) -> bool:
    """Whether this layout already has a body placeholder."""
    xml = parts[layout_part].decode("utf-8", "replace")
    return 'type="body"' in xml


def _region(rule: dict) -> list | None:
    """The body region in inches, or None when the recipe names none."""
    slots = rule.get("slots") or {}
    body = slots.get("body") or {}
    region = body.get("region")
    if isinstance(region, list) and len(region) == 4:
        return region
    return None


def _ink(parts: dict) -> str:
    """The master text colour, so filled runs match the shell."""
    master = parts.get("ppt/slideMasters/slideMaster1.xml", b"").decode("utf-8", "replace")
    if "F4F4F2" in master:
        return "F4F4F2"
    return "1C1C1F"


def _bg(parts: dict, layout_part: str) -> str:
    """The layout background colour, so the new slide matches the shell."""
    xml = parts[layout_part].decode("utf-8", "replace")
    match = re.search(r'<a:srgbClr val="([0-9A-Fa-f]{6})"/>', xml)
    return match.group(1) if match else "1C1C1F"


def _override(parts: dict, part_name: str, content_type: str) -> None:
    """Declare the content type of a part this write added."""
    types = parts["[Content_Types].xml"].decode("utf-8")
    snippet = f'<Override PartName="{part_name}" ContentType="{content_type}"/>'
    if snippet not in types:
        types = types.replace("</Types>", snippet + "</Types>")
        parts["[Content_Types].xml"] = types.encode("utf-8")


def _drop_override(parts: dict, part_name: str) -> None:
    """Remove one content-type override so a dropped part is not declared."""
    types = parts.get("[Content_Types].xml", b"").decode("utf-8")
    types = re.sub(rf'<Override PartName="{re.escape(part_name)}"[^>]*/>', "", types)
    parts["[Content_Types].xml"] = types.encode("utf-8")


def _set_title(parts: dict, title: str) -> None:
    """Set the document title in the package properties."""
    core = parts.get("docProps/core.xml")
    if not core:
        return
    text = core.decode("utf-8")
    safe = escape(title)
    if "<dc:title>" in text:
        text = re.sub(r"<dc:title>.*?</dc:title>", f"<dc:title>{safe}</dc:title>", text)
    else:
        text = text.replace("</cp:coreProperties>", f"<dc:title>{safe}</dc:title></cp:coreProperties>")
    parts["docProps/core.xml"] = text.encode("utf-8")


def _slide_order(parts: dict) -> list[str]:
    """Slide part names in the order the presentation lists them."""
    rels = parts.get("ppt/_rels/presentation.xml.rels", b"").decode("utf-8")
    presentation = parts.get("ppt/presentation.xml", b"").decode("utf-8")
    ids = re.findall(r'<p:sldId[^>]*r:id="([^"]+)"', presentation)
    targets = dict(re.findall(r'Id="([^"]+)"[^>]*Target="(slides/[^"]+)"', rels))
    names = []
    for rid in ids:
        target = targets.get(rid)
        if target:
            names.append("ppt/" + target)
    return names


def _join(folder: str, target: str) -> str:
    """Resolve a relationship target against the folder of the rels part."""
    parts = [] if not folder else folder.split("/")
    for piece in target.split("/"):
        if piece == "..":
            if parts:
                parts.pop()
        elif piece and piece != ".":
            parts.append(piece)
    return "/".join(parts)
