"""The presentation tool from a terminal.

Major harnesses ship deck tools as a command an agent can call. This is
the same surface the plugin declares: outline, create, inspect, render.
It needs no model endpoint and no browser.

    python -m nexuusbot.presentations.cli list
    python -m nexuusbot.presentations.cli outline --brief "the Q3 review"
    python -m nexuusbot.presentations.cli create --brief "the Q3 review" --out q3.pptx
    python -m nexuusbot.presentations.cli inspect q3.pptx
    python -m nexuusbot.presentations.cli render q3.pptx --out-dir preview
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nexuusbot.presentations.packs import TemplatePack, load_packs
from nexuusbot.presentations.tools import (
    ToolError,
    build_deck,
    inspect_file,
    render_file,
    tool_catalog,
)
from nexuusbot.presentations.writer import outline_for


def main(argv: list[str] | None = None) -> int:
    """Run one command and print JSON. A refusal is exit code 2."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except ToolError as exc:
        print(json.dumps({"error": exc.message}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _parser() -> argparse.ArgumentParser:
    """Build the subcommand parser once."""
    parser = argparse.ArgumentParser(prog="agentdesk.presentations", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="List the installed templates and their recipes.")
    listing.set_defaults(func=_list)
    outline = sub.add_parser("outline", help="Turn a brief into a deck outline.")
    outline.add_argument("--brief", required=True)
    outline.add_argument("--template", default="starter")
    outline.add_argument("--recipe", default="briefing")
    outline.set_defaults(func=_outline)
    create = sub.add_parser("create", help="Write a .pptx.")
    create.add_argument("--brief", default="")
    create.add_argument("--outline", help="A JSON outline file; overrides --brief for the slide text.")
    create.add_argument("--template", default="starter")
    create.add_argument("--recipe", default="briefing")
    create.add_argument("--variant", default="dark", choices=["dark", "light"])
    create.add_argument("--out", required=True, help="The .pptx path to write.")
    create.add_argument("--render", action="store_true", help="Also make a PDF and slide images.")
    create.set_defaults(func=_create)
    inspect = sub.add_parser("inspect", help="Read a deck back as slide text and problems.")
    inspect.add_argument("path")
    inspect.set_defaults(func=_inspect)
    render = sub.add_parser("render", help="Make a PDF and slide images for a deck.")
    render.add_argument("path")
    render.add_argument("--out-dir", help="Defaults to preview beside the deck.")
    render.set_defaults(func=_render)
    return parser


def _run(args) -> dict:
    """Dispatch to the subcommand the parser selected."""
    return args.func(args)


def _list(args) -> dict:
    """List installed templates, their recipes and their declared tools."""
    tools = tool_catalog()
    return {
        "templates": [
            {
                "id": pack.id,
                "name": pack.name,
                "version": pack.version,
                "variants": list(pack.variants),
                "recipes": [Path(item).stem for item in pack.recipes],
                "tools": [row["name"] for row in tools if row["template"] == pack.id],
            }
            for pack in load_packs()
        ]
    }


def _outline(args) -> dict:
    """Turn one brief into an outline without writing a file."""
    if not args.brief.strip():
        raise ToolError(400, "Send a brief.")
    pack = _find_pack(args.template)
    recipe = pack.recipe(args.recipe)
    if recipe is None:
        raise ToolError(404, f"Recipe {args.recipe!r} is not in template {pack.id!r}.")
    return {
        "outline": outline_for(args.brief.strip(), recipe),
        "template": pack.id,
        "templateVersion": pack.version,
        "recipe": args.recipe,
    }


def _create(args) -> dict:
    """Write one deck from a brief or an outline file."""
    pack = _find_pack(args.template)
    outline = None
    if args.outline:
        raw = json.loads(Path(args.outline).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ToolError(400, "The outline file must hold a JSON object.")
        outline = raw
        title = str(raw.get("title") or args.brief or "Untitled")
    else:
        if not args.brief.strip():
            raise ToolError(400, "Send --brief or --outline.")
        title = args.brief.strip()
        recipe = pack.recipe(args.recipe)
        if recipe is None:
            raise ToolError(404, f"Recipe {args.recipe!r} is not in template {pack.id!r}.")
        outline = outline_for(title, recipe)
    out = Path(args.out)
    result = build_deck(
        outline, pack, args.recipe, args.variant, out.parent, name=out.name,
        render=args.render,
    )
    return {
        "file": str(result["path"].resolve()),
        "slides": result["slides"],
        "bytes": result["bytes"],
        "renderer": result["renderer"],
        "pdf": str(result["pdf"]) if result["pdf"] else "",
        "images": [str(item) for item in result["images"]],
        "note": result["note"],
    }


def _inspect(args) -> dict:
    """Read one deck back as slide text and package problems."""
    result = inspect_file(Path(args.path))
    return {
        "file": str(result["path"].resolve()),
        "bytes": result["bytes"],
        "slides": result["slides"],
        "problems": result["problems"],
        "ok": result["ok"],
    }


def _render(args) -> dict:
    """Make a PDF and slide images for one deck."""
    path = Path(args.path)
    out_dir = Path(args.out_dir) if args.out_dir else path.parent / "preview"
    result = render_file(path, out_dir)
    return {
        "file": str(result["path"].resolve()),
        "renderer": result["renderer"],
        "pdf": str(result["pdf"]) if result["pdf"] else "",
        "images": [str(item) for item in result["images"]],
        "note": result["note"],
    }


def _find_pack(template: str) -> TemplatePack:
    """The named installed template pack, or a refusal."""
    pack = next((item for item in load_packs() if item.id == template), None)
    if pack is None:
        raise ToolError(404, f"Template {template!r} is not installed.")
    return pack


if __name__ == "__main__":
    raise SystemExit(main())
