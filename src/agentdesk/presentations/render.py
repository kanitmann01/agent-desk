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
    """The renderer on this machine, or "none".

    PowerPoint is chosen only when its COM registration is present.
    A machine with PowerShell but no Office stays on LibreOffice, or none.
    """
    if _powerpoint_available():
        return "powerpoint"
    if shutil.which("soffice") or shutil.which("libreoffice"):
        return "libreoffice"
    return "none"


def _powerpoint_available() -> bool:
    """Whether PowerPoint's COM class is registered. Windows only."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PowerPoint.Application")
    except OSError:
        return False
    return True


def render_deck(pptx: Path, out_dir: Path, runner=None, timeout: float = RENDER_TIMEOUT_S) -> dict:
    """PDF and slide images next to the deck, or a named absence.

    `runner(argv, timeout) -> CompletedProcess` does the work. The default
    runner is a subprocess with a timeout. The request waits at most
    `timeout` seconds.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        return _render_deck(pptx, out_dir, runner, timeout)
    finally:
        shutil.rmtree(out_dir / "lo-profile", ignore_errors=True)


def _render_deck(pptx: Path, out_dir: Path, runner, timeout: float) -> dict:
    """The render itself. The caller removes the LibreOffice profile."""
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
    if pdfs and not list(out_dir.glob("*.png")):
        _rasterize(pdfs[0], out_dir)
    # posix form: the download route matches parts as URL paths ("/"-separated)
    images = sorted(path.relative_to(out_dir.parent).as_posix() for path in out_dir.glob("*.png"))
    pdf = str(pdfs[0].relative_to(out_dir.parent)) if pdfs else ""
    used = name if runner is None else getattr(result, "renderer", "libreoffice")
    note = "" if pdf or images else "Previews are unavailable."
    return {"renderer": used, "pdf": pdf, "images": images, "note": note}


def _subprocess(argv: list[str], timeout: float):
    """One renderer process. The timeout is the process's own."""
    return subprocess.run(argv, timeout=timeout, check=False, capture_output=True)


def _command(kind: str, pptx: Path, out_dir: Path) -> list[str]:
    """The argv for PowerPoint COM or LibreOffice. Neither is bundled.

    LibreOffice gets its own user profile for this run, so two renders
    do not share a lock. PowerPoint paths escape single quotes.
    """
    if kind == "powerpoint":
        deck = _ps_quote(pptx)
        pdf = _ps_quote(out_dir / (pptx.stem + ".pdf"))
        script = (
            "$ppt = New-Object -ComObject PowerPoint.Application; "
            f"$deck = $ppt.Presentations.Open('{deck}'); "
            f"$deck.SaveAs('{pdf}', 32); "
            "$deck.Close(); $ppt.Quit()"
        )
        return ["powershell", "-NoProfile", "-Command", script]
    binary = shutil.which("soffice") or shutil.which("libreoffice") or "soffice"
    profile = (out_dir / "lo-profile").resolve().as_uri()
    return [
        binary, f"-env:UserInstallation={profile}", "--headless",
        "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx),
    ]


def _ps_quote(path: Path) -> str:
    """A PowerShell single-quoted path. An embedded quote is doubled."""
    return str(path).replace("'", "''")


def _rasterize(pdf: Path, out_dir: Path) -> None:
    """Write one PNG per page when pdftoppm is installed.

    LibreOffice's PDF conversion does not emit slide images. pdftoppm
    is used only when it is already on the machine.
    """
    binary = shutil.which("pdftoppm")
    if binary is None:
        return
    subprocess.run(
        [binary, "-png", str(pdf), str(out_dir / "slide")],
        timeout=RENDER_TIMEOUT_S, check=False, capture_output=True,
    )
