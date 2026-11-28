"""Coupled intelligence: what the desk already knows about this person,
said out loud on the cards they already read.

The package is deliberately separate from the plugins. A plugin declares
what it can fetch; this package decides what the fetch means for this
particular person, under one seam (the dashboard payload) and with one
refusal story (a family that fails leaves the card exactly as it was).
"""

from nexuusbot.insight.context import build_context
from nexuusbot.insight.preferences import (
    PreferenceStore,
    PreferencesError,
    changed,
    defaults,
    prompt_lines,
)
from nexuusbot.insight.service import FAMILIES, attach_cards
from nexuusbot.insight.types import InsightContext, InsightError, InsightReading

__all__ = [
    "FAMILIES",
    "InsightContext",
    "InsightError",
    "InsightReading",
    "PreferenceStore",
    "PreferencesError",
    "attach_cards",
    "build_context",
    "changed",
    "defaults",
    "prompt_lines",
]
