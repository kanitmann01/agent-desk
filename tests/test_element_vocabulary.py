"""The element vocabulary has one owner on each side of the wire.

The ten kinds, their direction and tone words, and every cap used to live in
five places: the renderer, the permission lint, the server's no-JS helper,
the SPA's ElementView and the marketplace sample renderer. The host now owns
them in agentdesk.plugins.vocabulary and the SPA's copy is generated from it,
so these tests pin the importers to the same objects and prove the one
no-JS renderer draws every kind.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.plugins import html as element_html  # noqa: E402
from agentdesk.plugins import render, vocabulary  # noqa: E402
from agentdesk.server import app  # noqa: E402
from agentdesk.validator import lint  # noqa: E402

# One representative element per kind, in the contract's order. Each carries
# the piece of untrusted text the escaping assertions look for.
SAMPLES = {
    "metric": {"kind": "metric", "value": "12", "label": "<script>alert(1)</script>"},
    "text": {"kind": "text", "text": "<script>alert(1)</script>"},
    "delta": {"kind": "delta", "label": "<script>alert(1)</script>",
              "value": "<script>alert(1)</script>", "direction": "up"},
    "progress": {"kind": "progress", "value": 6, "target": 10, "unit": "<script>alert(1)</script>"},
    "list": {"kind": "list", "title": "<script>alert(1)</script>",
             "rows": [{"primary": "Rows", "secondary": "8", "meta": "ok"}]},
    "table": {"kind": "table", "columns": ["<script>alert(1)</script>", "N"],
              "rows": [["a", "1"], {"primary": "b", "secondary": "2"}]},
    "sparkline": {"kind": "sparkline", "label": "<script>alert(1)</script>",
                  "points": [1, 4, 2, 9]},
    "status": {"kind": "status", "text": "<script>alert(1)</script>", "tone": "attention"},
    "timeline": {"kind": "timeline", "title": "<script>alert(1)</script>",
                 "items": [{"time": "09:00", "title": "Sync", "meta": "done"}]},
    "checklist": {"kind": "checklist", "title": "<script>alert(1)</script>",
                  "items": [{"text": "Ship", "done": True}]},
}


def test_render_exports_the_vocabulary_object():
    assert render.ELEMENT_KINDS is vocabulary.ELEMENT_KINDS
    assert render.DIRECTIONS is vocabulary.DIRECTIONS
    assert render.TONES is vocabulary.TONES


def test_the_lint_known_kinds_are_the_vocabulary():
    assert lint.KNOWN_ELEMENT_KINDS is vocabulary.ELEMENT_KINDS


def test_the_lint_caps_are_the_vocabulary_caps():
    assert lint.ROW_CAPS is vocabulary.ROW_CAPS
    assert lint.SPARKLINE_MIN_POINTS == vocabulary.SPARKLINE_MIN_POINTS
    assert lint.SPARKLINE_MAX_POINTS == vocabulary.SPARKLINE_MAX_POINTS
    assert lint.SAMPLE_MAX_BYTES == vocabulary.SAMPLE_MAX_BYTES


def test_known_kind_accepts_only_the_ten_names():
    for kind in vocabulary.ELEMENT_KINDS:
        assert vocabulary.known_kind(kind)
    assert not vocabulary.known_kind("hologram")
    assert not vocabulary.known_kind(None)


def test_every_kind_has_a_sample():
    assert list(SAMPLES) == list(vocabulary.ELEMENT_KINDS)


def test_the_no_js_renderer_draws_every_kind():
    for kind in vocabulary.ELEMENT_KINDS:
        markup = element_html.element_html(SAMPLES[kind])
        assert markup, kind
        assert "<script>" not in markup, kind
        assert "&lt;script&gt;" in markup, kind


def test_the_no_js_renderer_draws_a_sparkline_as_inline_svg():
    markup = element_html.element_html(SAMPLES["sparkline"])
    assert "<svg" in markup
    assert "<polyline" in markup
    assert 'viewBox="0 0 100 30"' in markup


def test_a_malformed_element_draws_nothing():
    assert element_html.element_html({"kind": "hologram"}) == ""
    assert element_html.element_html({"kind": "sparkline", "points": [1]}) == ""
    assert element_html.element_html("not a dict") == ""


def test_the_dashboard_html_delegates_to_the_one_renderer():
    for kind in vocabulary.ELEMENT_KINDS:
        assert app._plugin_element_html(SAMPLES[kind]) == element_html.element_html(SAMPLES[kind])
    assert app._plugin_element_html({"kind": "hologram"}) == ""


def test_the_spa_imports_the_generated_vocabulary():
    view = (ROOT / "frontend" / "src" / "dashboard" / "PluginCardView.tsx").read_text(encoding="utf-8")
    assert "from '../plugins/vocabulary'" in view
    assert "DRAWN_KINDS" not in view
    generated = (ROOT / "frontend" / "src" / "plugins" / "vocabulary.generated.ts").read_text(encoding="utf-8")
    assert 'export const ELEMENT_KINDS = [' in generated
    for kind in vocabulary.ELEMENT_KINDS:
        assert f'  "{kind}",' in generated


def test_the_marketplace_sample_draws_through_the_dashboard_viewer():
    sample = (ROOT / "frontend" / "src" / "marketplace" / "Sample.tsx").read_text(encoding="utf-8")
    assert "import { ElementView } from '../dashboard/PluginCardView'" in sample
    assert "function Sparkline" not in sample
    assert "SampleElement" not in sample
