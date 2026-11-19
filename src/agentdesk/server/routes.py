"""The declarative dispatch table for the dashboard's gated routes.

Every GET and POST the session gate protects is one row here, in matching
order, so the two dispatchers in agentdesk.server.app are a single ordered
walk instead of two if/elif ladders that must be read to the end to learn
what a path does. A row names its handler by attribute name rather than
holding a function: this module imports nothing from app (app imports it),
and the tests can prove every name resolves on DashboardHandler without
booting a server.

Ordering is the contract. The first matching row wins, exactly like the
chains this table replaced, so an exact path always sits before the prefix
that would also accept it (/marketplace before /marketplace/,
/api/plugins before /api/plugins/), and the /api/plugins/...instances...
pattern sits before the general /api/plugins/ record route.

Three families do not live here:

* /peer/... carries a peer token rather than a browser cookie, so its guard
  necessarily runs before the session gate can.
* /auth/... creates the very session the gate checks, so it too settles
  before the gate.
* /wizard, /api/marketplace/, /marketplace/ and /static/spa/ are prefix rows
  whose handlers hand off to their own routers (the wizard router, the
  marketplace API, the SPA asset directory); this table owns the gate and
  the first path segment, those owners keep their sub-paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

__all__ = [
    "GET_ROUTES",
    "POST_ROUTES",
    "Route",
    "RouteMatch",
    "match",
]


@dataclass(frozen=True)
class Route:
    """One table row: a method, a path shape and the handler attribute name.

    handler is resolved on DashboardHandler when a request matches, never at
    import, which keeps this module free of a circular import. The path shape
    is chosen by the fields: prefix=True tests str.startswith, a suffix (only
    with a prefix) additionally tests str.endswith and is how the
    /skills/<id>/skill.md-style branches are expressed, a single star or
    double star in the path compiles an anchored pattern, and no marker at
    all is an exact equality test. arg="rest" passes the matched remainder
    (the prefix remainder, or the middle between prefix and suffix) to the
    handler as its one argument; every other row calls a no-argument method.
    """

    method: str
    path: str
    handler: str
    prefix: bool = False
    arg: str = "none"
    suffix: str = ""

    def __post_init__(self) -> None:
        """Reject a row whose fields contradict the path shape it declares."""
        if not self.method:
            raise ValueError("a route needs a method")
        if self.arg not in ("none", "rest"):
            raise ValueError(f"{self.method} {self.path}: arg must be 'none' or 'rest'")
        if self.prefix:
            if "*" in self.path:
                raise ValueError(f"{self.method} {self.path}: a prefix route is not a pattern")
            if self.suffix and "*" in self.suffix:
                raise ValueError(f"{self.method} {self.path}: a suffix is not a pattern")
        elif self.suffix:
            raise ValueError(f"{self.method} {self.path}: a suffix needs a prefix")
        if self.arg == "rest" and not self.prefix:
            raise ValueError(f"{self.method} {self.path}: only a prefix route passes a remainder")
        if self.arg == "rest" and "*" in self.path:
            raise ValueError(f"{self.method} {self.path}: a pattern route passes no remainder")


@dataclass(frozen=True)
class RouteMatch:
    """The row a request matched and the remainder its handler receives.

    argument is the empty string for every row whose arg is "none", so the
    dispatcher can read it unconditionally.
    """

    route: Route
    argument: str


@lru_cache(maxsize=None)
def _compiled(path: str) -> re.Pattern[str]:
    """Compile one pattern path into its anchored regular expression.

    Double star becomes ".*" (anything, slashes included) and single star
    becomes "[^/]*" (one path segment, possibly empty, like the slash-count
    test it replaces); every other character is escaped literally. Cached
    because a table holds few patterns and the expression is rebuilt per
    match otherwise.
    """
    pieces: list[str] = []
    for piece in re.split(r"(\*{1,2})", path):
        if piece == "**":
            pieces.append(".*")
        elif piece == "*":
            pieces.append("[^/]*")
        else:
            pieces.append(re.escape(piece))
    return re.compile("".join(pieces))


def _remainder(route: Route, path: str) -> str:
    """The argument a prefix row passes: its remainder or its middle."""
    if route.suffix:
        return path[len(route.path):-len(route.suffix)]
    return path[len(route.path):]


def match(method: str, path: str) -> RouteMatch | None:
    """Return the first row this method and path match, or None.

    path must already have its query string removed, which both callers do
    before dispatch. A method with no table (anything but GET and POST)
    matches nothing. The first accepting row wins, in table order.
    """
    for route in _TABLES.get(method, ()):
        if route.prefix:
            if not path.startswith(route.path):
                continue
            if route.suffix and not path.endswith(route.suffix):
                continue
            argument = _remainder(route, path) if route.arg == "rest" else ""
            return RouteMatch(route, argument)
        if "*" in route.path:
            if _compiled(route.path).fullmatch(path):
                return RouteMatch(route, "")
        elif path == route.path:
            return RouteMatch(route, "")
    return None


GET_ROUTES: tuple[Route, ...] = (
    Route("GET", "/", "_send_index_or_dashboard"),
    Route("GET", "/health", "_send_health"),
    Route("GET", "/widgets/sales-24h", "_send_sales_status"),
    Route("GET", "/widgets/commitments", "_send_commitments_status"),
    Route("GET", "/walkthrough/calendar", "_send_walkthrough_calendar"),
    Route("GET", "/assistant", "_send_assistant_page"),
    Route("GET", "/agents", "_send_agents_page"),
    Route("GET", "/inbox", "_send_inbox_page"),
    Route("GET", "/activity", "_send_activity_redirect"),
    Route("GET", "/memory", "_send_memory_page"),
    Route("GET", "/memory/graph", "_memory_graph_page"),
    Route("GET", "/api/memory/loop", "_memory_loop_json"),
    Route("GET", "/api/memory/graph", "_memory_graph_json"),
    Route("GET", "/memory/sweep", "_memory_sweep_page"),
    Route("GET", "/memory/encrypt", "_memory_encrypt_page"),
    Route("GET", "/mail", "_send_mail_page"),
    Route("GET", "/capabilities", "_send_capabilities_page"),
    Route("GET", "/plugins", "_send_plugins_redirect"),
    Route("GET", "/peers", "_send_peers_page_request"),
    Route("GET", "/widgets/inbox", "_send_inbox_count"),
    Route("GET", "/settings/activity", "_send_audit_page"),
    Route("GET", "/settings", "_send_settings_page"),
    Route("GET", "/skills/", "_send_skill_markdown_rest", prefix=True, arg="rest",
          suffix="/skill.md"),
    Route("GET", "/audit/tail", "_send_audit_tail"),
    Route("GET", "/widgets/settings", "_send_settings_values"),
    Route("GET", "/wizard", "_wizard_request", prefix=True),
    Route("GET", "/api/marketplace/", "_marketplace_api_get", prefix=True),
    Route("GET", "/api/plugins", "_send_plugins_api_list"),
    Route("GET", "/api/registry", "_send_registry_listing"),
    Route("GET", "/api/peers", "_send_peers_api"),
    Route("GET", "/api/dashboard", "_send_dashboard_api"),
    Route("GET", "/api/preferences", "_send_preferences_values"),
    Route("GET", "/api/layout", "_send_layout_api"),
    Route("GET", "/api/plugins/**instances**", "_plugin_setup_get_request"),
    Route("GET", "/api/plugins/", "_plugin_record_get", prefix=True, arg="rest"),
    Route("GET", "/audit/export.csv", "_send_audit_csv"),
    Route("GET", "/what-this-touches", "_send_touches_page"),
    Route("GET", "/static/app.css", "_send_styles_asset"),
    Route("GET", "/static/app.js", "_send_app_js_asset"),
    Route("GET", "/static/theme-boot.js", "_send_theme_boot_asset"),
    Route("GET", "/static/spa/", "_send_spa_asset", prefix=True, arg="rest"),
    Route("GET", "/marketplace", "_send_marketplace_shell_request"),
    Route("GET", "/marketplace/", "_send_marketplace_shell_request", prefix=True),
)

POST_ROUTES: tuple[Route, ...] = (
    Route("POST", "/api/preferences", "_preferences_write"),
    Route("POST", "/api/insight/draft", "_insight_draft"),
    Route("POST", "/insight/press", "_insight_press_page"),
    Route("POST", "/sources/excel-watch/pick", "_excel_watch_pick"),
    Route("POST", "/sources/excel-watch", "_excel_watch_register"),
    Route("POST", "/sources/excel-watch/retest", "_excel_watch_retest"),
    Route("POST", "/widgets/commitments/check", "_commitment_check"),
    Route("POST", "/sources/calendar-bridge/retest", "_calendar_bridge_retest"),
    Route("POST", "/sources/calendar-bridge/pick", "_calendar_bridge_pick"),
    Route("POST", "/sources/calendar-bridge/path", "_calendar_bridge_path"),
    Route("POST", "/sources/calendar-bridge/upload", "_calendar_bridge_upload"),
    Route("POST", "/sources/calendar-bridge/reset", "_calendar_bridge_reset"),
    Route("POST", "/research", "_research_ask"),
    Route("POST", "/inbox/cards", "_inbox_card_add"),
    Route("POST", "/inbox/cards/", "_inbox_accept", prefix=True, arg="rest",
          suffix="/accept"),
    Route("POST", "/inbox/cards/", "_inbox_dismiss", prefix=True, arg="rest",
          suffix="/dismiss"),
    Route("POST", "/inbox/cards/", "_inbox_edit", prefix=True, arg="rest",
          suffix="/edit"),
    Route("POST", "/inbox/cards/", "_inbox_snooze", prefix=True, arg="rest",
          suffix="/snooze"),
    Route("POST", "/inbox/cards/", "_inbox_more_info", prefix=True, arg="rest",
          suffix="/more-info"),
    Route("POST", "/inbox/dismissed/", "_inbox_restore", prefix=True, arg="rest",
          suffix="/restore"),
    Route("POST", "/memory/add", "_memory_add"),
    Route("POST", "/memory/", "_memory_edit_rest", prefix=True, arg="rest",
          suffix="/edit"),
    Route("POST", "/memory/", "_memory_delete_rest", prefix=True, arg="rest",
          suffix="/delete"),
    Route("POST", "/memory/recall", "_memory_recall"),
    Route("POST", "/memory/entities/merge", "_memory_entities_merge"),
    Route("POST", "/memory/sweep", "_memory_sweep"),
    Route("POST", "/memory/encrypt", "_memory_encrypt"),
    Route("POST", "/memory/retain", "_memory_retain"),
    Route("POST", "/memory/reflect", "_memory_reflect"),
    Route("POST", "/memory/embeddings/backfill", "_memory_embeddings_backfill"),
    Route("POST", "/api/memory/remove/preview", "_memory_remove_preview"),
    Route("POST", "/api/memory/remove", "_memory_remove_apply"),
    Route("POST", "/api/memory/undo", "_memory_undo"),
    Route("POST", "/api/memory/facts/", "_memory_keep", prefix=True, arg="rest",
          suffix="/keep"),
    Route("POST", "/capabilities/", "_capabilities_retest", prefix=True, arg="rest",
          suffix="/retest"),
    Route("POST", "/inbox/consolidate", "_inbox_consolidate"),
    Route("POST", "/skills/", "_skill_run_rest", prefix=True, arg="rest",
          suffix="/run"),
    Route("POST", "/skills/", "_skill_undo_rest", prefix=True, arg="rest",
          suffix="/undo"),
    Route("POST", "/settings/toggle", "_settings_toggle"),
    Route("POST", "/api/layout", "_layout_save"),
    Route("POST", "/settings/endpoint/save", "_endpoint_save"),
    Route("POST", "/settings/endpoint/test", "_endpoint_test"),
    Route("POST", "/settings/mail/folder", "_mail_folder_save"),
    Route("POST", "/settings/preferences", "_preferences_save"),
    Route("POST", "/settings/registry/path", "_registry_path_save"),
    Route("POST", "/settings/hosts/save", "_extra_hosts_save"),
    Route("POST", "/api/registry/install", "_registry_install"),
    Route("POST", "/plugins/registry-install", "_registry_install"),
    Route("POST", "/peers/code", "_peers_code_generate"),
    Route("POST", "/peers/pair", "_peers_pair"),
    Route("POST", "/peers/refresh", "_peers_refresh"),
    Route("POST", "/peers/install", "_peers_install"),
    Route("POST", "/peers/update", "_peers_update"),
    Route("POST", "/plugins/*/*", "_plugins_page_action_request"),
    Route("POST", "/mail/retest", "_mail_retest"),
    Route("POST", "/mail/", "_mail_draft_rest", prefix=True, arg="rest",
          suffix="/draft"),
    Route("POST", "/wizard", "_wizard_request", prefix=True),
    Route("POST", "/api/marketplace/", "_marketplace_api_post", prefix=True),
    Route("POST", "/api/plugins", "_plugin_api_post", prefix=True),
    Route("POST", "/assistant/ask", "_assistant_ask"),
    Route("POST", "/agents/run", "_agents_run"),
    Route("POST", "/agents/runs/", "_agents_feedback", prefix=True, arg="rest",
          suffix="/feedback"),
)

_TABLES: dict[str, tuple[Route, ...]] = {
    "GET": GET_ROUTES,
    "POST": POST_ROUTES,
}
