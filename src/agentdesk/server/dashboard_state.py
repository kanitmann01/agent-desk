"""One dashboard state for both dashboard surfaces.

GET /api/dashboard and the server-rendered fallback page used to decide the
same settings, source and research state twice, and the two decisions had
drifted apart. This module performs every read once and exposes the result as
:class:`DashboardState`: :meth:`DashboardState.payload` is the JSON contract,
and the renderer maps the same fields onto widgets. A read this builder makes
is therefore never made again by either surface.

Keep the reads here, not in the surfaces. The builder is the one place where
"what does the dashboard currently know" is answered.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import agentdesk
from agentdesk.assistant import audit as audit_store
from agentdesk.calendar.watcher import STATE_EMPTY
from agentdesk.layout import resolved_layout
from agentdesk.plugins.cards import card_to_api
from agentdesk.server import demo_data
from agentdesk.server.core import SOURCE_IDS, SRC_RESEARCH, STATUS_CONNECTED, SourceStatus

# The three steps between a fresh desk and the morning loop, in the order
# a person takes them: id, title, reason, the page a link opens, and the
# form a one-click button posts to (None when the step is only a link).
AI_SETTINGS = "/settings#ai"
WORKBOOK_PICK = "/sources/excel-watch/pick"
CALENDAR_WALKTHROUGH = "/walkthrough/calendar"
SETUP_STEPS = (
    ("ai", "Add your AI key",
     "The assistant, your calendar breakdowns and memory all use it.",
     AI_SETTINGS, None),
    ("workbook", "Open your sales workbook",
     "Your pipeline figure and the moves come from it.",
     "/settings#tools", WORKBOOK_PICK),
    ("calendar", "Connect your calendar",
     "Today's commitment and your digest come from it.",
     CALENDAR_WALKTHROUGH, None),
)


def setup_payload(ai_connected: bool, sample: bool, excel, calendar) -> dict:
    """The Get started strip's data: three steps, each done or not.

    A step is done only by something real. The labelled sample set keeps
    every tile alive while nothing is connected, so a workbook or calendar
    inside the sample folder leaves its step open: the desk must never look
    finished while it is still showing sample data.

    `sampleOffer` says whether the strip offers "Try it with sample data":
    true until a real workbook or calendar is connected. A saved AI is not
    a source, so a person who adds the key first keeps the offer.
    """
    workbook = getattr(excel, "registered_path", None)
    workbook_done = bool(workbook) and not demo_data.under_sample_folder(workbook, None)
    status = calendar.status() if calendar is not None else {}
    calendar_path = status.get("path")
    calendar_done = (
        status.get("state") not in (None, STATE_EMPTY)
        and not (calendar_path and demo_data.under_sample_folder(calendar_path, None))
    )
    done = {"ai": bool(ai_connected), "workbook": workbook_done, "calendar": calendar_done}
    return {
        "steps": [
            {"id": step_id, "title": title, "reason": reason,
             "href": href, "action": action, "done": done[step_id]}
            for step_id, title, reason, href, action in SETUP_STEPS
        ],
        "sample": bool(sample),
        "sampleOffer": not (workbook_done or calendar_done),
    }


@dataclass(frozen=True)
class SourceState:
    """One source's resolved dashboard state.

    `mode` is the dashboard vocabulary: "disabled" when the settings toggle is
    off, "unavailable"/"unconfigured" when nothing can be read yet, and "live"
    when a status is being served. `status` is the source's own status dict, or
    None when there is none to report.
    """

    mode: str
    status: dict | None

    @property
    def enabled(self) -> bool:
        """True when the source is turned on in settings."""
        return self.mode != "disabled"


@dataclass(frozen=True)
class ResearchState:
    """Research availability and the last answered question.

    `last_answered_ts` is a POSIX timestamp, or None when the audit log has no
    successful research call.
    """

    enabled: bool
    last_answered_ts: float | None


@dataclass(frozen=True)
class DashboardState:
    """Every decision both dashboard surfaces need, read once.

    `now` is the clock the renderer stamps widgets with; the payload ignores
    it. Plugin cards already carry their insight attachment, so a surface that
    renders them must not call `with_insight` again.
    """

    version: str
    sample: bool
    desk_network: bool
    flags: dict[str, bool]
    sales: SourceState
    commitments: SourceState
    research: ResearchState
    sources: tuple[SourceStatus, ...]
    sources_connected: int
    inbox_waiting: int
    skills: tuple[dict, ...]
    plugin_cards: tuple[dict, ...]
    layout_entries: tuple[dict, ...]
    custom_titles: dict[str, str]
    desk_check: dict
    agent_loop: dict
    recommendations: tuple[dict, ...]
    update: dict
    setup: dict
    now: dt.datetime

    def payload(self) -> dict:
        """Return the GET /api/dashboard JSON body for this state.

        The key set is part of the API contract: version, sample,
        deskNetwork, flags, sources, sales, commitments, research, inbox,
        deskCheck, skills, layout, plugins, recommendations, update and
        setup, each with the nested shape the SPA reads.
        """
        return {
            "version": self.version,
            "sample": self.sample,
            "deskNetwork": self.desk_network,
            "flags": dict(self.flags),
            "sources": {
                "connected": self.sources_connected,
                "total": len(SOURCE_IDS),
                "items": [
                    {"id": source.id, "status": source.status, "detail": source.detail}
                    for source in self.sources
                ],
            },
            "sales": {
                "enabled": self.sales.enabled,
                "mode": self.sales.mode,
                "status": self.sales.status,
            },
            "commitments": {
                "enabled": self.commitments.enabled,
                "mode": self.commitments.mode,
                "status": self.commitments.status,
            },
            "research": {
                "enabled": self.research.enabled,
                "lastAnsweredTs": self.research.last_answered_ts,
            },
            "inbox": {"waiting": self.inbox_waiting},
            "deskCheck": dict(self.desk_check),
            "agentLoop": dict(self.agent_loop),
            "recommendations": [dict(item) for item in self.recommendations],
            "update": dict(self.update),
            "skills": [
                {"id": skill["id"], "name": skill["name"], "description": skill["description"]}
                for skill in self.skills
            ],
            "layout": {
                "cards": [
                    {"key": entry["key"], "title": entry["title"]}
                    for entry in self.layout_entries
                    if not entry["hidden"]
                ]
            },
            "plugins": {
                "cards": [
                    card_to_api(card, self.custom_titles.get(card["id"]))
                    for card in self.plugin_cards
                ]
            },
            "setup": dict(self.setup),
        }


def recommendation_payload(card) -> dict:
    """Project one waiting recommendation card onto the dashboard's API shape.

    The quoted fact text stays on the card body, which the inbox route already
    serves; this payload names the card, the rule's own copy and the fact ids
    only, so no memory text leaks through the dashboard.
    """
    meta = getattr(card, "meta", None) or {}
    recommendation = meta.get("recommendation") or {}
    due_ts = recommendation.get("dueTs")
    return {
        "cardId": card.id,
        "title": card.title,
        "why": card.origin,
        "whySource": recommendation.get("whySource") or "rule",
        "score": recommendation.get("score"),
        "due": dt.datetime.fromtimestamp(due_ts).date().isoformat() if due_ts else None,
        "href": recommendation.get("href") or "/agents",
        "actionLabel": card.action_label,
        "sample": bool(recommendation.get("sample")),
        "cites": [int(fact_id) for fact_id in (recommendation.get("cites") or ())],
    }


# A plugin with no widget has no card to show. Its install still lists on
# the marketplace Installed page; only the home screen drops the empty card.
# Both the old operator text and the reader sentence are matched, so a card
# recorded before the wording changed cannot slip through.
NO_WIDGET_CAUSES = (
    "plugin contributes no widget",
    "This plugin adds no card to your dashboard.",
)

# The source reason code (sources.py) for a build without an HTTP
# transport. Such a plugin can never read its source here, so a Re-test
# can never turn its amber card green: the home screen drops the card
# instead of offering a button that cannot work. This is the code, not
# the reader sentence, so changing the wording changes nothing.
UNRUNNABLE_SOURCE_REASONS = ("no-transport",)


def dashboard_plugin_cards(cards: list[dict]) -> list[dict]:
    """The plugin cards the dashboard shows.

    A card that says the plugin contributes no widget is dropped: there is
    nothing to draw, and the install stays listed on the marketplace
    Installed page. A card whose source cannot run on this desk (its
    internal reason code says no transport) is dropped for the same reason:
    it would be a permanent amber tile with a Re-test that cannot succeed.
    A setup card is a real next step, so it stays.
    """
    return [
        card for card in cards
        if card.get("state") != "contributes no widget"
        and card.get("cause") not in NO_WIDGET_CAUSES
        and card.get("sourceReason") not in UNRUNNABLE_SOURCE_REASONS
    ]


def build_dashboard_state(server, now: dt.datetime | None = None) -> DashboardState:
    """Read the dashboard's sources, plugins and layout exactly once.

    `now` stamps the rendered surfaces; None means the current local clock.
    Every collaborator is optional: a missing settings store treats every
    toggle as on, a missing source reports its honest unavailable state, and a
    missing store contributes an empty list. Plugin cards are returned with
    their insight attachment already applied.
    """
    # Imported here because app.py imports this module; the reverse import at
    # call time keeps the dependency acyclic.
    from agentdesk.server.app import enabled_plugin_ids, live_sources, with_insight

    # The same fact the marketplace reports: the live runner decides,
    # never a constant, because production builds it without a transport.
    plugin_runtime = getattr(server, "plugins", None)
    plugin_runner = getattr(plugin_runtime, "runner", None)
    desk_network = bool(getattr(plugin_runner, "has_network", False))

    settings = server.settings

    def allowed(key: str) -> bool:
        """Return the settings toggle value, treating a missing store as on."""
        return settings is None or bool(settings.get(key))

    instant = now if now is not None else dt.datetime.now()
    excel_enabled = allowed("excel_enabled")
    calendar_enabled = allowed("calendar_enabled")
    research_enabled = allowed("endpoint_enabled")

    excel = server.excel
    sales_status = excel.status() if excel is not None else None
    if not excel_enabled:
        sales = SourceState("disabled", sales_status)
    elif sales_status is not None and sales_status.get("configured"):
        sales = SourceState("live", sales_status)
    else:
        sales = SourceState("unconfigured", sales_status)

    calendar = server.calendar
    if not calendar_enabled:
        commitments = SourceState("disabled", None)
    elif calendar is None:
        commitments = SourceState("unavailable", None)
    else:
        commitments = SourceState("live", calendar.status())

    audit_conn = server.audit_conn
    last_answered_ts = (
        audit_store.last_ok_ts(audit_conn, "llm.research") if audit_conn is not None else None
    )

    skills = server.skills.active() if server.skills is not None else []
    plugin_cards = (
        dashboard_plugin_cards(server.plugins.widget_cards())
        if server.plugins is not None else []
    )
    with_insight(server, plugin_cards)

    sources = live_sources(server)
    # The AI is connected when the dashboard's own source table says so:
    # the same truth the Desk health tile prints, read once.
    sample = bool(settings.get("sample_data")) if settings is not None else False
    setup = setup_payload(
        ai_connected=any(source.id == SRC_RESEARCH and source.status == STATUS_CONNECTED
                         for source in sources),
        sample=sample, excel=excel, calendar=calendar)
    layout_entries = resolved_layout(server.layout, enabled_plugin_ids(server))
    custom_titles = {entry["key"]: entry["title"] for entry in layout_entries if entry["title"]}
    inbox_waiting = len(server.inbox.waiting()) if server.inbox is not None else 0

    # The desk check is one more read of the same collaborators. A crashing
    # check is a fatal finding, not a dashboard error, so the whole run is
    # inside a try as a last resort: the dashboard always renders.
    try:
        from agentdesk.deskcheck import summary
        from agentdesk.server.app import desk_check_result

        desk_check = summary(desk_check_result(server))
    except Exception:  # noqa: BLE001 - a check never breaks the dashboard
        desk_check = {"attention": 0, "top": None}

    # The agent loop's summary is one more read of the same shape: when it
    # last ran a pass, when the next one is due, and whether it is on. A
    # loop that cannot answer must not break the dashboard either.
    try:
        loop = getattr(server, "agent_loop", None)
        full = loop.status() if loop is not None else {}
        agent_loop = {
            "lastRunTs": full.get("lastRunTs"),
            "nextRunTs": full.get("nextRunTs"),
            "enabled": bool(full.get("enabled", False)),
        }
    except Exception:  # noqa: BLE001 - the loop never breaks the dashboard
        agent_loop = {"lastRunTs": None, "nextRunTs": None, "enabled": False}

    # Recommendations are an enrichment of the same payload: a desk without a
    # builder (or a broken one) still renders every other decision.
    recommender = getattr(server, "recommender", None)
    recommendations: tuple[dict, ...] = ()
    if recommender is not None:
        try:
            recommendations = tuple(
                recommendation_payload(card) for card in recommender.waiting()
            )
        except Exception:  # noqa: BLE001 - a card never breaks the dashboard
            recommendations = ()

    try:
        from agentdesk.server.app import update_payload

        update_state = update_payload(server)
    except Exception:  # noqa: BLE001 - updates never break the dashboard
        update_state = {"banner": None, "available": None, "autoUpdate": False,
                        "channelSet": False, "lastResult": "none"}

    return DashboardState(
        version=agentdesk.__version__,
        sample=sample,
        desk_network=desk_network,
        flags={
            "excelEnabled": excel_enabled,
            "calendarEnabled": calendar_enabled,
            "endpointEnabled": research_enabled,
        },
        sales=sales,
        commitments=commitments,
        research=ResearchState(research_enabled, last_answered_ts),
        sources=tuple(sources),
        sources_connected=sum(1 for source in sources if source.status == STATUS_CONNECTED),
        inbox_waiting=inbox_waiting,
        skills=tuple(skills),
        plugin_cards=tuple(plugin_cards),
        layout_entries=tuple(layout_entries),
        custom_titles=custom_titles,
        desk_check=desk_check,
        agent_loop=agent_loop,
        recommendations=recommendations,
        update=update_state,
        setup=setup,
        now=instant,
    )
