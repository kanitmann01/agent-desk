"""The settings page: toggles, the endpoint form, the visible parts.

Data sources, quiet hours and the notification budget are toggles or
small choices; the endpoint section takes a base URL, an API key and a
model, and tells the truth about the last call under failure. The key is
secret: this module renders only its masked state, never the value. The
activity log, skills, audit export and the what-this-touches statement
are reachable from here.
"""

import html
from datetime import datetime

from agentdesk.server.pages import page_shell

from agentdesk.repetition.skills import render_skill_md

_LABELS = {
    "excel_enabled": "Sales workbook watching",
    "calendar_enabled": "Calendar reading",
    "endpoint_enabled": "Company endpoint calls",
    "quiet_hours": "Quiet hours (18:00-08:00)",
    "daily_cap": "Notifications per day",
    "mail_enabled": "Mail digest (headers only)",
    "sample_data": "Sample data",
}

ENDPOINT_HINT = (
    "<p>Works with any OpenAI-compatible endpoint: your company gateway, "
    "OpenAI, OpenRouter, LiteLLM, or Anthropic's OpenAI-compatible URL "
    "(https://api.anthropic.com/v1 with a Claude model name). The base "
    "URL is the full API address: it starts with http:// or https:// and "
    "usually ends in the API version, like /v1; a portal sign-in page "
    "there is not an API base. A key and a URL are the whole login; "
    "there is no separate sign-in step. Saved settings win over "
    "environment variables and config.env.</p>"
)


def _registry_section(status: dict | None) -> str:
    """The registry path form plus the honest state of the resolution.

    ``status`` is the /api/registry listing shape: ok says which root
    answered and where it came from; a refusal says why, amber.
    """
    status = status or {"ok": False, "origin": "none"}
    origin_note = {
        "setting": "from this setting",
        "environment": "from the environment variable",
        "checkout": "from this app's own checkout",
        "pinned": "set for this run",
        "none": "not configured",
    }.get(str(status.get("origin", "none")), "")
    saved = html.escape(str(status.get("saved_path", "") or ""), quote=True)
    if status.get("ok"):
        state = (
            f"<p>Reading <b class='mono'>{html.escape(str(status.get('path', '')))}</b> "
            f"<span class='empty'>({origin_note})</span>.</p>")
    else:
        message = html.escape(str(status.get("message", "")))
        state = f"<div class='alert'><p>{message}</p></div>"
    return (
        state
        + "<form method='post' action='/settings/registry/path' class='cardform'>"
        "<label class='empty' for='registry-path'>Registry checkout folder</label>"
        f"<input id='registry-path' type='text' name='path' value='{saved}' "
        "placeholder='D:/registry-checkout/registry' autocomplete='off'>"
        "<button class='btn btn-secondary' type='submit'>Save path</button>"
        "</form>"
        "<p class='empty'>Saving with the field empty goes back to automatic. "
        "A folder without an index.json is refused; nothing is saved then. "
        "<a href='/plugins'>Open the plugins page</a>.</p>")


def mask_llm_key(key: str) -> str:
    """The page-facing form of a saved key: state only, never the value."""
    key = (key or "").strip()
    if not key:
        return ""
    return f"Set. Ends with {key[-4:]}." if len(key) > 4 else "Set."


def _endpoint_form(status: dict) -> str:
    """Three fields, three buttons, and the masked key state.

    The key field is always empty when rendered: the masked line and the
    placeholder are the only evidence a key is saved. Saving with the
    field empty clears the key, so the page says so plainly.
    """
    esc_base = html.escape(status.get("base", ""))
    esc_model = html.escape(status.get("model", ""))
    key_state = status.get("keyState", "")
    esc_hint = html.escape(key_state) if key_state else "Not set"
    return (
        ENDPOINT_HINT
        + f"<p class='empty'>API key: {esc_hint}. "
        "Saving with the key field empty clears the saved key.</p>"
        + "<div class='settings-block'>"
        "<label class='field'>Base URL"
        f"<input id='llm-base' type='text' value='{esc_base}' "
        "placeholder='https://llm.yourcompany.example/v1' autocomplete='off'></label>"
        "<label class='field'>API key"
        "<input id='llm-key' type='password' "
        f"placeholder='{esc_hint}' autocomplete='new-password'></label>"
        "<label class='field'>Model"
        f"<input id='llm-model' type='text' value='{esc_model}' "
        "placeholder='gpt-4o-mini' autocomplete='off'></label>"
        "</div>"
        + "<div class='cardrow'>"
        "<button class='btn btn-primary' data-endpoint-save>Save</button>"
        "<button class='btn btn-secondary' data-endpoint-test>Test connection</button>"
        "<button class='btn btn-secondary' data-endpoint-clear>Clear</button>"
        "</div>"
        + "<div class='alert' id='endpoint-note' hidden></div>"
    )


def _toggle_button(key: str, value) -> str:
    label = _LABELS.get(key, key)
    if key == "daily_cap":
        shown = {3: "3 (normal)", 1: "1 (quiet)", 0: "0 (inbox only)"}[value]
        state = shown
    else:
        state = "On" if value else "Off"
    return (
        f"<div class='setting-row'><span>{label}</span>"
        f"<button class='btn btn-secondary' data-setting='{key}'>{state}</button></div>"
    )


def _extra_hosts_section(extra_hosts: str, port: int) -> str:
    """The guard's extra-address form: a plain no-JS text field.

    By default the app answers only at its own loopback addresses; the
    copy names them (with the port this boot actually opened) and the
    field holds the sanctioned extras exactly as saved.
    """
    saved = html.escape(extra_hosts, quote=True)
    return (
        "<p>By default the app opens only at "
        f"<b class='mono'>http://127.0.0.1:{port}</b> or "
        f"<b class='mono'>http://localhost:{port}</b>, and refuses any other "
        "address. If you deliberately serve it through another address (a "
        "projected screen, a forwarded port), name it here and opening it "
        "there will work too. Each entry is a host name with an optional "
        "port, exactly as it appears in the address bar, separated by "
        "commas or spaces.</p>"
        '<form method="post" action="/settings/hosts/save" class="cardform">'
        '<label class="empty" for="extra-hosts">Also allow these addresses</label>'
        f'<input id="extra-hosts" type="text" name="hosts" value="{saved}" '
        "placeholder=\"deskpc:8765 192.168.1.20:8765\" autocomplete=\"off\">"
        '<button class="btn btn-secondary" type="submit">Save addresses</button>'
        "</form>"
        "<p class='empty'>Saving with the field empty goes back to the "
        "default. The app itself keeps listening on this machine only, and "
        "everything else about the guard is unchanged.</p>"
    )


def render_settings_page(
    activity_entries: list[dict],
    skills: list[dict],
    histories: dict[int, list[dict]],
    version: str,
    settings_values: dict | None = None,
    endpoint_status: dict | None = None,
    mail_folder: str = "",
    registry_status: dict | None = None,
    extra_hosts: str = "",
    server_port: int = 8765,
    inbox_count: int = 0,
) -> str:
    settings_values = settings_values or {}
    endpoint_status = endpoint_status or {"configured": False, "last": "never"}
    toggles_html = "".join(
        _toggle_button(key, settings_values[key]) for key in _LABELS
    )
    if endpoint_status["configured"]:
        indicator = (
            f"Configured. Last call: <b class='mono'>{html.escape(endpoint_status['last'])}</b>"
            + (" (research and the assistant are running at reduced capacity)"
               if endpoint_status["last"] == "error" else "")
        )
    else:
        indicator = "Not configured. Research and the assistant run at reduced capacity until it is set."
    endpoint_html = f"<p>{indicator}</p>" + _endpoint_form(endpoint_status)

    if activity_entries:
        rows = "".join(
            "<tr><td class='mono'>"
            f"{datetime.fromtimestamp(e['ts']).strftime('%m-%d %H:%M')}</td>"
            f"<td>{html.escape(e['kind'])}</td><td>{html.escape(e['text'][:120])}</td></tr>"
            for e in reversed(activity_entries[-30:])
        )
        activity = (
            "<table class='rows'><thead><tr><th scope='col'>When</th>"
            "<th scope='col'>Kind</th><th scope='col'>What you asked</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        activity = "<p class='empty'>Nothing asked yet. Research and assistant questions land here, for you to see.</p>"

    if skills:
        blocks = []
        for skill in skills:
            history = histories.get(skill["id"], [])
            versions = " ".join(
                f"<span class='mono'>v{h['version']} {'on' if h['active'] else 'off'}</span>"
                for h in history
            )
            md = html.escape(render_skill_md(skill["name"], skill["description"], skill["prompt"])[:400])
            undo = (
                f"<button class='btn btn-secondary btn-start' data-skill-undo='{skill['id']}'>"
                "Undo (deactivate)</button>"
                if skill["active"]
                else ""
            )
            blocks.append(
                "<article class='widget settings-skill'>"
                f"<div class='w-head'><h2 class='skill-name'>{html.escape(skill['name'])}</h2>"
                f"<span class='stamp'>{versions}</span></div>"
                f"<details><summary class='empty'>SKILL.md</summary><pre>{md}</pre></details>"
                f"{undo}</article>"
            )
        skills_html = "".join(blocks)
    else:
        skills_html = "<p class='empty'>No skills yet. Accept a proposal in the inbox and it appears here with its history.</p>"

    content = f"""<h1>Settings</h1>
<p>Toggles plus the endpoint form. The defaults are the recommended
ones; a setting you have never touched is the right setting.</p>
<div class='settings-block'>
{toggles_html}
</div>
<p class='empty'>Sample data fills a fresh desk with labelled example cards
and sample files (a workbook, a calendar file, header-only mail) so every
inbox action can be tried safely. Everything it adds is marked Sample,
and turning it off removes exactly what it added.</p>
<h2>Endpoint</h2>
{endpoint_html}
<h2>Calendar source</h2>
<p>Calendar reading follows the OneDrive sync file by default. To pick
a different file, paste a path, upload the JSON by hand, or go back to
automatic, open the <a href="/walkthrough/calendar">calendar source page</a>.</p>
<h2>Mail source</h2>
<p>Mail digest is <b>off by default</b>. When the toggle above is on,
the app polls one folder of .eml files and reads only their headers
(From, To, Cc, Subject, Date, Message-ID, In-Reply-To); bodies are
discarded at parse time and nothing is sent to any model. Reply drafts
you accept are written as files to the local outbox folder for you to
send yourself. The folder is read from this setting first, then the
AGENTDESK_MAIL_FOLDER environment variable.</p>
<form method="post" action="/settings/mail/folder" class="cardform">
<label class="empty" for="mail-folder">Mail folder</label>
<input id="mail-folder" type="text" name="folder" value="{html.escape(mail_folder, quote=True)}" placeholder="C:/Users/you/mail-exports" autocomplete="off">
<button class="btn btn-secondary" type="submit">Save folder</button>
</form>
<p class="empty">With the toggle off, nothing is read: no watcher runs and no mail cards are created. <a href="/mail">Open the mail page</a> to see the digest once it is on.</p>
<h2>Plugin registry</h2>
<p>The plugin registry is a local git checkout of the internal registry
repository. Installs are pinned by content hash and verified with the
same validator the registry's CI runs before anything executes. The
path is read from this setting first, then the AGENTDESK_REGISTRY
environment variable, then the app's own checkout.</p>
{_registry_section(registry_status)}
<h2>Where the app opens</h2>
{_extra_hosts_section(extra_hosts, server_port)}
<h2>Review</h2>
<p><a href="/activity">Read your decision log</a> (the activity page, newest first), <a href="/memory">review the facts the assistant recalls</a> (the memory page), <a href="/mail">review the mail digest</a> (headers only, off by default), <a href="/capabilities">check the environment gates, endpoint and sources</a> (the capabilities page), <a href="/audit/export.csv">export the audit log as CSV</a> (Security reads this) <span class="empty">or</span> <a href="/what-this-touches">read what this app touches</a>.</p>
<h2>Activity log</h2>
<p>Only what flows through the app: the asks you type into research and
the assistant. No keystrokes, no screen, and this list is yours.</p>
{activity}
<h2>Skills</h2>
{skills_html}
"""
    return page_shell("Settings", "/settings", content, version, inbox_count=inbox_count)
