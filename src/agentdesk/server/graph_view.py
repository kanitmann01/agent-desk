"""The memory graph page (ticket #96): the snapshot as static SVG.

The donor's dev-only graph server becomes one server-rendered page in
the memory pages' style: no client framework, no animation, no script
of its own. The snapshot (memory/graph) is the whole input; this module
only draws it. Layout is a deterministic grid keyed by the snapshot's
order (newest first), entities connect their facts through their edges,
older nodes shade down by recency, every dynamic string is escaped and
the labels arrive already truncated. An empty bank renders the empty
state; a locked store never reaches this module (the route renders the
memory page's banner instead, like the sweep's dry run does).

The page's query vocabulary lives here too: since and until accept
YYYY-MM-DD dates (UTC; the since date starts at its midnight, the until
date includes its whole day, so the exclusive bound lands at the next
midnight), limit clamps into 1..1000, and anything unparsable reads as
absent. A graph page must render, never error on its query string.
"""

import html
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from agentdesk.memory.graph import (
    DEFAULT_GRAPH_LIMIT,
    MAX_GRAPH_LIMIT,
    GraphSnapshot,
)
from agentdesk.server.pages import page_shell

UTC = timezone.utc  # datetime.UTC needs 3.11; the declared floor is 3.10

DAY_SECONDS = 86_400.0

# The grid: five nodes a row, enough cell width for an eighty-character
# label at nine pixels, cells in the snapshot's newest-first order.
COLUMNS = 5
CELL_WIDTH = 430.0
CELL_HEIGHT = 96.0
MARGIN = 24.0
NODE_RADIUS = 10.0

# Presentation attributes per edge type (the CSP governs style
# attributes, but SVG painting attributes keep the markup static).
# Colour comes from the theme through the graph-edge classes in the
# shared stylesheet (pages.STYLES); only width and dash ride here.
_EDGE_STYLE = {
    "entity": {"width": "1.5", "dash": None},
    "temporal": {"width": "1.3", "dash": "5 4"},
    "derived": {"width": "1.3", "dash": None},
    "semantic": {"width": "1.1", "dash": "1.5 3.5"},
}

_LEGEND = (
    ("entity", "Entity", "facts that share an entity"),
    ("temporal", "Temporal", "events within seven days of each other"),
    ("derived", "Citation", "an observation pointing at the facts it cites"),
    ("semantic", "Semantic", "vectors within a 0.72 cosine of each other"),
)


def _count(value: int, noun: str) -> str:
    """One counted noun, singular handled honestly."""
    return f"{value} {noun}" + ("" if value == 1 else "s")


def _parse_bound(value: str, extra_days: int) -> float | None:
    """One YYYY-MM-DD date as an epoch bound: the day starts at its
    UTC midnight, plus the caller's day shift (the until date includes
    its whole day). Anything unparsable is no bound at all."""
    try:
        moment = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return (moment.replace(tzinfo=UTC) + timedelta(days=extra_days)).timestamp()


def parse_graph_query(query: str) -> tuple[float | None, float | None, int]:
    """The page's since, until and limit out of one query string. The
    limit clamps into 1..1000 around the default of two hundred; unparsable
    values fall back to the default (the limit) or to no bound (the
    dates), so the page always renders."""
    params = parse_qs(query)
    limit = DEFAULT_GRAPH_LIMIT
    raw = params.get("limit", [""])[0]
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = DEFAULT_GRAPH_LIMIT
    limit = min(max(limit, 1), MAX_GRAPH_LIMIT)
    since = _parse_bound(params.get("since", [""])[0], extra_days=0)
    until = _parse_bound(params.get("until", [""])[0], extra_days=1)
    return since, until, limit


def _show_date(epoch: float) -> str:
    """The UTC calendar date of an epoch timestamp, as YYYY-MM-DD.

    UTC on purpose: the page's since and until bounds are read as UTC days, so the date
    a node shows matches the day that admitted it.
    """
    return datetime.fromtimestamp(epoch, tz=UTC).date().isoformat()


def _node_id(node_id) -> str:
    """The safe DOM id for a node: the snapshot's qualified id with the
    separator flattened, XML-safe and stable."""
    return html.escape(str(node_id), quote=True).replace(":", "-")


def _position(index: int) -> tuple[float, float]:
    """The centre of the grid slot at this index, in SVG user units.

    Slots fill COLUMNS columns left to right and then rows top to bottom, following the
    snapshot's newest-first order.
    """
    column = index % COLUMNS
    row = index // COLUMNS
    return (
        MARGIN + column * CELL_WIDTH + CELL_WIDTH / 2,
        MARGIN + row * CELL_HEIGHT + 34.0,
    )


def _shifted(point, toward, distance: float):
    """One point moved toward the other, so an edge line ends at the
    node's rim instead of under the circle."""
    dx = toward[0] - point[0]
    dy = toward[1] - point[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return point
    return (point[0] + dx / length * distance, point[1] + dy / length * distance)


def _edge_lines(snapshot: GraphSnapshot, positions: dict) -> str:
    """The SVG lines for every edge whose endpoints both have a position.

    Each line is pulled back to the node rim by NODE_RADIUS + 2 so it does not vanish
    under the circle. Width and dash come from _EDGE_STYLE, an unknown edge type falls
    back to the entity style, and only derived edges carry the arrowhead.
    """
    lines = []
    for edge in snapshot.edges:
        start = positions.get(edge.source)
        end = positions.get(edge.target)
        if start is None or end is None:
            continue
        style = _EDGE_STYLE.get(edge.type) or _EDGE_STYLE["entity"]
        x1, y1 = _shifted(start, end, NODE_RADIUS + 2.0)
        x2, y2 = _shifted(end, start, NODE_RADIUS + 2.0)
        dash = (
            f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
        )
        marker = (
            ' marker-end="url(#graph-arrow)"' if edge.type == "derived" else ""
        )
        lines.append(
            f'<line class="graph-edge edge-{edge.type}"'
            f' x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"'
            f' stroke-width="{style["width"]}"'
            f"{dash}{marker}></line>"
        )
    return "".join(lines)


def _node_groups(snapshot: GraphSnapshot, positions: dict) -> str:
    """The SVG group for every node: a circle, its label and a title tooltip.

    Opacity runs from 0.25 to 1.0 with the node's recency, whose half-life is thirty
    days. The tooltip repeats the label, its UTC date and its citation count, and a
    derived node uses the observation class.
    """
    groups = []
    for node in snapshot.nodes:
        x, y = positions[node.id]
        kind = "observation" if node.derived else "fact"
        # Recency shading: a brand-new node paints full strength, the
        # thirty-day half-life fades the circle toward a quarter.
        opacity = 0.25 + 0.75 * max(0.0, min(1.0, node.recency))
        label = html.escape(node.label)
        when = _show_date(node.instant)
        citations = _count(node.source_fact_count, "citation")
        tooltip = html.escape(
            f"{node.label} ({when}, {citations})"
        )
        groups.append(
            f'<g class="graph-node" id="graph-node-{_node_id(node.id)}">'
            f"<title>{tooltip}</title>"
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{NODE_RADIUS:.0f}"'
            f' class="graph-dot graph-dot-{kind}" fill-opacity="{opacity:.3f}"></circle>'
            f'<text x="{x:.1f}" y="{y + 26:.1f}" font-size="9"'
            f' text-anchor="middle" class="graph-text">{label}</text>'
            "</g>"
        )
    return "".join(groups)


def _legend() -> str:
    """The edge-type legend: one sample line per type, with its written contract.

    Every sample reuses the same style attributes as the drawn edges, so a legend line
    and a graph line cannot disagree.
    """
    rows = []
    for edge_type, title, description in _LEGEND:
        style = _EDGE_STYLE[edge_type]
        dash = (
            f' stroke-dasharray="{style["dash"]}"' if style["dash"] else ""
        )
        marker = (
            ' marker-end="url(#graph-arrow)"' if edge_type == "derived" else ""
        )
        rows.append(
            f'<li id="graph-legend-{edge_type}" style="display:flex;'
            'align-items:center;gap:6px;list-style:none">'
            f'<svg width="26" height="10" aria-hidden="true"><line'
            f' class="graph-edge edge-{edge_type}" x1="1" y1="5" x2="19" y2="5"'
            f' stroke-width="{style["width"]}"{dash}{marker}></line></svg>'
            f"<span><b>{title}</b> {html.escape(description)}</span></li>"
        )
    return (
        '<ul id="graph-legend" style="display:flex;flex-wrap:wrap;gap:14px;'
        f'padding:6px 0;margin:8px 0">{"".join(rows)}</ul>'
    )


def _island(fallback: str, query: str) -> str:
    """The interactive graph's mount point around the static fallback,
    with the island's stylesheet and module script."""
    endpoint = "/api/memory/graph" + (f"?{query}" if query else "")
    return (
        "<h1>Memory graph</h1>\n"
        f'<section id="memory-graph-root" data-endpoint="{html.escape(endpoint, quote=True)}"'
        f' data-mode="full" aria-label="Memory graph">\n{fallback}\n</section>\n'
        '<link rel="stylesheet" href="/static/spa/assets/memory-graph.css">\n'
        '<script type="module" src="/static/spa/assets/memory-graph.js"></script>\n'
    )


def render_graph_page(
    snapshot: GraphSnapshot,
    version: str,
    since: float | None = None,
    until: float | None = None,
    inbox_count: int = 0,
    island_query: str | None = None,
) -> str:
    """The full memory graph document: the counts header, the optional
    window line, the edge legend and the snapshot's static SVG, or the
    empty state when the bank has nothing in the window."""
    facts = sum(1 for node in snapshot.nodes if not node.derived)
    observations = len(snapshot.nodes) - facts
    counts = (
        f'<p class="mono" id="graph-counts">{_count(facts, "fact")}, '
        f"{_count(observations, 'observation')}, "
        f"{_count(len(snapshot.edges), 'edge')} shown</p>"
    )
    window = ""
    if since is not None or until is not None:
        if since is not None and until is not None:
            span = f"{_show_date(since)} to {_show_date(until - 1.0)}"
        elif since is not None:
            span = f"from {_show_date(since)}"
        else:
            span = f"through {_show_date(until - 1.0)}"
        window = (
            f'<p class="empty mono" id="graph-window">Window {span}'
            " (dates are UTC; the until day includes its whole day).</p>"
        )

    if not snapshot.nodes:
        content = f"""<h1>Memory graph</h1>
{counts}{window}<p class="empty" id="graph-empty">No memory to graph
yet: save a fact on the <a href="/memory">memory page</a> and it will
appear here with its entity, temporal, citation and semantic
links.</p>
"""
        if island_query is not None:
            content = _island(content.replace("<h1>Memory graph</h1>\n", ""), island_query)
        return page_shell(
            "Memory graph", "/memory", content, version, inbox_count=inbox_count
        )

    positions = {
        node.id: _position(index) for index, node in enumerate(snapshot.nodes)
    }
    height = MARGIN * 2 + CELL_HEIGHT * ((len(snapshot.nodes) + COLUMNS - 1) // COLUMNS)
    width = MARGIN * 2 + CELL_WIDTH * COLUMNS
    aria = (
        f"Memory graph with {_count(len(snapshot.nodes), 'node')} and "
        f"{_count(len(snapshot.edges), 'edge')}"
    )
    svg = (
        f'<svg id="memory-graph" width="{width:.0f}" height="{height:.0f}"'
        f' viewBox="0 0 {width:.0f} {height:.0f}" role="img"'
        f' aria-label="{html.escape(aria)}">'
        '<defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5"'
        ' markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path class="graph-arrow" d="M 0 1 L 9 5 L 0 9 z"></path></marker></defs>'
        f"{_edge_lines(snapshot, positions)}{_node_groups(snapshot, positions)}"
        "</svg>"
    )
    scrolled = (
        f'<div class="graph-static">{svg}</div>'
    )
    if island_query is not None:
        # The interactive graph mounts over the static picture, which
        # stays as the no-JavaScript fallback inside the mount point.
        content = _island(f"{counts}{window}{_legend()}{scrolled}", island_query)
        return page_shell(
            "Memory graph", "/memory", content, version, inbox_count=inbox_count
        )
    content = f"""<h1>Memory graph</h1>
<p>The bank as one static picture: newest first, each node's shading
fading with the same thirty-day half-life recall uses. Derived
observations point at the facts they cite; facts join the entities they
mention, their neighbours in time, and (when embeddings exist) their
closest vectors.</p>
{counts}{window}{_legend()}{scrolled}
"""
    return page_shell(
        "Memory graph", "/memory", content, version, inbox_count=inbox_count
    )
