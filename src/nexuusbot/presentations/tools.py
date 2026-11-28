"""Agent-callable presentation tools.

A plugin declares which of these host-implemented operations it offers
under ``contributes.tools``; the host owns the schema, the validation,
and the files. Plugin code is never executed: the manifest only says
"this pack exposes presentation_create", and this module does the work
with the same writer and packages the rest of the desk uses.

The operations are deliberately small and deterministic:

``presentation_outline``  turn a one-line brief into a deck outline
``presentation_create``   write a valid .pptx from that outline
``presentation_inspect``  read a .pptx back as slide text and problems
``presentation_render``   make a PDF and slide images when a renderer exists

Tools are also reachable from the CLI (``python -m
nexuusbot.presentations.cli``) and from the session-gated server routes.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

from nexuusbot.presentations.fit import fit_outline
from nexuusbot.presentations.packs import TemplatePack, load_packs
from nexuusbot.presentations.render import render_deck
from nexuusbot.presentations.writer import (
    outline_for,
    package_problems,
    slide_texts,
    write_deck,
)

MAX_SLIDES = 80
MAX_TITLE = 120
MAX_BULLETS = 8
MAX_BULLET = 300
MAX_NOTES = 4000
ROLES = {"title", "section", "content", "closing"}


class ToolError(Exception):
    """A refusal a tool caller can act on."""

    def __init__(self, status: int, message: str):
        """Carry the HTTP status a caller should show with the message."""
        super().__init__(message)
        self.status = status
        self.message = message


_TOOLS = {
    "presentation_outline": {
        "operation": "outline",
        "description": "Turn a one-line brief into a deck outline using a template recipe.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "minLength": 1, "maxLength": 500},
                "template": {"type": "string", "description": "Template pack id; defaults to starter."},
                "recipe": {"type": "string", "description": "Recipe id; defaults to briefing."},
            },
            "required": ["brief"],
            "additionalProperties": False,
        },
    },
    "presentation_create": {
        "operation": "create",
        "description": "Write a .pptx from an outline, or from a brief when no outline is given.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "maxLength": 500},
                "outline": {"type": "object"},
                "template": {"type": "string"},
                "recipe": {"type": "string"},
                "variant": {"type": "string", "enum": ["dark", "light"]},
                "render": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    "presentation_inspect": {
        "operation": "inspect",
        "description": "Read a deck back: every slide's text, its notes, and package problems.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "minLength": 1, "description": "Deck path under the presentation folder."},
            },
            "required": ["file"],
            "additionalProperties": False,
        },
    },
    "presentation_render": {
        "operation": "render",
        "description": "Make a PDF and slide images for a deck, when PowerPoint or LibreOffice is installed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "minLength": 1},
            },
            "required": ["file"],
            "additionalProperties": False,
        },
    },
}


def tool_catalog(packs: list[TemplatePack] | None = None) -> list[dict]:
    """The tools the installed template packs declare, in a stable order."""
    rows = []
    seen: set[str] = set()
    for pack in packs if packs is not None else load_packs():
        manifest = _manifest(pack)
        contributes = manifest.get("contributes")
        if not isinstance(contributes, dict):
            continue
        declared = contributes.get("tools")
        if not isinstance(declared, list):
            continue
        for item in declared:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            spec = _TOOLS.get(name) if isinstance(name, str) else None
            if spec is None or name in seen:
                continue
            seen.add(name)
            rows.append({
                "name": name,
                "description": str(item.get("description") or spec["description"]),
                "inputSchema": spec["inputSchema"],
                "plugin": str(manifest.get("id") or pack.id),
                "pluginVersion": str(manifest.get("version") or pack.version),
                "template": pack.id,
            })
    return rows


def run_tool(name: str, payload: dict, root: Path,
             packs: list[TemplatePack] | None = None, runner=None) -> dict:
    """Run one declared tool against a presentation root.

    ``root`` is the only folder a deck tool may read or write. Every
    returned path is relative to it, posix-style, so an HTTP caller can
    turn the path into a download URL without learning the filesystem.
    Every result also names the plugin whose catalog row answered: when
    two packs declare one name, the listing and the audit agree on who
    answers for the run (the catalog keeps the first declaring pack).
    """
    spec = _TOOLS.get(name)
    if spec is None:
        raise ToolError(404, f"No presentation tool is named {name}.")
    if not isinstance(payload, dict):
        raise ToolError(400, "The tool body must be a JSON object.")
    known = spec["inputSchema"]["properties"]
    unknown = sorted(set(payload) - set(known))
    if unknown:
        raise ToolError(400, f"Unknown field: {unknown[0]}.")
    packs = packs if packs is not None else load_packs()
    catalog = tool_catalog(packs)
    row = next((row for row in catalog if row["name"] == name), None)
    if row is None:
        raise ToolError(404, f"No installed template pack declares {name}.")
    plugin = row["plugin"]
    operation = spec["operation"]
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if operation == "outline":
        return {**_outline(payload, packs), "plugin": plugin}
    if operation == "create":
        result = _create(payload, packs, root, runner)
        return {
            "file": _relative(root, result["path"]),
            "slides": result["slides"],
            "bytes": result["bytes"],
            "renderer": result["renderer"],
            "pdf": _relative(root, result["pdf"]) if result["pdf"] else "",
            "images": [_relative(root, item) for item in result["images"]],
            "note": result["note"],
            "plugin": plugin,
        }
    if operation == "inspect":
        return {**_inspect(payload, root), "plugin": plugin}
    return {**_render(payload, root, runner), "plugin": plugin}


def build_deck(outline: dict, pack: TemplatePack, recipe_id: str, variant: str,
               folder: Path, name: str = "deck.pptx", runner=None,
               render: bool = False) -> dict:
    """Write one deck into ``folder`` and return its files.

    This is the shared path for the CLI and the server tool. The caller
    owns the folder; nothing is written outside it.
    """
    if not isinstance(outline, dict):
        raise ToolError(400, "outline must be an object.")
    recipe = pack.recipe(recipe_id)
    if recipe is None:
        raise ToolError(400, f"Recipe {recipe_id!r} is not in template {pack.id!r}.")
    shell = pack.shell_path(variant)
    if shell is None:
        raise ToolError(400, f"Variant {variant!r} is not in template {pack.id!r}.")
    cleaned = _clean_outline(outline, outline.get("title") or "Untitled")
    fitted, notes = fit_outline(cleaned, recipe, _shorten, 0, sources=[], min_pt=14)
    blob = write_deck(shell.read_bytes(), recipe, fitted)
    problems = package_problems(blob)
    if problems:
        raise ToolError(422, "The deck did not validate: " + "; ".join(problems[:4]))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_bytes(blob)
    rendered = {"renderer": "none", "pdf": "", "images": [], "note": ""}
    if render:
        rendered = render_deck(target, folder / "preview", runner=runner)
    return {
        "path": target,
        "bytes": len(blob),
        "slides": len(fitted.get("slides") or []),
        "fit": notes,
        "renderer": rendered.get("renderer", "none"),
        "pdf": (folder / rendered["pdf"]).resolve() if rendered.get("pdf") else None,
        "images": [(folder / item).resolve() for item in rendered.get("images") or []],
        "note": rendered.get("note", ""),
    }


def inspect_file(path: Path) -> dict:
    """The visible text, notes, slide count and package problems of one deck."""
    path = Path(path)
    if not path.is_file():
        raise ToolError(404, "The deck was not found.")
    try:
        blob = path.read_bytes()
    except OSError as exc:
        raise ToolError(404, f"The deck at {path.name} could not be read: {exc}") from exc
    problems = package_problems(blob)
    try:
        slides = slide_texts(blob)
    except Exception as exc:  # noqa: BLE001 - a broken package is the answer
        raise ToolError(422, f"The deck could not be read: {exc}") from exc
    return {
        "path": path,
        "bytes": len(blob),
        "slides": slides,
        "problems": problems,
        "ok": not problems,
    }


def render_file(path: Path, out_dir: Path, runner=None) -> dict:
    """The render result for one deck, with absolute paths."""
    path = Path(path)
    if not path.is_file():
        raise ToolError(404, "The deck was not found.")
    result = render_deck(path, Path(out_dir), runner=runner)
    return {
        "path": path,
        "outDir": Path(out_dir),
        "renderer": result.get("renderer", "none"),
        "pdf": (Path(out_dir).parent / result["pdf"]).resolve() if result.get("pdf") else None,
        "images": [(Path(out_dir).parent / item).resolve() for item in result.get("images") or []],
        "note": result.get("note", ""),
    }


def resolve_in_root(root: Path, file: str,
                    suffixes: tuple[str, ...] = (".pptx",)) -> Path:
    """One deck path under ``root``, or a refusal.

    Absolute paths and any parent segment are refused rather than
    normalized, because a caller that sends one is confused about the
    contract, not probing for a nicer spelling.
    """
    if not isinstance(file, str) or not file.strip():
        raise ToolError(400, "Send the deck's path as file.")
    raw = file.strip().replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ToolError(400, "file must be relative to the presentation folder.")
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part == ".." for part in parts):
        raise ToolError(400, "file must stay inside the presentation folder.")
    path = (Path(root).resolve() / Path(*parts)).resolve()
    root = Path(root).resolve()
    if path != root and root not in path.parents:
        raise ToolError(400, "file must stay inside the presentation folder.")
    if not path.is_file():
        raise ToolError(404, "The deck was not found.")
    if path.suffix.lower() not in suffixes:
        wanted = ", ".join(suffixes)
        raise ToolError(400, f"This tool reads {wanted} files only.")
    return path


def _outline(payload: dict, packs: list[TemplatePack]) -> dict:
    """Build an outline from a brief and the pack's recipe."""
    brief = _text(payload, "brief", required=True, limit=500)
    pack, recipe_id, recipe = _pack(payload, packs)
    outline = outline_for(brief, recipe)
    return {
        "outline": outline,
        "template": pack.id,
        "templateVersion": pack.version,
        "recipe": recipe_id,
    }


def _create(payload: dict, packs: list[TemplatePack], root: Path, runner) -> dict:
    """Write one deck into a fresh folder under the presentation root."""
    pack, recipe_id, _recipe = _pack(payload, packs)
    variant = _variant(payload, pack)
    raw_outline = payload.get("outline")
    if raw_outline is not None:
        if not isinstance(raw_outline, dict):
            raise ToolError(400, "outline must be an object.")
        title = _text(payload, "brief", limit=500) or str(raw_outline.get("title") or "Untitled")
        outline = _clean_outline(raw_outline, title)
    else:
        brief = _text(payload, "brief", required=True, limit=500)
        outline = outline_for(brief, pack.recipe(recipe_id) or {})
    render = payload.get("render", False)
    if not isinstance(render, bool):
        raise ToolError(400, "render must be true or false.")
    folder = root / f"tool-{secrets.token_hex(8)}"
    return build_deck(outline, pack, recipe_id, variant, folder, runner=runner, render=render)


def _inspect(payload: dict, root: Path) -> dict:
    """Read one deck under the root and keep paths relative to it."""
    path = resolve_in_root(root, payload.get("file", ""))
    result = inspect_file(path)
    return {
        "file": _relative(root, result["path"]),
        "bytes": result["bytes"],
        "slides": result["slides"],
        "problems": result["problems"],
        "ok": result["ok"],
    }


def _render(payload: dict, root: Path, runner) -> dict:
    """Render one deck under the root and keep paths relative to it."""
    path = resolve_in_root(root, payload.get("file", ""))
    result = render_file(path, path.parent / "preview", runner=runner)
    return {
        "file": _relative(root, result["path"]),
        "renderer": result["renderer"],
        "pdf": _relative(root, result["pdf"]) if result["pdf"] else "",
        "images": [_relative(root, item) for item in result["images"]],
        "note": result["note"],
    }


def _pack(payload: dict, packs: list[TemplatePack]) -> tuple[TemplatePack, str, dict]:
    """Resolve the requested template and recipe, or refuse."""
    template = _text(payload, "template", limit=80) or "starter"
    pack = next((item for item in packs if item.id == template), None)
    if pack is None:
        raise ToolError(404, f"Template {template!r} is not installed.")
    recipe_id = _text(payload, "recipe", limit=80) or "briefing"
    recipe = pack.recipe(recipe_id)
    if recipe is None:
        raise ToolError(404, f"Recipe {recipe_id!r} is not in template {template!r}.")
    return pack, recipe_id, recipe


def _variant(payload: dict, pack: TemplatePack) -> str:
    """The requested shell variant, defaulting to dark, or a refusal."""
    variant = _text(payload, "variant", limit=20) or "dark"
    if variant not in pack.variants:
        raise ToolError(400, f"Variant {variant!r} is not in template {pack.id!r}.")
    return variant


def _clean_outline(raw: dict, title: str) -> dict:
    """Validate and shorten a caller's outline before the fit step."""
    slides = raw.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ToolError(400, "outline.slides must be a non-empty list.")
    if len(slides) > MAX_SLIDES:
        raise ToolError(400, f"An outline may hold at most {MAX_SLIDES} slides.")
    cleaned = []
    for index, row in enumerate(slides, start=1):
        if not isinstance(row, dict):
            raise ToolError(400, f"Slide {index} must be an object.")
        role = row.get("role")
        if role not in ROLES:
            raise ToolError(400, f"Slide {index} has an unknown role {role!r}.")
        slide = {"role": role}
        if row.get("title") is not None:
            slide["title"] = _short(str(row["title"]), 200)
        bullets = row.get("bullets")
        if bullets is not None:
            if isinstance(bullets, str):
                bullets = [bullets]
            if not isinstance(bullets, list):
                raise ToolError(400, f"Slide {index} bullets must be a list.")
            slide["bullets"] = [_short(str(item), MAX_BULLET) for item in bullets[:MAX_BULLETS]]
        if row.get("notes") is not None:
            slide["notes"] = _short(str(row["notes"]), MAX_NOTES)
        if row.get("citations") is not None:
            citations = row["citations"]
            if not isinstance(citations, list) or not all(isinstance(item, int) for item in citations):
                raise ToolError(400, f"Slide {index} citations must be whole numbers.")
            slide["citations"] = citations
        cleaned.append(slide)
    if cleaned[0].get("role") != "title":
        cleaned.insert(0, {"role": "title", "title": _short(title, MAX_TITLE)})
    return {"title": _short(title, MAX_TITLE), "slides": cleaned}


def _text(payload: dict, key: str, required: bool = False, limit: int = 200) -> str:
    """One trimmed string field, with its required and length rules."""
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ToolError(400, f"Send {key}.")
        return ""
    if not isinstance(value, str):
        raise ToolError(400, f"{key} must be a string.")
    value = value.strip()
    if len(value) > limit:
        raise ToolError(400, f"{key} is longer than {limit} characters.")
    return value


def _short(value: str, limit: int) -> str:
    """Trim one label to its limit without leaving a dangling space."""
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _shorten(text: str, limit: int, timeout: float) -> str:
    """The fit step's shorten: never invent text, let continuations split."""
    return text


def _relative(root: Path, path: Path | None) -> str:
    """A posix path relative to the root, or the bare name as a fallback."""
    if path is None:
        return ""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _manifest(pack: TemplatePack) -> dict:
    """The pack's manifest, or an empty object when it cannot be read."""
    try:
        raw = json.loads((Path(pack.root) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}
