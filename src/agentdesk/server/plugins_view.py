"""The plugins page: what is installed, what the registry offers.

Plain forms throughout (no script needed): every action posts back to
this page's own routes, which drive the same runtime methods the JSON
API uses. Registry state is honest at every step: an unavailable or
invalid registry shows amber with its cause, never an empty success,
and an installed plugin says which version is active and whether a
re-consent is waiting. The page rides the shared shell (rail plus
footer), so navigation belongs to the rail.
"""

import html

from agentdesk.server import pages

_RISK_NOTE = {
    "low": "low risk",
    "medium": "medium risk",
    "high": "high risk",
}

_CLASS_NOTE = {
    "declarative": "declarative (no plugin code runs)",
}


def _installed_block(record: dict, shared_ids: set[str] | None = None,
                     peers_paired: int = 0) -> str:
    shared_ids = shared_ids or set()
    plugin_id = html.escape(str(record["id"]))
    name = html.escape(str(record.get("name", record["id"])))
    version = html.escape(str(record.get("active_version", "")))
    state = str(record.get("state", ""))
    source = html.escape(str(record.get("source", "zip")))
    data = record.get("data_source") or {}
    freshness = str(data.get("status", "attention"))
    cause = html.escape(str(data.get("cause", "")) or "data source has not run")
    pilot = int(record.get("pilot_views_left", 0) or 0)
    pending = record.get("pending_update")

    lines = []
    if state == "uninstalled":
        lines.append(
            f"<p class='empty'>Uninstalled. Its data is kept until you purge "
            f"it; purging needs the confirmation text "
            f"<span class='mono'>delete-data:{plugin_id}</span>.</p>")
        lines.append(
            f"<form method='post' action='/plugins/{plugin_id}/purge-data' class='cardform'>"
            f"<label class='empty' for='purge-{plugin_id}'>Confirmation</label>"
            f"<input id='purge-{plugin_id}' type='text' name='confirmation' "
            f"placeholder='delete-data:{plugin_id}' autocomplete='off'>"
            "<button class='btn btn-secondary' type='submit'>Purge data</button>"
            "</form>")
        return f"<article class='card'><h3>{name}</h3>{''.join(lines)}</article>"

    if state == "enabled":
        state_note = (f"enabled, reading {html.escape(str(data.get('file', '')))}"
                      if data.get("file") else "enabled")
    else:
        state_note = "disabled"
    badge = " <span class='empty mono'>PILOT</span>" if pilot > 0 else ""
    body = (
        f"<p><b>v{version}</b> from {source}{badge}. "
        f"<span class='empty'>{state_note}.</span></p>"
    )
    if freshness == "fresh":
        body += "<p class='empty'>Data source fresh.</p>"
    else:
        body += f"<div class='alert'><p>{cause}</p></div>"

    actions = []
    if state == "enabled":
        actions.append(("Disable", "disable", "btn-secondary"))
        actions.append(("Re-test", "retest", "btn-secondary"))
    else:
        actions.append(("Enable", "enable", "btn-primary"))
    if len(record.get("versions", [])) > 1:
        actions.append(("Roll back", "rollback", "btn-secondary"))
    # The create-to-publish loop: every installed plugin can become a
    # local registry release (validated, digest-pinned) in one click.
    actions.append(("Publish", "publish", "btn-secondary"))
    actions.append(("Uninstall", "uninstall", "btn-secondary"))
    forms = "".join(
        f"<form method='post' action='/plugins/{plugin_id}/{action}' class='inlineform'>"
        f"<button class='btn {cls}' type='submit'>{html.escape(label)}</button>"
        "</form>"
        for label, action, cls in actions)
    # The Share toggle (ticket #67): paired desks can install this
    # plugin from this desk while it is shared.
    shared = str(record["id"]) in shared_ids
    if shared:
        share_note = ("<p class='empty'>Shared with paired desks: they "
                      "see its manifest and bundle, never your data.</p>")
        share_form = (
            f"<form method='post' action='/plugins/{plugin_id}/unshare' "
            "class='inlineform'><button class='btn btn-secondary' "
            "type='submit'>Stop sharing</button></form>")
    else:
        share_note = ""
        share_form = (
            f"<form method='post' action='/plugins/{plugin_id}/share' "
            "class='inlineform'><button class='btn btn-secondary' "
            "type='submit'>Share with peers</button></form>")
    forms = share_form + forms
    body += f"<div class='cardrow'>{forms}</div>{share_note}"

    if pending:
        added = html.escape("; ".join(pending.get("added_scopes", [])))
        body += (
            f"<div class='alert'><p>An update to v{html.escape(str(pending.get('version', '')))} "
            f"is waiting for your decision. It adds: {added}.</p></div>"
            f"<div class='cardrow'>"
            f"<form method='post' action='/plugins/{plugin_id}/consent' class='inlineform'>"
            "<button class='btn btn-primary' type='submit'>Allow update</button></form>"
            "</div>")

    return f"<article class='card'><h3>{name} <span class='empty mono'>{plugin_id}</span></h3>{body}</article>"


def _registry_block(entry: dict, installed_ids: set[str]) -> str:
    plugin_id = html.escape(str(entry["id"]))
    publisher = html.escape(str(entry["publisher"]))
    latest = html.escape(str(entry["latest"]))
    risk = _RISK_NOTE.get(str(entry["risk"]), html.escape(str(entry["risk"])))
    class_note = _CLASS_NOTE.get(str(entry["class"]), html.escape(str(entry["class"])))
    releases = entry.get("releases", [])
    yanked = all(bool(r.get("yanked")) for r in releases) and bool(releases)
    if plugin_id in installed_ids:
        action = "<p class='empty'>Installed.</p>"
    elif yanked:
        action = "<p class='empty'>The latest release is yanked; it stays listed for pinned installs.</p>"
    else:
        action = (
            f"<form method='post' action='/plugins/registry-install' class='cardform'>"
            f"<input type='hidden' name='id' value='{plugin_id}'>"
            f"<input type='hidden' name='version' value='{latest}'>"
            "<button class='btn btn-primary' type='submit'>Install</button>"
            "</form>")
    return (
        f"<article class='card'><h3>{plugin_id} <span class='empty'>{publisher}</span></h3>"
        f"<p>v{latest}, {risk}, {class_note}.</p>{action}</article>"
    )


def render_plugins_page(records: list[dict], listing: dict, origin: str,
                        version: str, notice: str = "",
                        inbox_count: int = 0,
                        shared_ids: set[str] | None = None,
                        peers_paired: int = 0) -> str:
    installed = [record for record in records
                 if record.get("state") != "uninstalled"]
    uninstalled = [record for record in records
                   if record.get("state") == "uninstalled"]
    installed_ids = {str(record["id"]) for record in installed}

    if installed:
        installed_html = "".join(
            _installed_block(record, shared_ids, peers_paired)
            for record in installed)
    else:
        installed_html = (
            "<p class='empty'>Nothing installed yet. The wizard builds one "
            "from a plain-English description, or install a published plugin "
            "from the registry below.</p>")

    graveyard_html = ""
    if uninstalled:
        graveyard_html = (
            "<h2>Removed, data kept</h2>"
            + "".join(_installed_block(record) for record in uninstalled))

    if listing.get("ok"):
        origin_note = html.escape(str(listing.get("path", "")))
        entries = listing.get("plugins", [])
        registry_html = (
            f"<p class='empty mono'>{origin_note} (from {html.escape(origin)})</p>")
        if entries:
            registry_html += "".join(
                _registry_block(entry, installed_ids) for entry in entries)
        else:
            registry_html += "<p class='empty'>The registry has no plugins yet.</p>"
    else:
        message = html.escape(str(listing.get("message", "")))
        registry_html = (
            f"<div class='alert'><p>{message}</p></div>"
            "<p class='empty'>Point the app at a local git checkout of the "
            "registry on the <a href='/settings'>settings page</a>.</p>")

    notice_html = f"<div class='alert'><p>{html.escape(notice)}</p></div>" if notice else ""

    content = (
        "<h1>Plugins</h1>"
        "<p>Installed plugins run their declared data sources and show "
        "their own card on the dashboard. Every install goes through the "
        "same validator the registry's CI runs; nothing executes before "
        "it passes.</p>"
        f"{notice_html}"
        f"<h2>Installed</h2>{installed_html}"
        f"<h2>From the registry</h2>{registry_html}"
        f"{graveyard_html}"
    )
    return pages.page_shell("Plugins", "/plugins", content, version,
                            inbox_count=inbox_count)
