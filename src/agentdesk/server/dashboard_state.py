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
from agentdesk.layout import resolved_layout
from agentdesk.plugins.cards import card_to_api
from agentdesk.server.core import SOURCE_IDS, STATUS_CONNECTED, SourceStatus


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
    now: dt.datetime

    def payload(self) -> dict:
        """Return the GET /api/dashboard JSON body for this state.

        The key set is part of the API contract: version, sample, flags,
        sources, sales, commitments, research, inbox, deskCheck, skills,
        layout and plugins, each with the nested shape the SPA reads.
        """
        return {
            "version": self.version,
            "sample": self.sample,
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
        }


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
    plugin_cards = server.plugins.widget_cards() if server.plugins is not None else []
    with_insight(server, plugin_cards)

    sources = live_sources(server)
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

    return DashboardState(
        version=agentdesk.__version__,
        sample=bool(settings.get("sample_data")) if settings is not None else False,
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
        now=instant,
    )
