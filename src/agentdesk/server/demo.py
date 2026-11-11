"""Demo widgets for the walking skeleton.

Every value here is sample data, labeled as such twice: in the freshness
stamp on the card and in the footer line. When a real source connects
(the excel, calendar and research tickets) the same widget records render
live reads; nothing else about the shell changes.
"""

from dataclasses import dataclass

from agentdesk.server.core import ATTENTION, SAMPLE, Freshness

# SVG stroke color for up-deltas, from the design token --primary.
_GREEN = "#14594E"


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


_ARROW_UP = (
    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8"/></svg>'
)
_ARROW_DOWN = (
    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M7 7l10 10M17 9v8H9"/></svg>'
)

_CHECK_ON = (
    '<span class="box" aria-hidden="true"><svg width="11" height="11" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span>'
)

_SPARK = (
    f'<figure class="spark"><svg width="180" height="52" viewBox="0 0 180 52" '
    f'aria-label="14 day trend, rising, sample data">'
    f'<path d="M4 40 L17 36 L30 38 L43 30 L56 33 L69 27 L82 29 L95 22 L108 25 '
    f'L121 19 L134 21 L147 14 L160 16 L173 9" fill="none" stroke="{_GREEN}" '
    f'stroke-width="2" stroke-linecap="round"/>'
    f'<circle cx="173" cy="9" r="3" fill="{_GREEN}"/></svg>'
    f"<figcaption>14-day trend</figcaption></figure>"
)


def _rows() -> str:
    return (
        '<table class="rows"><thead><tr><th scope="col">Product line</th>'
        '<th scope="col" class="num">24 h</th>'
        '<th scope="col" class="num">Trend</th></tr></thead><tbody>'
        f'<tr><td>Atlas ERP modules</td><td class="num">+&euro;6,410</td>'
        f'<td class="num"><span class="delta up">{_ARROW_UP}+4.2%</span></td></tr>'
        f'<tr><td>Field services</td><td class="num neg">-&euro;2,150</td>'
        f'<td class="num"><span class="delta down">{_ARROW_DOWN}-2.8%</span></td></tr>'
        f'<tr><td>Care plans</td><td class="num">+&euro;1,890</td>'
        f'<td class="num"><span class="delta up">{_ARROW_UP}+1.6%</span></td></tr>'
        "</tbody></table>"
    )


def _checks() -> str:
    done = f'<div class="check" role="checkbox" aria-checked="true" aria-disabled="true">{_CHECK_ON}<span>Replay Meridian\'s objections from Monday\'s thread</span></div>'
    todo1 = f'<div class="check" role="checkbox" aria-checked="false" aria-disabled="true">{_CHECK_ON}<span>Pull the regional numbers Marco asked for</span></div>'
    todo2 = f'<div class="check" role="checkbox" aria-checked="false" aria-disabled="true">{_CHECK_ON}<span>Confirm the slide 12 spend figure with Finance</span></div>'
    return done + todo1 + todo2


def demo_widgets() -> list[Widget]:
    """The four sample cards, sized by role, not as a uniform mosaic."""
    return [
        Widget(
            id="sales-24h",
            title="Sales, last 24 hours",
            col="col-7",
            freshness=Freshness(SAMPLE, "Sample data", "2026-11-10T18:00:00"),
            body_html=(
                '<div class="kpi"><div><div class="label">Net change</div>'
                '<div class="value">+&nbsp;&euro;14,320</div>'
                '<div class="sub">+1.1% vs yesterday, &euro;1.32M total</div></div>'
                f"{_SPARK}</div>{_rows()}"
            ),
            foot_html=(
                '<button class="btn btn-secondary btn-start" data-pick>Connect a workbook</button>'
                "<span>Sample data until a workbook is connected.</span>"
            ),
        ),
        Widget(
            id="key-commitment",
            title="Today's key commitment",
            col="col-5",
            freshness=Freshness(SAMPLE, "Sample data", "2026-11-11T09:02:00"),
            body_html=(
                '<div class="event"><span class="when">14:00<br>15:00</span>'
                "<div><b>Q4 pipeline review</b><small>6 attendees, room Beaufort</small></div></div>"
                '<div><div class="subhead subhead-tight">Agent\'s breakdown</div>'
                f"{_checks()}</div>"
                '<span class="follow">Send the updated deck to Marco by 13:00</span>'
            ),
            foot_html="Demo widget. The calendar bridge connects in a later build.",
        ),
        Widget(
            id="research",
            title="Research",
            col="col-8",
            freshness=Freshness(SAMPLE, "Sample data", "2026-11-11T09:12:00"),
            body_html=(
                '<div class="well"><p class="q">Ask anything, or paste what you did '
                "and ask what to look for.</p>"
                '<button class="btn btn-secondary" disabled '
                'title="Research connects to the company endpoint in a later build">'
                "Research</button></div>"
                '<div class="answer"><div class="aq">What changed in the EU channel '
                'since the pricing update? <span class="tag-sample">sample</span></div>'
                "List prices took effect 4 November and five of nine EU partners have "
                "already reflected them in quotes. Two held to old prices on multi-year "
                "terms; Meridian is the only one that pushed back in writing."
                '<div><span class="src">eu-price-memo.pdf</span>'
                '<span class="src">channel-weekly.xlsx, tab EU</span></div></div>'
            ),
            foot_html="Demo widget. The company endpoint connects in a later build.",
        ),
        Widget(
            id="region-mix",
            title="Region mix",
            col="col-4",
            freshness=Freshness(ATTENTION, "Yesterday, 17:40", "2026-11-10T17:40:00"),
            badge="Pilot",
            extra_classes="amber",
            body_html=(
                '<div class="alert" id="amber-body">'
                '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
                'stroke-linejoin="round" aria-hidden="true"><path d="M12 4 21 19H3L12 4z"/>'
                '<path d="M12 10v4M12 17h.01"/></svg>'
                "<span>Can't refresh: Q4-sales.xlsx is open in Excel right now. "
                "Changes will appear once the file is free.</span></div>"
                '<button class="btn btn-secondary btn-start" id="retest">'
                "Re-test now</button>"
            ),
            foot_html="Demo widget. Amber state shown as designed.",
        ),
    ]
