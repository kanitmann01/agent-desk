"""Keep slide text inside its box without going under 14 pt.

Over budget: one shorten call. Still over: a continuation slide. The
point size never changes.
"""

from __future__ import annotations


def slot_budget(region: list, min_pt: int = 14, slack: float = 0.10) -> dict:
    """Characters per line and line count for a region in inches.

    An average glyph is half an em. Slack adds about ten percent.
    """
    width_pt = float(region[2]) * 72
    height_pt = float(region[3]) * 72
    chars = int(width_pt / (min_pt * 0.5) * (1 + slack))
    lines = int(height_pt / (min_pt * 1.2) * (1 + slack))
    return {"charsPerLine": max(chars, 1), "lines": max(lines, 1), "minPt": min_pt}


def fit_outline(outline: dict, recipe: dict, shorten, timeout: float) -> tuple[dict, list[str]]:
    """Return the outline and the slides that were shortened or split.

    `shorten(text, limit, timeout)` is called at most once per content slide.
    """
    rule = next((row for row in recipe.get("slides") or [] if row.get("role") == "content"), {})
    body = (rule.get("slots") or {}).get("body") or {}
    region = body.get("region") or [0.9, 1.7, 11.5, 4.6]
    min_pt = int(body.get("minPt") or 14)
    budget = slot_budget(region, min_pt)
    limit = budget["charsPerLine"] * budget["lines"]
    notes = []
    slides = []
    for slide in outline.get("slides") or []:
        if slide.get("role") != "content":
            slides.append(slide)
            continue
        text = " ".join(slide.get("bullets") or [])
        if len(text) <= limit:
            slides.append(slide)
            continue
        shorter = shorten(text, limit, timeout)
        notes.append(f"{slide.get('title')} (shortened)")
        if len(shorter) <= limit:
            slides.append({**slide, "bullets": _chunks(shorter, budget["charsPerLine"])})
            continue
        first, rest = shorter[:limit], shorter[limit:]
        slides.append({**slide, "bullets": _chunks(first, budget["charsPerLine"])})
        slides.append({
            **slide,
            "title": f"{slide.get('title')} (cont.)",
            "bullets": _chunks(rest, budget["charsPerLine"]),
        })
        notes.append(f"{slide.get('title')} (cont.)")
    return {**outline, "slides": slides}, notes


def _chunks(text: str, width: int) -> list[str]:
    """Break text into lines of at most `width` characters."""
    words = text.split()
    if not words:
        return []
    lines = []
    current = ""
    for word in words:
        piece = word if not current else current + " " + word
        if len(piece) <= width:
            current = piece
            continue
        if current:
            lines.append(current)
        current = word[:width]
    if current:
        lines.append(current)
    return lines
