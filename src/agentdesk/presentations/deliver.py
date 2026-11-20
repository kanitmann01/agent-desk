"""The one way a presentation becomes a file.

Fit, then write, then render. A research resume uses this same function,
so a deck that paused for sources still gets the fit check and the preview.
"""

from __future__ import annotations

from pathlib import Path

from agentdesk.presentations.fit import fit_outline
from agentdesk.presentations.render import render_deck
from agentdesk.presentations.writer import write_deck


def deliver_deck(shell: bytes, recipe: dict, outline: dict, sources: list,
                 folder: Path, shorten, timeout: float, runner=None) -> dict:
    """Fit the outline, write the package, and render previews into `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    fitted, notes = fit_outline(outline, recipe, shorten, timeout, sources)
    blob = write_deck(shell, recipe, fitted)
    (folder / "deck.pptx").write_bytes(blob)
    rendered = render_deck(folder / "deck.pptx", folder / "preview", runner=runner)
    return {"fit": notes, "rendered": rendered, "blob": blob}
