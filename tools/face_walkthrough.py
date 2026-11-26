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
SHEET_HOST = "127.0.0.1"
SHEET_PORT = 5199
SHEET_URL = f"http://{SHEET_HOST}:{SHEET_PORT}/face-sheet.html"
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
    paths = re.findall(r"'([^']+)'", match.group(1))
    if not paths:
        raise FaceWalkError("vite.config.ts backendPaths is empty")
    return tuple(dict.fromkeys(paths))


def _is_proxied_path(path: str, proxied: tuple[str, ...]) -> bool:
    """True when the path is one the dev server forwards to a backend.

    The denylist is the operative rule: it is checked before the sheet's
    allowlist, so even an asset-looking proxied path never leaves the dev
    server's own origin.
    """
    for prefix in proxied:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _is_sheet_asset(path: str) -> bool:
    """True for the sheet's own document, module, stylesheet, font or favicon."""
    if path in ("/face-sheet.html", "/face-sheet",
                "/static/spa/face-sheet.html"):
        return True
    if path in ("/@vite/client", "/@react-refresh"):
        return True
    for prefix in ("/src/", "/node_modules/", "/@vite/", "/@react-refresh",
                   "/@id/", "/@fs/"):
        if path.startswith(prefix):
            return True
    if path.endswith((".js", ".mjs", ".css", ".woff", ".woff2", ".ttf",
                      ".otf", ".eot")):
        return True
    return "favicon" in path and path.endswith((".svg", ".ico", ".png"))


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
               f"http://localhost:{SHEET_PORT}"}
    target.route("**/*", lambda route: _sheet_deny_handler(
        route, origins, paths))
    return paths


def _install_real_guard(target, started: list[dict], held: list) -> None:
    """Install the layout audit's guard before the real app's first navigation.

    The guard records every non-GET and lets the isolated desk answer it:
    the research action must reach the mock, and the two requests the walk
    answers or holds are intercepted by the walk's own later routes.
    """
    audit._install_request_guard(target, started, held, answered=True)


def _research_handler(route, config: RouteConfig) -> None:
    """Answer the research request with a 500 for the blocked mood, or pass."""
    if urllib.parse.urlsplit(route.request.url).path != "/research":
        route.fallback()
        return
    if config.research == "fail":
        route.fulfill(
            status=500, content_type="application/json",
            body=json.dumps({"error": RESEARCH_REFUSAL}))
        return
    route.fallback()


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
    """One collapsed-rail photograph per theme at the desk width."""
    if DESKTOP_WIDTH not in widths:
        return []
    return [Shot(
        id=f"rail-collapsed|{theme}|collapsed",
        surface="rail-collapsed", kind="rail-collapsed", theme=theme,
        mood="idle", motion="normal", condition="full",
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
        self.surfaces[name] = {
            "name": name,
            "face": bool(face),
            "observed": bool(observed),
            "detail": detail,
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


def _shoot_clip(page, locator, path: Path, pad: int = 8) -> str:
    """One padded crop around a locator, or a full page when the box is gone."""
    path.parent.mkdir(parents=True, exist_ok=True)
    box = locator.bounding_box()
    if box is None:
        page.screenshot(path=str(path), full_page=True, timeout=20000)
        return str(path)
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
    return str(path)


def _shoot_shot(page, shot: Shot, run_dir: Path) -> str:
    """Take one planned photograph and return its absolute path.

    A face crop is a padded clip around the face element; a sheet tile is an
    element screenshot of the tile; every other shot is the full page. A
    missing element falls back to the full page so a failed check still has
    its photograph.
    """
    path = run_dir / shot.file
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if shot.locator_kind == "rail-face":
            locator = page.locator(RAIL_FACE).first
            if locator.count() == 0:
                page.screenshot(path=str(path), full_page=True, timeout=20000)
                return str(path)
            return _shoot_clip(page, locator, path)
        if shot.locator_kind == "sheet-tile":
            locator = _sheet_tile(page, shot.mood)
            if locator.count() == 0:
                page.screenshot(path=str(path), full_page=True, timeout=20000)
                return str(path)
            locator.screenshot(path=str(path), timeout=20000)
            return str(path)
    except Exception:  # noqa: BLE001 - a photograph failure is still recorded
        page.screenshot(path=str(path), full_page=True, timeout=20000)
        return str(path)
    page.screenshot(path=str(path), full_page=True, timeout=20000)
    return str(path)


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
        error = ""
        try:
            file = (shoot or _shoot_shot)(page, shot, run.run_dir)
        except Exception as exc:  # noqa: BLE001 - record and keep going
            error = f"{type(exc).__name__}: {exc}"[:300]
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
                        else "failed"),
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


def _run_sheet_phase(args, run: RunState, plan: list[Shot],
                     playwright) -> None:
    """Start the dev server and photograph the review sheet; stage 2 fills this."""
    shots = [shot for shot in plan if shot.kind == "sheet"]
    if not shots:
        return
    run.notes.append("sheet capture phase is not implemented yet")


def _run_real_phase(args, run: RunState, plan: list[Shot],
                    playwright) -> None:
    """Boot the isolated desk and photograph the real app; stage 3 fills this."""
    shots = [shot for shot in plan if shot.kind in REAL_KINDS]
    if not shots:
        return
    tmp_root = Path(tempfile.mkdtemp(prefix="agentdesk-face-"))
    mock = None
    desk = None
    browser = None
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
        _install_real_routes(context, RouteConfig(), run.held)
        page = context.new_page()
        page.clock.install(time=FIXED_TIME)
        page.clock.set_fixed_time(FIXED_TIME)
        page.goto(desk["base"] + "/auth/" + desk["token"],
                  wait_until="domcontentloaded", timeout=30000)
        if page.url.rstrip("/") != desk["base"].rstrip("/"):
            raise FaceWalkError(f"auth landed on {page.url}, not the dashboard")
        _save_mock_connection(context, desk["base"], mock_port)
        run.notes.append("mock connection saved")
        run.notes.append("real-app capture phase is not implemented yet")
        context.close()
    finally:
        _abort_held(run.held)
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
