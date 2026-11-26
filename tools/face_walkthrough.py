"""Face walkthrough: photograph the agent's face on every surface.

The walk boots one isolated desk through ``tools/layout_audit.py``'s own
boot function, so the inert capability runners are always injected, and it
starts the dev-only review sheet from ``frontend/`` for the one mood no
real action reaches. It photographs the face in each mood and theme, plus
the collapsed rail, the phone strip, the two dialogs and the server-rendered
inbox page. A surface with no face is listed by name and never filled in.

The layout audit's request guard is installed before the first navigation,
and the two requests the walk must fail or hold are answered by the walk's
own routes: a research request answered with a 500 for the blocked mood,
and a marketplace retest held (never answered) for the reading mood. No
capability retest is sent, and the ``busy`` condition is never used.

Usage, from anywhere:

    uv run --no-project --with playwright --with keyring --with cryptography \\
        python "<worktree>/tools/face_walkthrough.py"

Useful filters:

    --routes sheet,rail,idle     --themes unkey,coforge
    --widths 1280,800,420        --mock-delay-ms 12000 --record-api DIR
    --sheet-only                 --out DIR

Exit codes: 0 when every planned capture has a photograph, a verdict and a
passed check (surfaces with no face are listed, not failed), 1 when a check
failed or a planned photograph is missing after every other photograph was
taken, and 2 when the desk, the browser or the dev server did not start.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import feedback_walkthrough as feedback
import layout_audit as audit

ROOT = audit.ROOT
DEFAULT_OUT = ROOT / "build" / "face-walkthrough"
FIXED_TIME = audit.FIXED_TIME
VIEWPORT_HEIGHT = audit.VIEWPORT_HEIGHT
DESKTOP_WIDTH = 1280
STRIP_WIDTH = 800
PHONE_WIDTH = 420
MOODS = ("idle", "listening", "thinking", "reading", "working",
         "waiting", "blocked", "done")
REAL_MOODS = tuple(mood for mood in MOODS if mood != "working")
THEMES = ("unkey", "coforge", "momentuum")
MOTIONS = ("normal", "reduce")
PLANNED_WIDTHS = (DESKTOP_WIDTH, STRIP_WIDTH, PHONE_WIDTH)
DEFAULT_WIDTHS = "1280,800,420"
DEFAULT_MOCK_DELAY_MS = 12000
DONE_DURATION_MS = 1600
RAIL_CHECK_TIMEOUT_MS = 15000
DONE_CHECK_TIMEOUT_MS = 60000
SHEET_HOST = "localhost"
SHEET_PORT = 5199
SHEET_URLS = (
    f"http://{SHEET_HOST}:{SHEET_PORT}/static/spa/face-sheet.html",
    f"http://{SHEET_HOST}:{SHEET_PORT}/face-sheet.html",
)
SHEET_URL = SHEET_URLS[0]
RAIL_FACE = '[data-face-slot="rail"] .face-box'
DIALOG_FACE = '[role="dialog"] .face-box'
PHONE_BAR = ".phone-bar"
RESEARCH_FIELD = 'textarea[aria-label="Research question"]'
RESEARCH_BUTTON = "button.cmd-send"
REAL_KINDS = ("rail", "rail-collapsed", "phone-strip", "dialog", "server")
SHEET_QUESTION = (
    "What changed in the regional pipeline this week, and which three deals "
    "need an owner before Friday?"
)
RESEARCH_REFUSAL = (
    "The face walk refused this research request on purpose to photograph "
    "the blocked mood."
)
SHEET_STATE_JS = r"""
(arg) => {
  let el = null;
  if (arg.demo) {
    el = document.querySelector('.face-sheet-demo [data-face-slot="rail"] .face-box');
  } else {
    const grids = document.querySelectorAll('.face-sheet-grid');
    const grid = grids.length > 0 ? grids[0] : null;
    const tiles = grid ? grid.querySelectorAll('.face-sheet-tile') : [];
    const tile = tiles.length > arg.index ? tiles[arg.index] : null;
    el = tile ? tile.querySelector('.face-box') : null;
  }
  const left = el ? el.querySelector('.face-eye-left') : null;
  const right = el ? el.querySelector('.face-eye-right') : null;
  const styleOf = (node) => node ? {
    transform: node.style.transform || '',
    borderRadius: node.style.borderRadius || '',
    shape: node.dataset ? (node.dataset.shape || '') : '',
  } : null;
  return {
    present: !!el,
    mood: el ? (el.getAttribute('data-mood') || '') : '',
    size: el ? (el.getAttribute('data-size') || '') : '',
    title: el ? (el.getAttribute('title') || '') : '',
    theme: document.documentElement.getAttribute('data-theme') || '',
    media: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    signature: el ? {
      box: styleOf(el),
      left: styleOf(left),
      right: styleOf(right),
    } : null,
  };
}
"""
RAIL_STATE_JS = r"""
() => {
  const el = document.querySelector('[data-face-slot="rail"] .face-box');
  return el ? {
    present: true,
    mood: el.getAttribute('data-mood') || '',
    size: el.getAttribute('data-size') || '',
    title: el.getAttribute('title') || '',
  } : {present: false, mood: '', size: '', title: ''};
}
"""
BLOCKED_STATE_JS = r"""
() => {
  const area = document.querySelector('.brief-answer');
  const alert = area ? area.querySelector('[role="alert"], .alert') : null;
  const field = document.querySelector('textarea[aria-label="Research question"]');
  return {
    alert: alert ? ((alert.innerText || alert.textContent || '') + '').trim() : '',
    question: field ? field.value : '',
  };
}
"""
COLLAPSED_STATE_JS = r"""
() => {
  const el = document.querySelector('[data-face-slot="rail"] .face-box');
  return {
    collapsed: !!document.querySelector('.app.rail-collapsed'),
    face: el ? {
      present: true,
      mood: el.getAttribute('data-mood') || '',
      size: el.getAttribute('data-size') || '',
      title: el.getAttribute('title') || '',
    } : {present: false, mood: '', size: '', title: ''},
  };
}
"""
PHONE_STATE_JS = r"""
() => {
  const bar = document.querySelector('.phone-bar');
  return {
    bar: !!bar,
    visible: bar ? getComputedStyle(bar).display !== 'none' : false,
    slots: bar ? bar.querySelectorAll('[data-face-slot]').length : -1,
    faces: bar ? bar.querySelectorAll('.face-box').length : -1,
  };
}
"""
DIALOG_STATE_JS = r"""
() => {
  const dialog = document.querySelector('[role="dialog"]');
  return {
    dialog: !!dialog,
    dialogFaces: dialog ? dialog.querySelectorAll('.face-box').length : -1,
    dialogSlots: dialog ? dialog.querySelectorAll('[data-face-slot]').length : -1,
    railFaces: document.querySelectorAll('[data-face-slot="rail"] .face-box').length,
    railStays: document.querySelectorAll('[data-face-slot="rail"]').length > 0,
  };
}
"""
SERVER_STATE_JS = r"""
() => ({
  theme: document.documentElement.getAttribute('data-theme') || '',
  faceSlots: document.querySelectorAll('[data-face-slot]').length,
  faceBoxes: document.querySelectorAll('.face-box').length,
  railSlots: document.querySelectorAll('.rail .brand [data-face-slot]').length,
  collapsed: !!document.querySelector('.app.rail-collapsed'),
})
"""
REQUIRED_SURFACES = ("review-sheet", "rail", "rail-collapsed", "phone-strip",
                     "dialog-describe", "dialog-tracker", "server-inbox")


class FaceWalkError(Exception):
    """A setup failure the walk cannot continue past."""


@dataclass(frozen=True)
class Shot:
    """One planned photograph and the surface it belongs to."""

    id: str
    surface: str
    kind: str
    theme: str
    mood: str
    motion: str
    condition: str
    width: int
    state: str
    variant: str
    file: str
    locator_kind: str = ""
    route: str = ""


@dataclass
class RouteConfig:
    """The two requests the walk answers or holds, and their current mode."""

    research: str = "pass"
    retest: str = "pass"


def _now_stamp() -> str:
    """A filesystem-friendly timestamp for one run folder."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    """The same instant as a UTC ISO string for the manifest."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_list(value: str) -> list[str]:
    """Split a comma-separated option, dropping blanks and duplicates."""
    seen: list[str] = []
    for part in str(value or "").split(","):
        item = part.strip()
        if item and item not in seen:
            seen.append(item)
    return seen


def _write_json(path: Path, document) -> None:
    """Write one JSON document with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _proxied_paths() -> tuple[str, ...]:
    """The dev server's proxied backend paths, read from vite.config.ts.

    The sheet runs on the dev server's origin, so a rule about other origins
    would never fire. The deny rule therefore reads the same list the proxy
    uses; a config it cannot read is a named setup failure, not a guess.
    """
    path = ROOT / "frontend" / "vite.config.ts"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FaceWalkError(f"cannot read {path}: {exc}") from exc
    match = re.search(r"const backendPaths\s*=\s*\[(.*?)\];", text, re.S)
    if match is None:
        raise FaceWalkError("vite.config.ts has no backendPaths list")
    paths = [value for value in re.findall(r"'([^'\n]+)'", match.group(1))
             if value.startswith("/")]
    if not paths:
        raise FaceWalkError("vite.config.ts backendPaths is empty")
    return tuple(dict.fromkeys(paths))


def _strip_vite_base(path: str) -> str:
    """Drop the dev server's build base so a prefixed asset keeps its name.

    Vite serves this config's assets under ``/static/spa/`` (the production
    mount). Its own client and dependency modules can arrive with that
    prefix, so the asset checks look at the path without it; the proxied
    paths are checked both with and without the prefix.
    """
    base = "/static/spa"
    if path == base:
        return "/"
    if path.startswith(base + "/"):
        return path[len(base):]
    return path


def _is_proxied_path(path: str, proxied: tuple[str, ...]) -> bool:
    """True when the path is one the dev server forwards to a backend.

    The denylist is the operative rule: it is checked before the sheet's
    allowlist, so even an asset-looking proxied path never leaves the dev
    server's own origin.
    """
    for candidate in (path, _strip_vite_base(path)):
        for prefix in proxied:
            if candidate == prefix or candidate.startswith(prefix + "/"):
                return True
    return False


def _is_sheet_asset(path: str) -> bool:
    """True for the sheet's own document, module, stylesheet, font or favicon."""
    candidate = _strip_vite_base(path)
    if candidate in ("/face-sheet.html", "/face-sheet"):
        return True
    if candidate in ("/@vite/client", "/@react-refresh"):
        return True
    for prefix in ("/src/", "/node_modules/", "/@vite/", "/@react-refresh",
                   "/@id/", "/@fs/"):
        if candidate.startswith(prefix):
            return True
    if candidate.endswith((".js", ".mjs", ".css", ".woff", ".woff2", ".ttf",
                           ".otf", ".eot")):
        return True
    return "favicon" in candidate and candidate.endswith((".svg", ".ico", ".png"))


def _sheet_deny_handler(route, allowed_origins: set[str],
                        proxied: tuple[str, ...]) -> None:
    """Abort every request that is not the sheet's own asset.

    Requests from another origin are aborted, every proxied backend path is
    aborted before the allowlist is consulted, and only GETs for the sheet's
    own document, modules, stylesheets, fonts and favicon fall through.
    """
    request = route.request
    url = urllib.parse.urlsplit(request.url)
    origin = f"{url.scheme}://{url.netloc}"
    path = url.path
    if origin not in allowed_origins:
        route.abort()
        return
    if _is_proxied_path(path, proxied):
        route.abort()
        return
    if request.method != "GET" or not _is_sheet_asset(path):
        route.abort()
        return
    route.fallback()


def _install_sheet_deny(target, proxied: tuple[str, ...] | None = None) -> tuple[str, ...]:
    """Install the sheet's deny rule before the sheet page navigates."""
    paths = _proxied_paths() if proxied is None else tuple(proxied)
    origins = {f"http://{SHEET_HOST}:{SHEET_PORT}",
               f"http://127.0.0.1:{SHEET_PORT}"}
    target.route("**/*", lambda route: _sheet_deny_handler(
        route, origins, paths))
    return paths


def _install_real_guard(target, started: list[dict], held: list) -> None:
    """Install the layout audit's guard in its holding mode before navigation.

    Every non-GET is held and never reaches the desk. Exactly one kind of
    request may pass: the research request in the thinking and the done
    captures, and the walk's own research route continues that request
    explicitly. Every other non-GET stays in ``held`` until cleanup aborts it.
    """
    audit._install_request_guard(target, started, held, answered=False)


def _research_handler(route, config: RouteConfig) -> None:
    """Answer the research request with a 500, or continue it to the desk.

    This is the walk's one explicit exception to the holding guard: the
    thinking and done captures need the isolated desk to answer Research, so
    the request is continued here rather than falling back to the hold.
    """
    if urllib.parse.urlsplit(route.request.url).path != "/research":
        route.fallback()
        return
    if config.research == "fail":
        route.fulfill(
            status=500, content_type="application/json",
            body=json.dumps({"error": RESEARCH_REFUSAL}))
        return
    route.continue_()


def _retest_handler(route, config: RouteConfig, held: list) -> None:
    """Hold the marketplace retest without answering it, or pass."""
    if urllib.parse.urlsplit(route.request.url).path != "/api/marketplace/retest":
        route.fallback()
        return
    if config.retest == "hold":
        held.append(route)
        return
    route.fallback()


def _install_real_routes(target, config: RouteConfig, held: list) -> RouteConfig:
    """Install the walk's own research and marketplace-retest routes."""
    target.route("**/research", lambda route: _research_handler(route, config))
    target.route("**/api/marketplace/retest",
                 lambda route: _retest_handler(route, config, held))
    return config


def _slug(text: str) -> str:
    """A filesystem-safe form of one path or label."""
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text).strip())
    return value.strip("-") or "item"


def _sheet_file(theme: str, motion: str, mood: str) -> str:
    """The relative path of one review-sheet photograph."""
    return f"photos/sheet/{theme}/{motion}/{mood}.png"


def _rail_file(theme: str, mood: str, variant: str) -> str:
    """The relative path of one real-app rail photograph."""
    return f"photos/rail/{theme}/{mood}-{variant}.png"


def _build_sheet_shots(themes: list[str]) -> list[Shot]:
    """One photograph per mood, theme and motion mode on the review sheet."""
    shots: list[Shot] = []
    for theme in themes:
        for motion in MOTIONS:
            for mood in MOODS:
                shots.append(Shot(
                    id=f"sheet|{theme}|{mood}|{motion}",
                    surface="review-sheet", kind="sheet", theme=theme,
                    mood=mood, motion=motion, condition="", width=DESKTOP_WIDTH,
                    state="tile", variant="tile",
                    file=_sheet_file(theme, motion, mood),
                    locator_kind="sheet-tile"))
    return shots


def _build_rail_shots(themes: list[str], widths: set[int]) -> list[Shot]:
    """A face crop and a full page per real mood and theme at the desk width."""
    if DESKTOP_WIDTH not in widths:
        return []
    shots: list[Shot] = []
    for theme in themes:
        for mood in REAL_MOODS:
            condition = "fresh" if mood in ("idle", "listening") else "full"
            shots.append(Shot(
                id=f"rail|{theme}|{mood}|face",
                surface="rail", kind="rail", theme=theme, mood=mood,
                motion="normal", condition=condition, width=DESKTOP_WIDTH,
                state="dashboard", variant="face",
                file=_rail_file(theme, mood, "face"),
                locator_kind="rail-face", route="/"))
            shots.append(Shot(
                id=f"rail|{theme}|{mood}|page",
                surface="rail", kind="rail", theme=theme, mood=mood,
                motion="normal", condition=condition, width=DESKTOP_WIDTH,
                state="dashboard", variant="page",
                file=_rail_file(theme, mood, "page"), route="/"))
    return shots


def _build_collapsed_shots(themes: list[str], widths: set[int]) -> list[Shot]:
    """One collapsed-rail photograph per theme on the fresh desk.

    The full seed's four waiting cards make the rail face ``waiting``, so the
    collapsed rail is captured before the seed, where the condition guarantees
    an idle face and the check may demand it.
    """
    if DESKTOP_WIDTH not in widths:
        return []
    return [Shot(
        id=f"rail-collapsed|{theme}|collapsed",
        surface="rail-collapsed", kind="rail-collapsed", theme=theme,
        mood="idle", motion="normal", condition="fresh",
        width=DESKTOP_WIDTH, state="collapsed", variant="page",
        file=f"photos/rail-collapsed/{theme}/collapsed-page.png", route="/")
        for theme in themes]


def _build_phone_shots(themes: list[str], widths: set[int]) -> list[Shot]:
    """One phone-strip photograph per theme at each requested narrow width."""
    shots: list[Shot] = []
    for theme in themes:
        for width in (STRIP_WIDTH, PHONE_WIDTH):
            if width not in widths:
                continue
            shots.append(Shot(
                id=f"phone-strip|{theme}|{width}",
                surface="phone-strip", kind="phone-strip", theme=theme,
                mood="", motion="normal", condition="full", width=width,
                state="closed", variant="page",
                file=f"photos/phone-strip/{theme}/{width}.png", route="/"))
    return shots


def _build_dialog_shots(themes: list[str], widths: set[int]) -> list[Shot]:
    """One photograph of each real dialog per theme at the desk width."""
    if DESKTOP_WIDTH not in widths:
        return []
    shots: list[Shot] = []
    for theme in themes:
        shots.append(Shot(
            id=f"dialog-describe|{theme}",
            surface="dialog-describe", kind="dialog", theme=theme,
            mood="", motion="normal", condition="full", width=DESKTOP_WIDTH,
            state="open", variant="page",
            file=f"photos/dialog-describe/{theme}/dialog-page.png",
            route="/marketplace"))
        shots.append(Shot(
            id=f"dialog-tracker|{theme}",
            surface="dialog-tracker", kind="dialog", theme=theme,
            mood="", motion="normal", condition="full", width=DESKTOP_WIDTH,
            state="open", variant="page",
            file=f"photos/dialog-tracker/{theme}/dialog-page.png",
            route="/"))
    return shots


def _build_server_shots(themes: list[str], widths: set[int]) -> list[Shot]:
    """The server-rendered inbox page, expanded and collapsed, per theme."""
    if DESKTOP_WIDTH not in widths:
        return []
    shots: list[Shot] = []
    for theme in themes:
        for state in ("expanded", "collapsed"):
            shots.append(Shot(
                id=f"server-inbox|{theme}|{state}",
                surface="server-inbox", kind="server", theme=theme,
                mood="", motion="normal", condition="full",
                width=DESKTOP_WIDTH, state=state, variant="page",
                file=f"photos/server-inbox/{theme}/{state}.png", route="/inbox"))
    return shots


def _matches_routes(shot: Shot, routes: list[str]) -> bool:
    """True when any route filter names this shot's surface, mood or state."""
    if not routes:
        return True
    haystack = " ".join((shot.id, shot.surface, shot.kind, shot.mood,
                         shot.theme, shot.state, shot.route)).lower()
    return any(item.lower() in haystack for item in routes)


def build_plan(args) -> list[Shot]:
    """The planned photographs for one run, filters applied.

    The plan holds one record per photograph, so counting the records is
    counting the files the run must leave behind.
    """
    themes = [theme for theme in _parse_list(args.themes) if theme in THEMES]
    if not themes:
        raise FaceWalkError(f"no supported theme in {args.themes!r}")
    widths_raw = _parse_list(args.widths)
    widths: set[int] = set()
    for value in widths_raw:
        try:
            number = int(value)
        except ValueError as exc:
            raise FaceWalkError(f"unsupported width {value!r}") from exc
        if number not in PLANNED_WIDTHS:
            raise FaceWalkError(
                f"unsupported width {value!r}; use "
                + ",".join(str(width) for width in PLANNED_WIDTHS))
        widths.add(number)
    if not widths:
        raise FaceWalkError("no widths selected")
    routes = _parse_list(getattr(args, "routes", ""))
    shots: list[Shot] = []
    if not getattr(args, "sheet_only", False):
        shots.extend(_build_rail_shots(themes, widths))
        shots.extend(_build_collapsed_shots(themes, widths))
        shots.extend(_build_phone_shots(themes, widths))
        shots.extend(_build_dialog_shots(themes, widths))
        shots.extend(_build_server_shots(themes, widths))
    shots.extend(_build_sheet_shots(themes))
    selected = [shot for shot in shots if _matches_routes(shot, routes)]
    if not selected:
        raise FaceWalkError(
            f"route filter {args.routes!r} matches no planned photograph")
    return selected


def _record_for(shot: Shot) -> dict:
    """One record in its not-taken state."""
    return {
        "id": shot.id,
        "surface": shot.surface,
        "kind": shot.kind,
        "theme": shot.theme,
        "mood": shot.mood,
        "motion": shot.motion,
        "condition": shot.condition,
        "width": shot.width,
        "state": shot.state,
        "variant": shot.variant,
        "route": shot.route,
        "file": "",
        "planned_file": shot.file,
        "check": {},
        "verdict": "failed",
        "missing": True,
        "elapsed_s": 0.0,
        "error": "not photographed",
    }


class RunState:
    """One run's plan, records, surface observations and notes."""

    def __init__(self, plan: list[Shot], run_dir: Path) -> None:
        """Start every planned record in its not-taken state."""
        self.plan = plan
        self.run_dir = run_dir
        self.records = {shot.id: _record_for(shot) for shot in plan}
        self.surfaces: dict[str, dict] = {}
        self.notes: list[str] = []
        self.held: list = []
        self.guard_started: list[dict] = []
        self.browser_version = ""
        self.chromium_revision = ""

    def observe_surface(self, name: str, face: bool, observed: bool,
                        detail: str = "") -> None:
        """Record whether one surface carries a face, or that it went unseen."""
        previous = self.surfaces.get(name)
        if previous and previous.get("observed") and previous.get("face"):
            face = True
        self.surfaces[name] = {
            "name": name,
            "face": bool(face),
            "observed": bool(observed) or bool(previous and previous.get("observed")),
            "detail": detail or (previous or {}).get("detail", ""),
        }


def _counts(records: list[dict], run_dir: Path,
            surfaces: dict | None = None) -> dict:
    """Every count the METRIC line prints, measured from the folder and records."""
    files = [path for path in run_dir.rglob("*.png") if path.is_file()]
    present = [record for record in records
               if record.get("file") and (run_dir / record["file"]).is_file()]
    faces_without = [name for name, entry in (surfaces or {}).items()
                     if entry.get("observed") and not entry.get("face")]
    return {
        "moods": len({record["mood"] for record in records if record.get("mood")}),
        "themes": len({record["theme"] for record in records if record.get("theme")}),
        "surfaces": len({record["surface"] for record in records
                         if record.get("surface")}),
        "photos": len(files),
        "reduced_motion": len([record for record in present
                               if record.get("motion") == "reduce"]),
        "missing": len([record for record in records if record.get("missing")]),
        "failed": len([record for record in records
                       if record.get("verdict") != "passed"]),
        "surfaces_without_face": len(faces_without),
    }


def _metric_line(counts: dict) -> str:
    """The one parsed summary line the parent run prints."""
    return (f"METRIC moods={counts['moods']} themes={counts['themes']} "
            f"surfaces={counts['surfaces']} photos={counts['photos']} "
            f"reduced-motion={counts['reduced_motion']} "
            f"missing={counts['missing']}")


def _verdict_line(counts: dict) -> str:
    """The final line, naming failed checks or faceless surfaces by count."""
    if counts["failed"]:
        return f"FACE-WALK FAIL {counts['failed']} failed"
    if counts["surfaces_without_face"]:
        return (f"FACE-WALK PASS WITH {counts['surfaces_without_face']} "
                f"SURFACES WITHOUT A FACE")
    return "FACE-WALK PASS"


def _exit_code(counts: dict, startup_failed: bool) -> int:
    """0 for a complete passing run, 1 for a failed or missing capture, 2 for setup."""
    if startup_failed:
        return 2
    if counts["failed"] or counts["missing"]:
        return 1
    return 0


def _shoot_clip(page, locator, path: Path, pad: int = 8) -> tuple[str, str]:
    """One padded crop from the face's bounding box, never waiting for stillness.

    The box is a layout measurement, so an animating face still yields its
    crop. A box that cannot be measured takes the full page, and the reason
    is returned so the capture is recorded as failed rather than passed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    box = locator.bounding_box()
    if box is None:
        page.screenshot(path=str(path), full_page=True, timeout=20000)
        return (str(path),
                "the face had no bounding box; the photograph is the full page")
    viewport = getattr(page, "viewport_size", None) or {}
    x = max(0.0, float(box["x"]) - pad)
    y = max(0.0, float(box["y"]) - pad)
    width = float(box["width"]) + pad * 2
    height = float(box["height"]) + pad * 2
    if viewport:
        width = min(width, float(viewport["width"]) - x)
        height = min(height, float(viewport["height"]) - y)
    page.screenshot(path=str(path), timeout=20000,
                    clip={"x": x, "y": y, "width": max(1.0, width),
                          "height": max(1.0, height)})
    return str(path), ""


def _shoot_shot(page, shot: Shot, run_dir: Path) -> tuple[str, str]:
    """Take one planned photograph and return its path and any fallback reason.

    A sheet mood and a rail face are padded crops from their ``.face-box``
    bounding box, so an animating face still yields its crop without waiting
    for the animation to settle. Every other shot is the full page. A crop
    that cannot be measured is still photographed as the full page and the
    reason comes back with it; the capture is then recorded as failed.
    """
    path = run_dir / shot.file
    path.parent.mkdir(parents=True, exist_ok=True)
    if shot.locator_kind == "rail-face":
        locator = page.locator(RAIL_FACE).first
    elif shot.locator_kind == "sheet-tile":
        locator = _sheet_tile(page, shot.mood)
    else:
        page.screenshot(path=str(path), full_page=True, timeout=20000)
        return str(path), ""
    if locator.count() == 0:
        page.screenshot(path=str(path), full_page=True, timeout=20000)
        return (str(path),
                "the face element is absent; the photograph is the full page")
    return _shoot_clip(page, locator, path)


def _capture_group(page, shots: list[Shot], check, run: RunState,
                   shoot=None) -> None:
    """Check and photograph every shot in a group, failures included.

    A check that fails or raises is recorded, the photograph is still taken,
    and the next shot is still attempted: one bad capture never stops the
    run.
    """
    for shot in shots:
        started = time.monotonic()
        try:
            check_result = check(shot)
        except Exception as exc:  # noqa: BLE001 - the photograph still happens
            check_result = {
                "kind": "exception",
                "passed": False,
                "detail": f"{type(exc).__name__}: {exc}"[:300],
            }
        file = ""
        note = ""
        error = ""
        try:
            result = (shoot or _shoot_shot)(page, shot, run.run_dir)
            if isinstance(result, tuple):
                file, note = result
            else:
                file = result
        except Exception as exc:  # noqa: BLE001 - record and keep going
            error = f"{type(exc).__name__}: {exc}"[:300]
        if note:
            check_result = dict(check_result)
            check_result["passed"] = False
            detail = str(check_result.get("detail") or "").strip()
            check_result["detail"] = ((detail + "; ") if detail else "") + note
            check_result["capture_note"] = note
            error = error or note
        record = run.records[shot.id]
        relative = ""
        if file:
            try:
                relative = (Path(file).resolve()
                            .relative_to(run.run_dir.resolve()).as_posix())
            except ValueError:  # noqa: BLE001 - a path outside the run is named in full
                relative = str(file).replace("\\", "/")
        record.update({
            "file": relative,
            "check": check_result,
            "verdict": ("passed" if check_result.get("passed") and relative
                        and not note else "failed"),
            "missing": not bool(relative),
            "elapsed_s": round(time.monotonic() - started, 3),
            "error": error,
        })


def _sheet_tile(page, mood: str):
    """The active-preset review-sheet tile for one mood.

    The first ``.face-sheet-grid`` is the active preset's all-moods section,
    and its tiles follow ``FACE_MOODS`` order, so the index is stable. The
    working capture uses the interactive demo instead: its mood selector and
    Step row are the sheet's own working control.
    """
    if mood == "working":
        return page.locator('.face-sheet-demo [data-face-slot="rail"] .face-box').first
    grid = page.locator(".face-sheet-grid").nth(0)
    return grid.locator(".face-sheet-tile").nth(MOODS.index(mood)).locator(
        ".face-box")


def _port_open(host: str, port: int) -> bool:
    """True when something already answers a TCP connect on the port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _ensure_sheet_port_free() -> None:
    """Stop before starting a second dev server on the pinned port."""
    if _port_open(SHEET_HOST, SHEET_PORT):
        raise FaceWalkError(
            f"port {SHEET_PORT} is already in use; stop the other dev server")


def _vite_command() -> list[str]:
    """The dev server command, spelled for this platform."""
    return ["npm.cmd" if os.name == "nt" else "npm", "run", "dev"]


def _start_vite(run_dir: Path):
    """Start Vite as this walk's child process, logging into the run folder."""
    log_path = run_dir / "vite.log"
    log = open(log_path, "w", encoding="utf-8")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(
            _vite_command(), cwd=str(ROOT / "frontend"), stdout=log,
            stderr=subprocess.STDOUT, **kwargs)
    except Exception:
        log.close()
        raise
    return process, log, log_path


def _wait_for_vite(process, log_path: Path, timeout_s: float = 90.0) -> str:
    """Wait until the dev server answers the sheet document, or name the failure."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise FaceWalkError(
                f"the dev server exited {code}; see {log_path}")
        for url in SHEET_URLS:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return url
            except Exception:  # noqa: BLE001 - try the next spelling
                continue
        time.sleep(0.5)
    raise FaceWalkError(
        f"the dev server did not answer {SHEET_URL}; see {log_path}")


def _stop_vite(process, log) -> None:
    """Stop the dev server and its child processes, then close its log."""
    if process is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except Exception:  # noqa: BLE001 - fall back to the direct child
                process.terminate()
        try:
            process.wait(timeout=15)
        except Exception:  # noqa: BLE001 - make sure it is gone
            try:
                process.kill()
            except Exception:  # noqa: BLE001 - already gone
                pass
    finally:
        try:
            log.close()
        except Exception:  # noqa: BLE001 - the log is best effort
            pass


def _sheet_mood_argument(mood: str) -> dict:
    """The sheet script's argument: the demo face for working, a tile otherwise."""
    return {"demo": mood == "working", "index": MOODS.index(mood)}


def _check_sheet(page, shot: Shot, run: RunState) -> dict:
    """Check the sheet's face before its photograph.

    The face must be present, its ``data-mood`` must match, and the requested
    theme must sit on the sheet's root. A reduced-motion capture also checks
    that the media query matches and that the face's own inline pose
    signature is identical after 500 ms.
    """
    argument = _sheet_mood_argument(shot.mood)
    state = page.evaluate(SHEET_STATE_JS, argument)
    present = bool(state.get("present"))
    run.observe_surface("review-sheet", present, True,
                        f"{shot.theme}/{shot.motion}")
    failures: list[str] = []
    if not present:
        failures.append("the face element is absent")
    if state.get("mood") != shot.mood:
        failures.append(f"data-mood is {state.get('mood')!r}")
    if state.get("theme") != shot.theme:
        failures.append(f"data-theme is {state.get('theme')!r}")
    if shot.motion == "reduce":
        if not state.get("media"):
            failures.append("the reduced-motion media query did not match")
        page.wait_for_timeout(500)
        after = page.evaluate(SHEET_STATE_JS, argument)
        if after.get("signature") != state.get("signature"):
            failures.append("the face moved in reduced motion")
    elif state.get("media"):
        failures.append("the normal-motion capture ran under reduced motion")
    return {
        "kind": "sheet-face",
        "mood": shot.mood,
        "motion": shot.motion,
        "theme": shot.theme,
        "passed": not failures,
        "detail": "; ".join(failures) if failures else "face mood, theme and "
                  + ("still pose" if shot.motion == "reduce" else "motion mode")
                  + " hold",
        "state": state,
    }


def _prepare_sheet_working(page) -> None:
    """Choose the sheet's working mood and step it once, as the sheet offers."""
    button = page.get_by_role("button", name="working", exact=True)
    if button.count() == 0:
        raise FaceWalkError("the review sheet has no working mood button")
    button.first.click()
    step = page.get_by_role("button", name=re.compile(r"^Step row"))
    if step.count() > 0:
        step.first.click()
    page.wait_for_selector(
        '.face-sheet-demo [data-face-slot="rail"] .face-box[data-mood="working"]',
        timeout=10000)


def _open_sheet_page(browser, motion: str, proxied: tuple[str, ...],
                     run: RunState, sheet_url: str = SHEET_URL):
    """Create one sheet context with the guard and deny rule before its goto."""
    options = {
        "viewport": {"width": DESKTOP_WIDTH, "height": VIEWPORT_HEIGHT},
        "device_scale_factor": 1,
    }
    if motion == "reduce":
        options["reduced_motion"] = "reduce"
    context = browser.new_context(**options)
    guard_started: list[dict] = []
    held: list = []
    audit._install_request_guard(context, guard_started, held, answered=False)
    _install_sheet_deny(context, proxied)
    page = context.new_page()
    page.emulate_media(reduced_motion=("reduce" if motion == "reduce"
                                      else "no-preference"))
    page.goto(sheet_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector(".face-sheet-grid .face-sheet-tile", timeout=60000)
    page.wait_for_timeout(1000)
    run.notes.append(f"sheet page ready ({motion}) at {sheet_url}")
    return context, page, held


def _run_sheet_phase(args, run: RunState, plan: list[Shot],
                     playwright) -> None:
    """Start the dev server, photograph the sheet, and stop it in finally.

    Nothing from the sheet page may leave the dev server: the deny rule is
    installed on every sheet context before its first navigation, and every
    proxied backend path is aborted before the asset allowlist is consulted.
    """
    shots = [shot for shot in plan if shot.kind == "sheet"]
    if not shots:
        return
    _ensure_sheet_port_free()
    process = None
    log = None
    browser = None
    pages: dict[str, tuple] = {}
    held_all: list = []
    try:
        process, log, log_path = _start_vite(run.run_dir)
        sheet_url = _wait_for_vite(process, log_path)
        run.notes.append("dev server started")
        browser = playwright.chromium.launch(headless=True)
        if not run.browser_version:
            run.browser_version = str(getattr(browser, "version", ""))
        proxied = _proxied_paths()
        for motion in MOTIONS:
            if not any(shot.motion == motion for shot in shots):
                continue
            context, page, held = _open_sheet_page(
                browser, motion, proxied, run, sheet_url)
            pages[motion] = (context, page)
            held_all.extend(held)
        themes = list(dict.fromkeys(shot.theme for shot in shots))
        for theme in themes:
            for motion in MOTIONS:
                if motion not in pages:
                    continue
                _context, page = pages[motion]
                page.evaluate(
                    "(theme) => document.documentElement.setAttribute("
                    "'data-theme', theme)", theme)
                page.wait_for_timeout(100)
                group = [shot for shot in shots
                         if shot.theme == theme and shot.motion == motion]
                if any(shot.mood == "working" for shot in group):
                    _prepare_sheet_working(page)
                _capture_group(
                    page, group,
                    lambda shot, sheet=page: _check_sheet(sheet, shot, run),
                    run)
        for _context, _page in pages.values():
            _context.close()
        pages.clear()
    finally:
        _abort_held(held_all)
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - close everything that opened
                pass
        _stop_vite(process, log)


def _set_theme_storage(page, theme: str) -> None:
    """Pin the theme in localStorage; the next navigation applies it."""
    page.evaluate(
        "(theme) => { try { localStorage.setItem('agentdesk.theme', theme); } "
        "catch (error) {} }", theme)


def _settle_dashboard(page) -> None:
    """Wait for the dashboard's command bar, the research actions' anchor."""
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_timeout(600)
    page.wait_for_selector(RESEARCH_BUTTON, state="visible", timeout=15000)


def _focus_research(page) -> dict:
    """Focus the research question field, the action that reaches listening."""
    field = page.locator(RESEARCH_FIELD).first
    field.focus()
    return {"field": RESEARCH_FIELD}


def _ask_research(page, question: str) -> dict:
    """Type a question and start Research, the action behind three moods."""
    field = page.locator(RESEARCH_FIELD).first
    field.fill(question)
    page.locator(RESEARCH_BUTTON).first.click()
    return {"question": question}


def _act_idle(page, base: str) -> dict:
    """Land on the dashboard with nothing active and no waiting cards."""
    page.goto(base + "/", wait_until="domcontentloaded", timeout=30000)
    _settle_dashboard(page)
    return {"action": "idle"}


def _act_listening(page, base: str) -> dict:
    """Focus the research field on the freshly booted dashboard."""
    _act_idle(page, base)
    return _focus_research(page)


def _act_thinking(page, base: str, question: str) -> dict:
    """Type a question and start Research while the mock holds the answer."""
    _act_idle(page, base)
    return _ask_research(page, question)


def _act_blocked(page, base: str, config: RouteConfig, question: str) -> dict:
    """Ask Research with the walk's own 500 route in place."""
    config.research = "fail"
    _act_idle(page, base)
    return _ask_research(page, question)


def _act_reading(page, base: str, config: RouteConfig) -> dict:
    """Open a non-fresh card's menu and choose Re-test now while it is held."""
    config.retest = "hold"
    _act_idle(page, base)
    return _open_retest_menu(page)


def _act_waiting(page, base: str) -> dict:
    """Land on the dashboard of the full seed, whose sample data waits."""
    return _act_idle(page, base)


def _act_done(page, base: str) -> dict:
    """The done mood follows the successful research action already in flight."""
    return {"action": "done", "base": base}


def _open_retest_menu(page) -> dict:
    """Find the first widget whose menu offers Re-test now and click it.

    A fresh card's menu has only Manage plugins, so the loop opens each
    widget's menu until the Re-test now item appears, closing the others.
    """
    triggers = page.locator('button[aria-label^="Widget options"]')
    for index in range(min(triggers.count(), 30)):
        trigger = triggers.nth(index)
        label = trigger.get_attribute("aria-label") or ""
        trigger.click()
        item = page.get_by_role("menuitem", name="Re-test now", exact=True)
        if item.count() > 0:
            item.first.click()
            return {"card": label}
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
    raise FaceWalkError("no non-fresh plugin card offers Re-test now")


def _open_describe_dialog(page, base: str) -> None:
    """Open the plugin description dialog on the catalog page."""
    page.goto(base + "/marketplace", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(600)
    trigger = page.get_by_role(
        "button", name="Describe a plugin in plain English", exact=True)
    if trigger.count() == 0:
        raise FaceWalkError("no describe-a-plugin control on the catalog page")
    trigger.first.click()
    page.wait_for_selector('.setup-sheet[role="dialog"]', timeout=10000)


def _open_tracker_dialog(page, base: str) -> None:
    """Open the tracker setup dialog from the seeded tracker card."""
    page.goto(base + "/", wait_until="domcontentloaded", timeout=30000)
    _settle_dashboard(page)
    buttons = page.locator(".tracker-card button")
    for index in range(min(buttons.count(), 20)):
        button = buttons.nth(index)
        if (button.inner_text() or "").strip() in ("Set up", "Edit"):
            button.click()
            page.wait_for_selector('.setup-sheet[role="dialog"]', timeout=10000)
            return
    raise FaceWalkError("no Set up or Edit control on the tracker card")


def _close_dialog(page) -> None:
    """Close an open dialog, by its own control or the Escape key."""
    close = page.get_by_role("button", name="Close dialog", exact=True)
    if close.count() > 0:
        close.first.click()
    else:
        page.keyboard.press("Escape")
    page.wait_for_timeout(150)


def _wait_mood(page, mood: str, timeout_ms: int, poll_ms: int = 60) -> dict:
    """Poll the rail face until its data-mood is the expected one."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = page.evaluate(RAIL_STATE_JS)
        except Exception:  # noqa: BLE001 - navigation briefly removes the face
            last = {}
        if last.get("present") and last.get("mood") == mood:
            return last
        page.wait_for_timeout(poll_ms)
    return last


def _check_rail(page, shot: Shot, run: RunState, question: str = "") -> dict:
    """Check the rail face's mood, size and the two moods with an extra fact."""
    timeout = (DONE_CHECK_TIMEOUT_MS if shot.mood == "done"
               else RAIL_CHECK_TIMEOUT_MS)
    state = _wait_mood(page, shot.mood, timeout,
                       poll_ms=50 if shot.mood == "done" else 60)
    present = bool(state.get("present"))
    run.observe_surface("rail", present, True, f"{shot.theme}/{shot.mood}")
    failures: list[str] = []
    if not present:
        failures.append("the rail face is absent")
    if state.get("mood") != shot.mood:
        failures.append(f"data-mood is {state.get('mood')!r}")
    if present and state.get("size") != "md":
        failures.append(f"data-size is {state.get('size')!r}, not the rail size")
    extra: dict = {}
    if shot.mood == "waiting":
        match = re.search(r"(\d+) waiting in Inbox", state.get("title") or "")
        extra["waiting_count"] = int(match.group(1)) if match else None
        if match is None:
            failures.append("the face tooltip does not name the waiting count")
    if shot.mood == "blocked":
        facts = page.evaluate(BLOCKED_STATE_JS)
        extra["blocked"] = facts
        if not str(facts.get("alert") or "").strip():
            failures.append("the answer area keeps no failure")
        if question and facts.get("question") != question:
            failures.append("the typed question is not kept")
    return {
        "kind": "rail-face",
        "mood": shot.mood,
        "passed": not failures,
        "detail": "; ".join(failures) if failures else "rail face mood holds",
        "state": state,
        "extra": extra,
    }


def _check_collapsed(page, shot: Shot, run: RunState) -> dict:
    """Check the collapsed rail still carries an idle face at rail size."""
    state = page.evaluate(COLLAPSED_STATE_JS)
    face = state.get("face") or {}
    present = bool(face.get("present"))
    run.observe_surface("rail-collapsed", present, True, shot.theme)
    failures: list[str] = []
    if not state.get("collapsed"):
        failures.append("the rail did not collapse")
    if not present:
        failures.append("the collapsed rail has no face")
    if face.get("mood") != "idle":
        failures.append(f"data-mood is {face.get('mood')!r}")
    if face.get("size") != "md":
        failures.append(f"data-size is {face.get('size')!r}, not the rail size")
    return {
        "kind": "collapsed-rail",
        "passed": not failures,
        "detail": "; ".join(failures) if failures else "collapsed rail keeps its face",
        "state": state,
    }


def _check_phone(page, shot: Shot, run: RunState) -> dict:
    """Check that the phone strip carries no face slot and no face box."""
    state = page.evaluate(PHONE_STATE_JS)
    run.observe_surface("phone-strip", False, True,
                        f"{shot.theme}/{shot.width}")
    failures: list[str] = []
    if not state.get("bar"):
        failures.append("the phone strip is absent")
    if state.get("slots") != 0:
        failures.append(f"{state.get('slots')} face slot(s) inside the phone strip")
    if state.get("faces") != 0:
        failures.append(f"{state.get('faces')} face box(es) inside the phone strip")
    return {
        "kind": "phone-strip",
        "passed": not failures,
        "detail": "; ".join(failures) if failures else "phone strip has no face",
        "state": state,
    }


def _check_dialog(page, shot: Shot, run: RunState) -> dict:
    """Record whether the open dialog mounts a face and whether the rail stays."""
    state = page.evaluate(DIALOG_STATE_JS)
    open_dialog = bool(state.get("dialog"))
    faces = int(state.get("dialogFaces") or 0)
    run.observe_surface(shot.surface, faces > 0, open_dialog,
                        f"{shot.theme}: {faces} face(s)")
    failures: list[str] = []
    if not open_dialog:
        failures.append("the dialog did not open")
    return {
        "kind": "dialog",
        "passed": not failures,
        "detail": ("dialog face count " + str(faces) + "; rail face in page "
                   + str(int(state.get("railFaces") or 0)))
                  if not failures else "; ".join(failures),
        "state": state,
    }


def _check_server(page, shot: Shot, run: RunState) -> dict:
    """Record the server-rendered rail's missing face and the requested state."""
    state = page.evaluate(SERVER_STATE_JS)
    any_face = int(state.get("faceSlots") or 0) + int(state.get("faceBoxes") or 0)
    run.observe_surface("server-inbox", any_face > 0, True,
                        f"{shot.theme}/{shot.state}: {any_face} face node(s)")
    failures: list[str] = []
    if state.get("theme") != shot.theme:
        failures.append(f"data-theme is {state.get('theme')!r}")
    if bool(state.get("collapsed")) != (shot.state == "collapsed"):
        failures.append(f"rail collapsed is {bool(state.get('collapsed'))}")
    return {
        "kind": "server-page",
        "passed": not failures,
        "detail": ("server rail face count " + str(any_face))
                  if not failures else "; ".join(failures),
        "state": state,
    }


def _capture_surface(page, shots: list[Shot], prep, check, run: RunState,
                     shoot=None) -> None:
    """Run one surface's action, then check and photograph every shot.

    A failed action is recorded as a failed check for the group, and the
    page is still photographed, so one broken surface never stops the run.
    """
    if not shots:
        return
    try:
        prep()
    except Exception as exc:  # noqa: BLE001 - the photograph still happens
        detail = f"{type(exc).__name__}: {exc}"[:300]
        run.notes.append(f"{shots[0].surface}: {detail}")

        def failed(_shot: Shot) -> dict:
            """Name the action failure as this capture's failed check."""
            return {"kind": "action", "passed": False, "detail": detail}

        _capture_group(page, shots, failed, run, shoot=shoot)
        return
    _capture_group(page, shots, check, run, shoot=shoot)


def _api_recorder(record_dir: Path):
    """A response listener that saves GET /api JSON bodies, or None."""
    def handler(response) -> None:
        """Write one JSON API body; a read failure is skipped, not raised."""
        try:
            if response.request.method != "GET":
                return
            api_path = urllib.parse.urlsplit(response.url).path
            if not api_path.startswith("/api/"):
                return
            body = response.body()
            if not body:
                return
            json.loads(body)
        except Exception:  # noqa: BLE001 - recording never fails a page
            return
        target = record_dir / (_slug(api_path.lstrip("/")) + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    return handler


def _boot_isolated_desk(condition: str, tmp_root: Path) -> dict:
    """Boot one isolated desk through the layout audit's boot function.

    This is the instrument's only boot path: the audit's boot injects the
    inert capability runners, the file-backed keychain and the fixed store
    clocks. It never calls the server factory itself.
    """
    return audit._boot_desk(condition, tmp_root)


def _save_mock_connection(context, base: str, mock_port: int) -> None:
    """Save a connection to the loopback mock through the walkthrough helper."""
    feedback._save_mock_connection(context, base, mock_port)


def _abort_held(held: list) -> None:
    """Abort every held request so the page can close cleanly."""
    audit._abort_held(held)
    held.clear()


def _tool_version(command: list[str]) -> str:
    """One tool's version line, or 'unknown' when it cannot be read."""
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=15)
        text = (done.stdout or done.stderr or "").strip()
        return text.splitlines()[0].strip() if text else "unknown"
    except Exception:  # noqa: BLE001 - a missing tool is recorded, not fatal
        return "unknown"


def _commit() -> str:
    """The checkout's HEAD commit, or the empty string."""
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15)
        return done.stdout.strip() if done.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - an absent git is recorded, not fatal
        return ""


def _package_version(name: str) -> str:
    """One installed Python package's version, or 'unknown'."""
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:  # noqa: BLE001 - the gate environment may not carry it
        return "unknown"


def _chromium_revision() -> str:
    """The Playwright manifest's Chromium revision, or 'unknown'."""
    try:
        import playwright
        manifest = (Path(playwright.__file__).resolve().parent
                    / "driver" / "package" / "browsers.json")
        document = json.loads(manifest.read_text(encoding="utf-8"))
        for browser in document.get("browsers", []):
            if browser.get("name") == "chromium":
                return str(browser.get("revision", "unknown"))
    except Exception:  # noqa: BLE001 - recorded as unknown, never a failure
        return "unknown"
    return "unknown"


def _tool_versions() -> dict:
    """The tool versions the manifest records."""
    vite = "unknown"
    try:
        package = json.loads((ROOT / "frontend" / "package.json").read_text(
            encoding="utf-8"))
        vite = str((package.get("devDependencies") or {}).get("vite", "unknown"))
    except Exception:  # noqa: BLE001 - the manifest says unknown, not nothing
        pass
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return {
        "python": sys.version.split()[0],
        "playwright": _package_version("playwright"),
        "node": _tool_version(["node", "--version"]),
        "npm": _tool_version([npm, "--version"]),
        "vite": vite,
    }


def _meta(args, run_dir: Path, started: float) -> dict:
    """The manifest's meta block: commit, tools, browser, viewport and clocks."""
    return {
        "commit": _commit(),
        "tool_versions": _tool_versions(),
        "browser_version": "",
        "chromium_revision": _chromium_revision(),
        "viewport": {"width": DESKTOP_WIDTH, "height": VIEWPORT_HEIGHT},
        "fixed_time": FIXED_TIME,
        "mock_delay_ms": int(args.mock_delay_ms),
        "themes": _parse_list(args.themes),
        "widths": _parse_list(args.widths),
        "sheet_only": bool(args.sheet_only),
        "record_api": str(getattr(args, "record_api", "")),
        "run_dir": str(run_dir),
        "started_at": _now_iso(),
        "finished_at": "",
        "elapsed_s": round(time.monotonic() - started, 3),
    }


def _manifest(run: RunState, args, meta: dict, surfaces: dict | None = None) -> dict:
    """The manifest document, with every capture and the measured counts."""
    records = list(run.records.values())
    counts = _counts(records, run.run_dir, run.surfaces if surfaces is None
                     else surfaces)
    surfaces = []
    for name in sorted(run.surfaces):
        entry = dict(run.surfaces[name])
        if entry["observed"]:
            surfaces.append(entry)
    meta = dict(meta)
    meta["browser_version"] = run.browser_version
    meta["notes"] = list(run.notes)
    return {
        "tool": "face_walkthrough",
        "version": 1,
        "meta": meta,
        "reduced_motion_check": (
            "media query matches AND the face's inline pose signature "
            "(box transform, both eye transforms, shapes and radii) is "
            "identical after 500 ms; derived from brain.ts:599-603 and "
            "645-648, which apply the static pose and schedule no frame"),
        "surfaces": surfaces,
        "captures": records,
        "counts": counts,
        "metrics_line": _metric_line(counts),
        "verdict_line": _verdict_line(counts),
    }


def _photograph_real_app(page, context, desk: dict, config: RouteConfig,
                         run: RunState, shots: list[Shot],
                         tmp_root: Path) -> None:
    """Photograph every planned real-app surface on the booted desk."""
    base = desk["base"]
    rail = [shot for shot in shots if shot.kind == "rail"]
    fresh = [shot for shot in shots if shot.condition == "fresh"]
    fresh_rail = [shot for shot in fresh if shot.kind == "rail"]
    if fresh:
        for theme in dict.fromkeys(shot.theme for shot in fresh):
            _set_theme_storage(page, theme)
            for mood in ("idle", "listening"):
                group = [shot for shot in fresh_rail
                         if shot.theme == theme and shot.mood == mood]
                if not group:
                    continue
                if mood == "idle":
                    prep = lambda: _act_idle(page, base)  # noqa: E731
                else:
                    prep = lambda: _act_listening(page, base)  # noqa: E731
                _capture_surface(
                    page, group, prep,
                    lambda shot: _check_rail(page, shot, run, SHEET_QUESTION),
                    run)
            collapsed = [shot for shot in fresh
                         if shot.kind == "rail-collapsed"
                         and shot.theme == theme]
            if collapsed:
                def prep_collapsed(theme=theme) -> None:
                    """Collapse the rail on the fresh desk's dashboard."""
                    _set_theme_storage(page, theme)
                    page.evaluate(
                        "() => { try { localStorage.setItem("
                        "'agentdesk.railCollapsed', '1'); } catch (error) {} }")
                    _act_idle(page, base)
                    page.wait_for_selector(".app.rail-collapsed", timeout=10000)

                _capture_surface(
                    page, collapsed, prep_collapsed,
                    lambda shot: _check_collapsed(page, shot, run), run)
                page.evaluate(
                    "() => { try { localStorage.setItem("
                    "'agentdesk.railCollapsed', '0'); } catch (error) {} }")
    full = [shot for shot in shots if shot.condition == "full"]
    if not full:
        return
    notes = audit._seed(context, base, "full", tmp_root)
    run.notes.extend(notes)
    for theme in dict.fromkeys(shot.theme for shot in full):
        _set_theme_storage(page, theme)
        waiting = [shot for shot in rail
                   if shot.theme == theme and shot.mood == "waiting"]
        if waiting:
            _capture_surface(page, waiting, lambda: _act_waiting(page, base),
                             lambda shot: _check_rail(
                                 page, shot, run, SHEET_QUESTION), run)
        blocked = [shot for shot in rail
                   if shot.theme == theme and shot.mood == "blocked"]
        if blocked:
            _capture_surface(
                page, blocked,
                lambda: _act_blocked(page, base, config, SHEET_QUESTION),
                lambda shot: _check_rail(page, shot, run, SHEET_QUESTION), run)
            config.research = "pass"
        reading = [shot for shot in rail
                   if shot.theme == theme and shot.mood == "reading"]
        if reading:
            _capture_surface(
                page, reading, lambda: _act_reading(page, base, config),
                lambda shot: _check_rail(page, shot, run, SHEET_QUESTION), run)
            _abort_held(run.held)
            config.retest = "pass"
        thinking = [shot for shot in rail
                    if shot.theme == theme and shot.mood == "thinking"]
        done = [shot for shot in rail
                if shot.theme == theme and shot.mood == "done"]
        if thinking or done:
            config.research = "pass"
            if thinking:
                _capture_surface(
                    page, thinking,
                    lambda: _act_thinking(page, base, SHEET_QUESTION),
                    lambda shot: _check_rail(page, shot, run, SHEET_QUESTION),
                    run)
            if done:
                done_prep = ((lambda: _act_done(page, base)) if thinking
                             else (lambda: _act_thinking(
                                 page, base, SHEET_QUESTION)))
                _capture_surface(
                    page, done, done_prep,
                    lambda shot: _check_rail(page, shot, run, SHEET_QUESTION),
                    run)
        describe = [shot for shot in shots
                    if shot.surface == "dialog-describe"
                    and shot.theme == theme]
        if describe:
            def prep_describe(theme=theme) -> None:
                """Open the plugin description dialog on the catalog page."""
                _set_theme_storage(page, theme)
                _open_describe_dialog(page, base)

            _capture_surface(page, describe, prep_describe,
                             lambda shot: _check_dialog(page, shot, run), run)
            _close_dialog(page)
        tracker = [shot for shot in shots
                   if shot.surface == "dialog-tracker" and shot.theme == theme]
        if tracker:
            def prep_tracker(theme=theme) -> None:
                """Open the tracker setup dialog from the seeded card."""
                _set_theme_storage(page, theme)
                _open_tracker_dialog(page, base)

            _capture_surface(page, tracker, prep_tracker,
                             lambda shot: _check_dialog(page, shot, run), run)
            _close_dialog(page)
        for state in ("expanded", "collapsed"):
            server = [shot for shot in shots
                      if shot.surface == "server-inbox"
                      and shot.theme == theme and shot.state == state]
            if not server:
                continue

            def prep_server(theme=theme, state=state) -> None:
                """Open the server-rendered inbox with the requested rail state."""
                _set_theme_storage(page, theme)
                page.evaluate(
                    "(value) => { try { localStorage.setItem("
                    "'agentdesk.railCollapsed', value); } catch (error) {} }",
                    "1" if state == "collapsed" else "0")
                page.goto(base + "/inbox", wait_until="domcontentloaded",
                          timeout=30000)
                page.wait_for_selector(".app", timeout=15000)
                page.wait_for_timeout(500)

            _capture_surface(page, server, prep_server,
                             lambda shot: _check_server(page, shot, run), run)
        for width in (STRIP_WIDTH, PHONE_WIDTH):
            phone = [shot for shot in shots
                     if shot.surface == "phone-strip"
                     and shot.theme == theme and shot.width == width]
            if not phone:
                continue

            def prep_phone(theme=theme, width=width) -> None:
                """Load the dashboard at the requested phone width."""
                _set_theme_storage(page, theme)
                page.set_viewport_size(
                    {"width": width, "height": VIEWPORT_HEIGHT})
                page.goto(base + "/", wait_until="domcontentloaded",
                          timeout=30000)
                page.wait_for_selector(".phone-bar", state="attached",
                                       timeout=15000)
                page.wait_for_timeout(400)

            _capture_surface(page, phone, prep_phone,
                             lambda shot: _check_phone(page, shot, run), run)
            page.set_viewport_size(
                {"width": DESKTOP_WIDTH, "height": VIEWPORT_HEIGHT})


def run_tmp_root(run: RunState) -> Path:
    """The desk's temporary root, named on the run for the seed."""
    return Path(run.tmp_root)


def _run_real_phase(args, run: RunState, plan: list[Shot],
                    playwright) -> None:
    """Boot the isolated desk and photograph the real app's faces."""
    shots = [shot for shot in plan if shot.kind in REAL_KINDS]
    if not shots:
        return
    tmp_root = Path(tempfile.mkdtemp(prefix="agentdesk-face-"))
    mock = None
    desk = None
    browser = None
    context = None
    config = RouteConfig()
    try:
        mock, mock_port = audit._start_mock(int(args.mock_delay_ms))
        audit._pin_environment(tmp_root / "data", "full", mock_port)
        if "src" not in sys.path:
            sys.path.insert(0, str(ROOT / "src"))
        if "tools" not in sys.path:
            sys.path.insert(0, str(ROOT / "tools"))
        desk = _boot_isolated_desk("full", tmp_root)
        run.notes.append(f"desk {desk['base']}")
        browser = playwright.chromium.launch(headless=True)
        run.browser_version = str(getattr(browser, "version", ""))
        context = browser.new_context(
            viewport={"width": DESKTOP_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=1)
        _install_real_guard(context, run.guard_started, run.held)
        _install_real_routes(context, config, run.held)
        if getattr(args, "record_api", ""):
            record_dir = Path(args.record_api)
            record_dir.mkdir(parents=True, exist_ok=True)
            context.on("response", _api_recorder(record_dir))
        page = context.new_page()
        page.clock.install(time=FIXED_TIME)
        page.clock.set_fixed_time(FIXED_TIME)
        page.emulate_media(reduced_motion="no-preference")
        page.goto(desk["base"] + "/auth/" + desk["token"],
                  wait_until="domcontentloaded", timeout=30000)
        if page.url.rstrip("/") != desk["base"].rstrip("/"):
            raise FaceWalkError(f"auth landed on {page.url}, not the dashboard")
        _save_mock_connection(context, desk["base"], mock_port)
        run.notes.append("mock connection saved")
        _photograph_real_app(page, context, desk, config, run, shots,
                             tmp_root)
        context.close()
        context = None
    finally:
        _abort_held(run.held)
        if context is not None:
            try:
                context.close()
            except Exception:  # noqa: BLE001 - close everything that opened
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - close everything that opened
                pass
        if desk is not None:
            errors = audit._stop_desk(desk)
            if errors:
                run.notes.extend(f"stop: {error}" for error in errors)
        if mock is not None:
            try:
                mock.shutdown()
                mock.server_close()
            except Exception:  # noqa: BLE001 - the desk is already gone
                pass
        shutil.rmtree(tmp_root, ignore_errors=True)


def _execute(args, run: RunState) -> bool:
    """Run the phases in the plan and return True when startup failed."""
    plan = run.plan
    has_sheet = any(shot.kind == "sheet" for shot in plan)
    try:
        with audit.sync_playwright() as playwright:
            if has_sheet:
                _run_sheet_phase(args, run, plan, playwright)
            _run_real_phase(args, run, plan, playwright)
    except FaceWalkError:
        raise
    except Exception as exc:  # noqa: BLE001 - startup failure is exit 2
        raise FaceWalkError(f"{type(exc).__name__}: {exc}") from exc
    return False


def main(argv: list[str] | None = None) -> int:
    """Parse the options, run the walk and print its two summary lines."""
    parser = argparse.ArgumentParser(
        description="Photograph the agent's face in every mood and surface.")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="output base directory")
    parser.add_argument("--routes", default="",
                        help="substring filter for surfaces, moods and routes")
    parser.add_argument("--themes", default=",".join(THEMES),
                        help="comma-separated themes")
    parser.add_argument("--widths", default=DEFAULT_WIDTHS,
                        help="comma-separated widths from 1280,800,420")
    parser.add_argument("--mock-delay-ms", type=int, default=DEFAULT_MOCK_DELAY_MS,
                        help="the mock model's delay (default 12000)")
    parser.add_argument("--record-api", default="",
                        help="write GET /api JSON bodies under this directory")
    parser.add_argument("--sheet-only", action="store_true",
                        help="start the review sheet and a browser, no desk")
    args = parser.parse_args(argv)
    if audit.sync_playwright is None:
        print(audit.PLAYWRIGHT_HELP)
        return 2
    try:
        plan = build_plan(args)
    except FaceWalkError as exc:
        print(f"invalid face walk options: {exc}")
        return 2
    started = time.monotonic()
    run_dir = Path(args.out) / _now_stamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run {run_dir}", flush=True)
    print(f"mock delay {args.mock_delay_ms} ms; themes {args.themes}; "
          f"widths {args.widths}", flush=True)
    run = RunState(plan, run_dir)
    startup_failed = False
    try:
        startup_failed = _execute(args, run)
    except FaceWalkError as exc:
        print(f"face walkthrough failed to start: {exc}", flush=True)
        startup_failed = True
    meta = _meta(args, run_dir, started)
    document = _manifest(run, args, meta)
    _write_json(run_dir / "manifest.json", document)
    _write_json(run_dir / "photographs.json", list(run.records.values()))
    counts = document["counts"]
    print(_metric_line(counts), flush=True)
    print(_verdict_line(counts), flush=True)
    return _exit_code(counts, startup_failed)


if __name__ == "__main__":
    sys.exit(main())
