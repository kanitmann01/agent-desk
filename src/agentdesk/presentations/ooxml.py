"""Minimal .pptx shells, built with the standard library.

A shell is a zip of Office Open XML: one master, four named layouts
(Title Slide, Divider, Content, Closing), a theme, and one sample slide
the writer later drops. Dark and light differ only by the background
and text colours. Nothing here is a brand palette.
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

EMU = 914400
SLIDE_CX = 12192000
SLIDE_CY = 6858000

LAYOUT_TITLE = "Title Slide"
LAYOUT_DIVIDER = "Divider"
LAYOUT_CONTENT = "Content"
LAYOUT_CLOSING = "Closing"
SAMPLE_TEXT = "Title goes here"
CLOSING_TEXT = "Thank you"

# Neutral greys. Not taken from any company template.
_DARK_BG = "1C1C1F"
_LIGHT_BG = "F7F7F5"
_DARK_INK = "F4F4F2"
_LIGHT_INK = "1C1C1F"
_MARK = "5C6B73"

_SLIDE_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
_LAYOUT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
_MASTER_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
_THEME_TYPE = "application/vnd.openxmlformats-officedocument.theme+xml"
_PRES_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"

_REL_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
_REL_CORE = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
_REL_APP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties"
_REL_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
_REL_LAYOUT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
_REL_SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
_REL_THEME = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"


def emu(inches: float) -> int:
    """English Metric Units for one length in inches."""
    return int(round(inches * EMU))


def pack_zip(parts: dict[str, bytes]) -> bytes:
    """Zip parts with a fixed timestamp so the same tree is the same file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name in sorted(parts):
            info = zipfile.ZipInfo(filename=name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, parts[name])
    return buf.getvalue()


def read_parts(blob: bytes) -> dict[str, bytes]:
    """Every part in a package, keyed by its zip name."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _xml(body: str) -> bytes:
    """One XML part, with the declaration Office expects."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body
    ).encode("utf-8")


def _rels(pairs: list[tuple[str, str, str]]) -> bytes:
    """A relationships part. Each triple is id, type, target."""
    rows = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}"/>'
        for rid, rtype, target in pairs
    )
    return _xml(
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rows}</Relationships>"
    )


def _run(text: str, size_pt: int, ink: str) -> str:
    """One text run in Arial at `size_pt`, coloured `ink`."""
    safe = escape(text)
    return (
        f'<a:r><a:rPr lang="en-US" sz="{size_pt * 100}" dirty="0">'
        f'<a:solidFill><a:srgbClr val="{ink}"/></a:solidFill>'
        '<a:latin typeface="Arial"/></a:rPr>'
        f"<a:t>{safe}</a:t></a:r>"
    )


def _shape(shape_id: int, name: str, x: int, y: int, cx: int, cy: int,
           paragraphs: str, placeholder: str = "") -> str:
    """One shape. `placeholder` is the inner ph element, or empty for art."""
    nv = "<p:nvPr/>" if not placeholder else f"<p:nvPr>{placeholder}</p:nvPr>"
    return (
        "<p:sp><p:nvSpPr>"
        f'<p:cNvPr id="{shape_id}" name="{escape(name)}"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        f"{nv}</p:nvSpPr><p:spPr>"
        f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>"
        f"{paragraphs}</p:txBody></p:sp>"
    )


def _mark() -> str:
    """A bar on the layout. The writer leaves this shape alone."""
    return (
        "<p:sp><p:nvSpPr>"
        '<p:cNvPr id="90" name="Mark"/>'
        "<p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{SLIDE_CX}" cy="{emu(0.12)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:solidFill><a:srgbClr val="{_MARK}"/></a:solidFill>'
        "</p:spPr></p:sp>"
    )


def _paragraph(inner: str) -> str:
    """Wrap one run (or several) in a paragraph."""
    return f"<a:p>{inner}</a:p>"


def _layout(name: str, shapes: str, bg: str) -> bytes:
    """One named layout: the mark, then the shapes, on `bg`."""
    return _xml(
        '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'type="obj" preserve="1">'
        f'<p:cSld name="{escape(name)}">'
        "<p:bg><p:bgPr>"
        f'<a:solidFill><a:srgbClr val="{bg}"/></a:solidFill><a:effectLst/>'
        "</p:bgPr></p:bg>"
        "<p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{_mark()}{shapes}"
        "</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>"
        "</p:sldLayout>"
    )


def _slide(shapes: str, bg: str) -> bytes:
    """One slide part. The sample slide is the only one a fresh shell has."""
    return _xml(
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld>"
        "<p:bg><p:bgPr>"
        f'<a:solidFill><a:srgbClr val="{bg}"/></a:solidFill><a:effectLst/>'
        "</p:bgPr></p:bg><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{shapes}</p:spTree></p:cSld>"
        "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"
    )


def _title_shape(text: str, ink: str, y_in: float, size: int, ph: str) -> str:
    """A title placeholder. `ph` is the ph element, including its type."""
    return _shape(
        2, "Title", emu(0.7), emu(y_in), emu(11.9), emu(1.1),
        _paragraph(_run(text, size, ink)),
        placeholder=ph,
    )


def _body_shape(ink: str) -> str:
    """The content layout's body placeholder, empty until a run fills it."""
    return _shape(
        3, "Body", emu(0.9), emu(1.7), emu(11.5), emu(4.6),
        _paragraph(_run("", 14, ink)),
        placeholder='<p:ph type="body" idx="1"/>',
    )


def build_shell(*, variant: str = "dark", body_placeholder: bool = True) -> bytes:
    """One neutral shell. `variant` is "dark" or "light".

    Content has a body placeholder when `body_placeholder` is true. The
    title-only fixture used by the writer passes false: the body is a
    text box the writer places, not a placeholder.
    """
    if variant not in ("dark", "light"):
        raise ValueError(f"unknown variant {variant}")
    bg = _DARK_BG if variant == "dark" else _LIGHT_BG
    ink = _DARK_INK if variant == "dark" else _LIGHT_INK
    title = _title_shape("", ink, 2.6, 32, '<p:ph type="ctrTitle"/>')
    divider = _title_shape("", ink, 2.8, 28, '<p:ph type="title"/>')
    content_shapes = _title_shape("", ink, 0.45, 24, '<p:ph type="title"/>')
    if body_placeholder:
        content_shapes += _body_shape(ink)
    closing = _title_shape(CLOSING_TEXT, ink, 2.8, 32, '<p:ph type="ctrTitle"/>')
    sample = _title_shape(SAMPLE_TEXT, ink, 2.6, 32, '<p:ph type="ctrTitle"/>')
    layouts = [
        (LAYOUT_TITLE, title),
        (LAYOUT_DIVIDER, divider),
        (LAYOUT_CONTENT, content_shapes),
        (LAYOUT_CLOSING, closing),
    ]
    parts: dict[str, bytes] = {}
    layout_rels = []
    for index, (name, shapes) in enumerate(layouts, start=1):
        path = f"ppt/slideLayouts/slideLayout{index}.xml"
        parts[path] = _layout(name, shapes, bg)
        parts[f"ppt/slideLayouts/_rels/slideLayout{index}.xml.rels"] = _rels([
            ("rId1", _REL_MASTER, "../slideMasters/slideMaster1.xml"),
        ])
        layout_rels.append((f"rId{index}", _REL_LAYOUT, f"../slideLayouts/slideLayout{index}.xml"))

    master_shapes = _shape(
        4, "Footer", emu(0.7), emu(7.05), emu(6), emu(0.3),
        _paragraph(_run("Starter", 12, ink)),
    )
    parts["ppt/slideMasters/slideMaster1.xml"] = _xml(
        '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld name="Starter"><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f"{master_shapes}</p:spTree></p:cSld>"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
        'accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" '
        'accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        "<p:sldLayoutIdLst>"
        + "".join(
            f'<p:sldLayoutId id="{2147483649 + i}" r:id="rId{i + 1}"/>'
            for i in range(len(layouts))
        )
        + "</p:sldLayoutIdLst></p:sldMaster>"
    )
    parts["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _rels(
        layout_rels + [("rId5", _REL_THEME, "../theme/theme1.xml")]
    )
    parts["ppt/theme/theme1.xml"] = _THEME
    parts["ppt/slides/slide1.xml"] = _slide(sample, bg)
    parts["ppt/slides/_rels/slide1.xml.rels"] = _rels([
        ("rId1", _REL_LAYOUT, "../slideLayouts/slideLayout1.xml"),
    ])
    parts["ppt/presentation.xml"] = _xml(
        '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'saveSubsetFonts="1">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
        f'<p:sldSz cx="{SLIDE_CX}" cy="{SLIDE_CY}" type="screen16x9"/>'
        '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    )
    parts["ppt/_rels/presentation.xml.rels"] = _rels([
        ("rId1", _REL_MASTER, "slideMasters/slideMaster1.xml"),
        ("rId2", _REL_SLIDE, "slides/slide1.xml"),
    ])
    parts["docProps/core.xml"] = _xml(
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>Starter</dc:title><dc:creator>Agent Desk</dc:creator>"
        "<cp:lastModifiedBy>Agent Desk</cp:lastModifiedBy>"
        "</cp:coreProperties>"
    )
    parts["docProps/app.xml"] = _xml(
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>Agent Desk</Application></Properties>"
    )
    parts["_rels/.rels"] = _rels([
        ("rId1", _REL_OFFICE, "ppt/presentation.xml"),
        ("rId2", _REL_CORE, "docProps/core.xml"),
        ("rId3", _REL_APP, "docProps/app.xml"),
    ])
    overrides = [
        ("/ppt/presentation.xml", _PRES_TYPE),
        ("/ppt/slideMasters/slideMaster1.xml", _MASTER_TYPE),
        ("/ppt/theme/theme1.xml", _THEME_TYPE),
        ("/ppt/slides/slide1.xml", _SLIDE_TYPE),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ("/docProps/app.xml", "application/vnd.openxmlformats-officedocument.extended-properties+xml"),
    ]
    for index in range(1, 5):
        overrides.append((f"/ppt/slideLayouts/slideLayout{index}.xml", _LAYOUT_TYPE))
    rows = "".join(
        f'<Override PartName="{name}" ContentType="{ctype}"/>' for name, ctype in overrides
    )
    parts["[Content_Types].xml"] = _xml(
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{rows}</Types>"
    )
    return pack_zip(parts)


_THEME = _xml(
    '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Starter">'
    "<a:themeElements>"
    '<a:clrScheme name="Starter">'
    + "".join(
        f'<a:{name}><a:srgbClr val="{value}"/></a:{name}>'
        for name, value in (
            ("dk1", "1C1C1F"), ("lt1", "F7F7F5"), ("dk2", "3A3A3E"), ("lt2", "E4E4E1"),
            ("accent1", "5C6B73"), ("accent2", "8A9BA3"), ("accent3", "4F5D64"),
            ("accent4", "B7C4C9"), ("accent5", "6E7C84"), ("accent6", "D5DCDE"),
            ("hlink", "5C6B73"), ("folHlink", "8A9BA3"),
        )
    )
    + "</a:clrScheme>"
    '<a:fontScheme name="Starter"><a:majorFont><a:latin typeface="Arial"/>'
    '<a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/><a:cs typeface=""/>'
    "</a:minorFont></a:fontScheme>"
    '<a:fmtScheme name="Starter"><a:fillStyleLst>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    "</a:fillStyleLst><a:lnStyleLst>"
    '<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    '<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    '<a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    "</a:lnStyleLst><a:effectStyleLst>"
    "<a:effectStyle><a:effectLst/></a:effectStyle>"
    "<a:effectStyle><a:effectLst/></a:effectStyle>"
    "<a:effectStyle><a:effectLst/></a:effectStyle>"
    "</a:effectStyleLst><a:bgFillStyleLst>"
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    "</a:bgFillStyleLst></a:fmtScheme></a:themeElements>"
    "<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>"
)
