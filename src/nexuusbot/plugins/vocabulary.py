"""The one element vocabulary the Python host and the SPA share.

Every element kind a plugin card may draw is named here once, together with
the direction and tone words a kind may carry and the caps the validator and
the renderer enforce. The SPA's copy is generated from this module by
scripts/export_plugin_vocabulary.py, so a kind either reaches both surfaces
or neither.
"""

from __future__ import annotations

METRIC = "metric"
TEXT = "text"
DELTA = "delta"
PROGRESS = "progress"
LIST = "list"
TABLE = "table"
SPARKLINE = "sparkline"
STATUS = "status"
TIMELINE = "timeline"
CHECKLIST = "checklist"

# The ten element kinds, in the order the contract lists them.
ELEMENT_KINDS: tuple[str, ...] = (
    METRIC,
    TEXT,
    DELTA,
    PROGRESS,
    LIST,
    TABLE,
    SPARKLINE,
    STATUS,
    TIMELINE,
    CHECKLIST,
)

# The direction a delta may point, and the tone a colour-carrying kind may
# take. Both are closed vocabularies: an unknown word normalises to the
# calm member rather than travelling to a surface.
DIRECTIONS: tuple[str, ...] = ("up", "down", "flat")
TONES: tuple[str, ...] = ("ok", "attention", "alarm")

# Element-specific caps from the plugin marketplace design: rows a list or
# table may show, and the sparkline's point window.
ROW_CAPS: dict[str, int] = {LIST: 8, TABLE: 20}
SPARKLINE_MIN_POINTS = 12
SPARKLINE_MAX_POINTS = 30

# The byte cap a bundled sample file may weigh.
SAMPLE_MAX_BYTES = 32768


def known_kind(kind: object) -> bool:
    """Say whether a value names one of the element kinds this build draws."""
    return isinstance(kind, str) and kind in ELEMENT_KINDS
