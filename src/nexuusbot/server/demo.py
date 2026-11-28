"""The shared widget type for dashboard cards.

pages.py renders it; sales.py, commitments.py, research.py and
inbox_view.py build it. Every renderer states the real state of its
source; nothing here (or anywhere in the shell) fabricates values, so
there is no sample data to label anymore.
"""

from dataclasses import dataclass

from nexuusbot.server.core import Freshness


@dataclass(frozen=True)
class Widget:
    """One dashboard card: identity, size, freshness contract, content.

    body_html and foot_html are authored HTML built by this package and
    sales.py, which escape every dynamic value themselves; the shell
    renders them as-is. Titles and badges are escaped by the shell.
    """

    id: str
    title: str
    col: str  # grid size class, e.g. "col-7"; sizes vary by role on purpose
    freshness: Freshness
    body_html: str
    foot_html: str
    extra_classes: str = ""
    badge: str = ""
