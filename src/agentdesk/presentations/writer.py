"""Fill a shell from an outline. Standard library only.

Sample slides are removed with their notes, thumbnail, and any media
nothing else uses. New slides reference the layout placeholders by
index and type, and do not set their own colour, typeface, or
background, so a dark layout stays dark and its art and footer stay
put. A title-only layout gets a text box in the recipe's region.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from agentdesk.presentations.ooxml import (
    CLOSING_TEXT,
    SAMPLE_TEXT,
    _paragraph,
    _rels,
    _shape,
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
_THEME_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
_SLIDE_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
_NOTES_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
_NOTES_MASTER_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"

_LEFTOVER = (SAMPLE_TEXT, "Divider Slide Option")
# XML 1.0 forbids these. A model or a brief can still emit them.
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


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
    slide_ids = []
    for index, row in enumerate(outline.get("slides") or [], start=1):
        role = str(row.get("role") or "content")
        rule = spec.get(role, {})
        layout_name = str(rule.get("layout") or "Content")
        layout_part = _find_layout(parts, layout_name)
        if layout_part is None:
            raise ValueError("this template has no layout for that slide")
        title = _title_for(row, rule, layout_part)
        bullets = [str(item) for item in (row.get("bullets") or []) if str(item).strip()]
        shapes = _title_shape_for(title, role, layout_part, parts)
        if role == "content":
            if _layout_has_body(layout_part, parts):
                shapes += _body_from_layout(bullets, layout_part, parts)
            else:
                shapes += _body_box(bullets, _region(rule) or [0.9, 1.7, 11.5, 4.6])
        notes = str(row.get("notes") or "")
        slide_name = f"ppt/slides/slide{index}.xml"
        parts[slide_name] = _slide_plain(shapes)
        rels = [("rId1", _LAYOUT_REL, "../" + layout_part.split("ppt/", 1)[1])]
        if notes:
            _ensure_notes_master(parts)
            notes_name = f"ppt/notesSlides/notesSlide{index}.xml"
            parts[notes_name] = _notes_slide(notes)
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

    The zip opens, every part name is unique, every XML part parses,
    every part has a content type, every internal relationship target
    exists, and leftover placeholder text is gone. An external target
    is a link, not a missing part.
    """
    problems = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
        names = archive.namelist()
        parts = {name: archive.read(name) for name in names}
    except Exception as exc:  # noqa: BLE001 - a bad zip is the problem
        return [f"package does not open: {exc}"]
    if len(names) != len(set(names)):
        problems.append("duplicate part names")
    for name, data in parts.items():
        if name.endswith(".xml") or name.endswith(".rels"):
            try:
                ET.fromstring(data)
            except ET.ParseError:
                problems.append(f"xml does not parse: {name}")
    types = parts.get("[Content_Types].xml", b"").decode("utf-8", "replace")
    defaults = {ext.lower() for ext in re.findall(r'Extension="([^"]+)"', types)}
    overrides = {part.lstrip("/") for part in re.findall(r'PartName="([^"]+)"', types)}
    for name in parts:
        if name == "[Content_Types].xml":
            continue
        leaf = name.rsplit("/", 1)[-1]
        ext = leaf.rsplit(".", 1)[-1].lower() if "." in leaf else ""
        if name not in overrides and ext not in defaults:
            problems.append(f"part has no content type: {name}")
    for part_name in overrides:
        if part_name not in parts:
            problems.append(f"content type names a missing part: /{part_name}")
    for name, blob_part in parts.items():
        if not name.endswith(".rels"):
            continue
        folder = _rels_folder(name)
        text = blob_part.decode("utf-8", "replace")
        for attrs in re.findall(r"<Relationship\b([^>]*)/?>", text):
            if 'TargetMode="External"' in attrs:
                continue
            found = re.search(r'Target="([^"]+)"', attrs)
            if not found:
                continue
            target = found.group(1)
            resolved = target.lstrip("/") if target.startswith("/") else _join(folder, target)
            if resolved not in parts:
                problems.append(f"{name} target missing: {target}")
    slide_text = "\n".join(
        data.decode("utf-8", "replace")
        for name, data in parts.items()
        if name.endswith(".xml") and "/slides/" in name
    )
    for leftover in _LEFTOVER:
        if leftover in slide_text:
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
    """Remove the shell's slides, their notes, its thumbnail, and unused media.

    Notes and media that belong to a layout or master stay. A sample
    notes part must not survive under the name the first new slide
    would reuse, or the sample's speaker notes show up on slide 1.
    """
    for name in list(parts):
        if (name.startswith("ppt/slides/") or name.startswith("ppt/notesSlides/")
                or name == "docProps/thumbnail.jpeg"):
            parts.pop(name, None)
            _drop_override(parts, "/" + name)
    rels_name = "ppt/_rels/presentation.xml.rels"
    rels = parts.get(rels_name, b"").decode("utf-8")
    if rels:
        cleaned = re.sub(r'<Relationship[^>]*Type="[^"]*/slide"[^>]*/>', "", rels)
        parts[rels_name] = cleaned.encode("utf-8")
    presentation = parts.get("ppt/presentation.xml", b"").decode("utf-8")
    if presentation:
        presentation = re.sub(
            r"<p:sldIdLst>.*?</p:sldIdLst>", "<p:sldIdLst></p:sldIdLst>",
            presentation, flags=re.DOTALL,
        )
        parts["ppt/presentation.xml"] = presentation.encode("utf-8")
    referenced = _referenced_parts(parts)
    for name in list(parts):
        if name.startswith("ppt/media/") and name not in referenced:
            parts.pop(name, None)
            _drop_override(parts, "/" + name)


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


def _ensure_notes_master(parts: dict) -> None:
    """A notes master with a theme relationship, without replacing one that exists.

    Office requires the theme relationship. A shell that already has a
    notes master keeps that part; only a missing theme link is added.
    """
    master = "ppt/notesMasters/notesMaster1.xml"
    rels_name = "ppt/notesMasters/_rels/notesMaster1.xml.rels"
    if master not in parts:
        parts[master] = _xml(
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
        parts[rels_name] = _rels([("rId1", _THEME_REL, "../theme/theme1.xml")])
        _override(parts, "/ppt/notesMasters/notesMaster1.xml", _NOTES_MASTER_TYPE)
    else:
        rels = parts.get(rels_name, b"").decode("utf-8")
        if "relationships/theme" not in rels:
            link = (
                f'<Relationship Id="rIdTheme" Type="{_THEME_REL}" '
                'Target="../theme/theme1.xml"/>'
            )
            if "</Relationships>" in rels:
                rels = rels.replace("</Relationships>", link + "</Relationships>")
            else:
                rels = _rels([("rIdTheme", _THEME_REL, "../theme/theme1.xml")]).decode("utf-8")
            parts[rels_name] = rels.encode("utf-8")
    pres_rels_name = "ppt/_rels/presentation.xml.rels"
    pres_rels = parts[pres_rels_name].decode("utf-8")
    if "notesMaster" not in pres_rels:
        pres_rels = pres_rels.replace(
            "</Relationships>",
            f'<Relationship Id="rIdNotes" Type="{_NOTES_MASTER_REL}" '
            'Target="notesMasters/notesMaster1.xml"/></Relationships>',
        )
        parts[pres_rels_name] = pres_rels.encode("utf-8")


def _notes_slide(text: str) -> bytes:
    """A notes slide whose body is the speaker-note text, one paragraph per line."""
    lines = str(text).splitlines() or [""]
    paragraphs = "".join(_paragraph(_plain_run(line)) for line in lines)
    body = _shape(
        2, "Notes", emu(0.5), emu(1.2), emu(6), emu(5),
        paragraphs,
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


def _title_shape_for(title: str, role: str, layout_part: str, parts: dict) -> str:
    """The title placeholder, matching the layout's own placeholder."""
    wanted = "title" if role in ("content", "section") else "ctrTitle"
    found = _placeholder(parts[layout_part], wanted) or _placeholder(parts[layout_part], "title")
    ph = found["ph"] if found else f'<p:ph type="{wanted}"/>'
    xfrm = found["xfrm"] if found else ""
    pt = found["pt"] if found else 14
    return _ph_shape(2, "Title", xfrm, _paragraph(_plain_run(title, pt)), ph)


def _body_from_layout(bullets: list[str], layout_part: str, parts: dict) -> str:
    """The body placeholder the layout already defines, filled and not restyled.

    A body is type body, type obj, or an untyped placeholder at idx 1.
    Those are the shapes a Title and Content layout uses.
    """
    found = _body_placeholder(parts[layout_part])
    ph = found["ph"] if found else '<p:ph type="body" idx="1"/>'
    xfrm = found["xfrm"] if found else ""
    pt = found["pt"] if found else 14
    return _ph_shape(3, "Body", xfrm, _bullet_paragraphs(bullets, pt), ph)


def _body_box(bullets: list[str], region: list) -> str:
    """A text box in the recipe region, for a shell with no body placeholder."""
    x, y, w, h = region
    return _shape(
        3, "Body", emu(x), emu(y), emu(w), emu(h),
        _bullet_paragraphs(bullets, 14),
    )


def _bullet_paragraphs(bullets: list[str], pt: int = 14) -> str:
    """One bulleted paragraph per line, at least 14 pt, with no typeface of its own."""
    if not bullets:
        return _paragraph(_plain_run("", pt))
    rows = []
    for bullet in bullets:
        rows.append(
            '<a:p><a:pPr marL="342900" indent="-285750"><a:buChar char="•"/></a:pPr>'
            + _plain_run(bullet, pt) + "</a:p>"
        )
    return "".join(rows)


def _plain_run(text: str, pt: int = 14) -> str:
    """A run with no colour and no typeface. The size is explicit and at least 14 pt."""
    size = max(14, int(pt))
    return (
        f'<a:r><a:rPr lang="en-US" sz="{size * 100}" dirty="0"/>'
        f"<a:t>{_xml_text(text)}</a:t></a:r>"
    )


def _xml_text(value: str) -> str:
    """Escape text for XML, dropping characters XML 1.0 forbids.

    A lone surrogate from a model reply cannot be encoded, so those
    code points are dropped before escaping.
    """
    kept = []
    for char in str(value):
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            continue
        kept.append(char)
    return escape(_ILLEGAL_XML.sub("", "".join(kept)))


def _ph_shape(shape_id: int, name: str, xfrm: str, paragraphs: str, placeholder: str) -> str:
    """A placeholder shape. No fill, so it cannot paint over the layout."""
    box = f"<p:spPr>{xfrm}</p:spPr>" if xfrm else "<p:spPr/>"
    return (
        "<p:sp><p:nvSpPr>"
        f'<p:cNvPr id="{shape_id}" name="{escape(name)}"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        f"<p:nvPr>{placeholder}</p:nvPr></p:nvSpPr>{box}"
        f"<p:txBody><a:bodyPr/><a:lstStyle/>{paragraphs}</p:txBody></p:sp>"
    )


def _slide_plain(shapes: str) -> bytes:
    """A slide with no background of its own, so the layout's shows through."""
    return _xml(
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{shapes}</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )


def _placeholder(layout_xml: bytes, ph_type: str) -> dict | None:
    """The layout shape of one placeholder type, with its transform and size."""
    for found in _shapes(layout_xml):
        if f'type="{ph_type}"' in found["ph"]:
            return found
    return None


def _body_placeholder(layout_xml: bytes) -> dict | None:
    """The layout's body shape.

    Title and Content layouts often omit the type and write only
    `<p:ph idx="1"/>`, or they use `type="obj"`. Both are the body.
    """
    for found in _shapes(layout_xml):
        if _is_body(found["ph"]):
            return found
    return None


def _shapes(layout_xml: bytes) -> list[dict]:
    """Each placeholder shape: its ph element, transform, and point size."""
    text = layout_xml.decode("utf-8", "replace")
    found = []
    for match in re.finditer(r"<p:sp>.*?</p:sp>", text):
        block = match.group(0)
        ph = re.search(r"<p:ph\b[^>]*/>", block)
        if not ph:
            continue
        xfrm = re.search(r"<a:xfrm>.*?</a:xfrm>", block)
        size = re.search(r'\bsz="(\d+)"', block)
        pt = max(14, int(size.group(1)) // 100) if size else 14
        found.append({
            "ph": ph.group(0),
            "xfrm": xfrm.group(0) if xfrm else "",
            "pt": pt,
        })
    return found


def _is_body(tag: str) -> bool:
    """Whether this placeholder element is the body, including obj and untyped idx 1."""
    kind = _attr(tag, "type")
    idx = _attr(tag, "idx")
    if kind in ("title", "ctrtitle", "subtitle", "dt", "ftr", "sldnum"):
        return False
    if kind in ("body", "obj"):
        return True
    return idx == "1"


def _attr(tag: str, name: str) -> str:
    """One attribute of a placeholder tag, lower-cased, or empty."""
    match = re.search(rf'\b{name}="([^"]*)"', tag)
    return match.group(1).lower() if match else ""


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
    return _body_placeholder(parts[layout_part]) is not None


def content_point_size(shell: bytes, recipe: dict) -> int:
    """The body size a filled slide will use, never under 14 pt.

    The size is the layout placeholder's own when it declares one, so a
    fit check can budget for the text that will actually be drawn.
    """
    parts = read_parts(shell)
    rule = next(
        (row for row in recipe.get("slides") or [] if isinstance(row, dict) and row.get("role") == "content"),
        {},
    )
    layout_name = str(rule.get("layout") or "Content")
    layout_part = _find_layout(parts, layout_name)
    if layout_part is None:
        return 14
    found = _body_placeholder(parts[layout_part])
    return found["pt"] if found else 14


def _region(rule: dict) -> list | None:
    """The body region in inches, or None when the recipe names none."""
    slots = rule.get("slots") or {}
    body = slots.get("body") or {}
    region = body.get("region")
    if isinstance(region, list) and len(region) == 4:
        return region
    return None


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
    safe = _xml_text(title)
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


def _rels_folder(name: str) -> str:
    """The folder a relationship target is resolved against."""
    if name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker in name:
        return name.rsplit(marker, 1)[0]
    return name.rsplit("/", 1)[0]


def _referenced_parts(parts: dict) -> set[str]:
    """Internal relationship targets that some remaining part still points at."""
    found = set()
    for name, blob in parts.items():
        if not name.endswith(".rels"):
            continue
        folder = _rels_folder(name)
        text = blob.decode("utf-8", "replace")
        for attrs in re.findall(r"<Relationship\b([^>]*)/?>", text):
            if 'TargetMode="External"' in attrs:
                continue
            target = re.search(r'Target="([^"]+)"', attrs)
            if not target:
                continue
            raw = target.group(1)
            found.add(raw.lstrip("/") if raw.startswith("/") else _join(folder, raw))
    return found


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
