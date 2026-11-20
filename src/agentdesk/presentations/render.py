"""Optional slide previews. Nothing is bundled.

PowerPoint over COM on Windows, otherwise LibreOffice if it is installed.
Tests pass a runner. A missing or hung renderer leaves the .pptx in place
and says previews are unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path

RENDER_TIMEOUT_S = 60


def which_renderer() -> str:
    """The renderer on this machine, or "none"."""
    if sys.platform == "win32" and shutil.which("powershell"):
        return "powerpoint"
    if shutil.which("soffice") or shutil.which("libreoffice"):
        return "libreoffice"
    return "none"


def render_deck(pptx: Path, out_dir: Path, runner=None, timeout: float = RENDER_TIMEOUT_S) -> dict:
    """PDF and slide images next to the deck, or a named absence.

    `runner(argv, timeout) -> CompletedProcess` does the work. The default
    runner is a subprocess with a timeout. The request waits at most
    `timeout` seconds.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    name = which_renderer() if runner is None else "injected"
    if runner is None and name == "none":
        return {"renderer": "none", "pdf": "", "images": [], "note": "Previews are unavailable."}
    command = _command(name if runner is None else "libreoffice", pptx, out_dir)
    active = runner or _subprocess
    box: dict = {}

    def run() -> None:
        """The renderer, off the request thread."""
        try:
            box["result"] = active(command, timeout)
        except Exception as exc:  # noqa: BLE001 - a failed render is a status
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout + 1)
    if thread.is_alive():
        return {"renderer": "none", "pdf": "", "images": [], "note": "Previews are unavailable."}
    if "error" in box:
        return {"renderer": "none", "pdf": "", "images": [], "note": "Previews are unavailable."}
    result = box.get("result")
    if result is None or getattr(result, "returncode", 1) != 0:
        return {"renderer": "none", "pdf": "", "images": [], "note": "Previews are unavailable."}
    pdfs = sorted(out_dir.glob("*.pdf"))
    images = sorted(str(path.relative_to(out_dir.parent)) for path in out_dir.glob("*.png"))
    # Images are stored as paths relative to the presentation directory's child.
    pdf = str(pdfs[0].relative_to(out_dir.parent)) if pdfs else ""
    used = name if runner is None else getattr(result, "renderer", "libreoffice")
    return {"renderer": used, "pdf": pdf, "images": images, "note": ""}


def _subprocess(argv: list[str], timeout: float):
    """One renderer process. The timeout is the process's own."""
    return subprocess.run(argv, timeout=timeout, check=False, capture_output=True)


def _command(kind: str, pptx: Path, out_dir: Path) -> list[str]:
    """The argv for PowerPoint COM or LibreOffice. Neither is bundled."""
    if kind == "powerpoint":
        # Same posture as tools/export-outlook.ps1: COM, no bundled Office.
        script = (
            "$ppt = New-Object -ComObject PowerPoint.Application; "
            f"$deck = $ppt.Presentations.Open('{pptx}'); "
            f"$deck.SaveAs('{out_dir / (pptx.stem + '.pdf')}', 32); "
            "$deck.Close(); $ppt.Quit()"
        )
        return ["powershell", "-NoProfile", "-Command", script]
    binary = shutil.which("soffice") or shutil.which("libreoffice") or "soffice"
    return [binary, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx)]
