"""Keep slide text inside its box without going under 14 pt.

A content slide that does not fit is shortened once. The shortened text
goes back through the digit guard. What is still too tall becomes as
many continuation slides as it needs. Each bullet stays one bullet:
wrapping uses lines of the budget, it does not invent a new bullet per
line. The point size never changes.
"""

from __future__ import annotations

from nexuusbot.presentations.pipeline import guard_numbers


def slot_budget(region: list, min_pt: int = 14, slack: float = 0.10) -> dict:
    """Characters per line and line count for a region in inches.

    An average glyph is half an em. Slack adds about ten percent.
    """
    width_pt = float(region[2]) * 72
    height_pt = float(region[3]) * 72
    chars = int(width_pt / (min_pt * 0.5) * (1 + slack))
    lines = int(height_pt / (min_pt * 1.2) * (1 + slack))
    return {"charsPerLine": max(chars, 1), "lines": max(lines, 1), "minPt": min_pt}


def fit_outline(outline: dict, recipe: dict, shorten, timeout: float,
                sources: list | None = None, min_pt: int | None = None) -> tuple[dict, list[str]]:
    """Return the outline and the slides that were shortened or split.

    `shorten(text, limit, timeout)` is called at most once per content
    slide. Continuation slides repeat until every slide fits the line budget.
    `min_pt` is the size the writer will draw, so the budget matches the slide.
    """
    rule = next((row for row in recipe.get("slides") or [] if row.get("role") == "content"), {})
    body = (rule.get("slots") or {}).get("body") or {}
    region = body.get("region") or [0.9, 1.7, 11.5, 4.6]
    if min_pt is None:
        min_pt = int(body.get("minPt") or 14)
    min_pt = max(14, int(min_pt))
    budget = slot_budget(region, min_pt)
    limit = budget["charsPerLine"] * budget["lines"]
    notes = []
    slides = []
    for slide in outline.get("slides") or []:
        if slide.get("role") != "content":
            slides.append(slide)
            continue
        bullets = [str(item) for item in (slide.get("bullets") or []) if str(item).strip()]
        if not _fits(bullets, budget):
            shorter = shorten("\n".join(bullets), limit, timeout)
            shorter = guard_numbers(shorter or "", sources or [], slide.get("citations") or [])
            rewritten = [line.strip() for line in shorter.splitlines() if line.strip()]
            bullets = rewritten or bullets
            notes.append(f"{slide.get('title')} (shortened)")
        slides.extend(_continuations(slide, bullets, budget, notes))
    return {**outline, "slides": slides}, notes


def _continuations(slide: dict, bullets: list[str], budget: dict, notes: list[str]) -> list[dict]:
    """As many slides as the bullets need, each one inside the line budget."""
    title = str(slide.get("title") or "")
    rows = []
    remaining = list(bullets)
    first = True
    guard = 0
    while remaining and guard < 20:
        guard += 1
        taken, remaining = _take(remaining, budget)
        if not taken:
            break
        row = {**slide, "bullets": taken}
        if not first:
            row["title"] = f"{title} (cont.)"
            notes.append(f"{title} (cont.)")
        rows.append(row)
        first = False
    return rows or [{**slide, "bullets": bullets}]


def _take(bullets: list[str], budget: dict) -> tuple[list[str], list[str]]:
    """The prefix of bullets that fits, and the rest.

    A single bullet taller than the box is split once, at a line boundary,
    so the next loop can take the remainder.
    """
    taken = []
    used = 0
    width = budget["charsPerLine"]
    room = budget["lines"]
    for index, bullet in enumerate(bullets):
        need = _bullet_lines(bullet, width)
        if taken and used + need > room:
            return taken, bullets[index:]
        if need > room:
            piece, rest = _split_bullet(bullet, budget, room - used)
            if not piece:
                return taken, bullets[index:]
            taken.append(piece)
            rest_bullets = ([rest] if rest else []) + bullets[index + 1:]
            return taken, rest_bullets
        taken.append(bullet)
        used += need
    return taken, []


def _fits(bullets: list[str], budget: dict) -> bool:
    """Whether these bullets use no more lines than the box has."""
    used = sum(_bullet_lines(bullet, budget["charsPerLine"]) for bullet in bullets)
    return used <= budget["lines"]


def _bullet_lines(bullet: str, width: int) -> int:
    """How many lines one bullet wraps to. The bullet stays one bullet."""
    words = str(bullet).split()
    if not words:
        return 1
    lines = 1
    current = 0
    for word in words:
        if current and current + 1 + len(word) <= width:
            current += 1 + len(word)
            continue
        if current:
            lines += 1
            current = 0
        current = min(len(word), width)
        if len(word) > width:
            lines += (len(word) - 1) // width
            current = len(word) % width or width
    return lines


def _split_bullet(bullet: str, budget: dict, room: int) -> tuple[str, str]:
    """The first `room` lines of a bullet, and the text that remains."""
    if room < 1:
        return "", bullet
    words = str(bullet).split()
    width = budget["charsPerLine"]
    kept = []
    current = ""
    lines = 1
    index = 0
    while index < len(words):
        word = words[index]
        piece = word if not current else current + " " + word
        if len(piece) <= width:
            current = piece
            index += 1
            continue
        if current:
            kept.append(current)
            current = ""
            lines += 1
            if lines > room:
                break
            continue
        kept.append(word[:width])
        words[index] = word[width:]
        current = ""
        lines += 1
        if lines > room:
            index += 1
            break
    if current and lines <= room:
        kept.append(current)
    rest = " ".join(words[index:]).strip()
    return " ".join(kept).strip(), rest
