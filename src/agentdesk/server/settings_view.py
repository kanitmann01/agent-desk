"""The settings page: toggles, the endpoint form, the visible parts.

Data sources, quiet hours and the notification budget are toggles or
small choices; the endpoint section takes a base URL, an API key and a
model, and tells the truth about the last call under failure. The key is
secret: this module renders only its masked state, never the value. The
activity log, skills, audit export and the what-this-touches statement
are reachable from here. The preferences card is the only place the desk
is told what to assume about its reader; its values are read back from the
store on every render, never inferred.
"""

import html
from datetime import datetime

from agentdesk.insight.preferences import PreferenceStore, changed
from agentdesk.keys.presets import PRESETS, preset_for
from agentdesk.repetition.skills import render_skill_md
from agentdesk.server import audit_view
from agentdesk.server.pages import page_shell

_LABELS = {
    "excel_enabled": "Sales workbook watching",
    "calendar_enabled": "Calendar reading",
    "endpoint_enabled": "Company endpoint calls",
    "quiet_hours": "Quiet hours (18:00-08:00)",
    "daily_cap": "Notifications per day",
    "mail_enabled": "Mail digest (headers only)",
    "sample_data": "Sample data",
    "semantic_memory": "Semantic memory (embeddings)",
    "suggest_headers_only": "Suggest columns from headers only",
    "plugin_instance_cap": "Plugin instances per plugin",
}

ENDPOINT_HINT = (
    "<p>Any OpenAI-compatible endpoint works: your company gateway, "
    "OpenAI, OpenRouter, LiteLLM, Azure AI Foundry, or Anthropic at "
    "https://api.anthropic.com/v1. Use the full API address: it starts "
    "with http:// or https:// and usually ends in /v1; a portal sign-in "
    "page is not an API base. The key and URL are the whole login. "
    "Saving with an empty key field clears the saved key. Saved settings "
    "win over environment variables.</p>"
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
        "<a href='/marketplace/installed'>Open Marketplace</a>.</p>")


def _esc_timeout(status: dict) -> str:
    """The presentation timeout as the form shows it."""
    return html.escape(str(status.get("presentationTimeout") or "30"))


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
        "<label class='field'>Presentation timeout (seconds)"
        f"<input id='presentation-timeout' type='text' value='{_esc_timeout(status)}' "
        "placeholder='30' autocomplete='off'></label>"
        "<label class='field'>Web research URL"
        f"<input id='research-url' type='text' value='{html.escape(str(status.get('researchUrl') or ''))}' "
        "placeholder='https://research.example/v1' autocomplete='off'></label>"
        "<label class='field'>Web research key"
        "<input id='research-key' type='password' "
        f"placeholder='{html.escape(str(status.get('researchKeyState') or 'Not set'))}' "
        "autocomplete='new-password'></label>"
        "</div>"
        + "<p class='empty'>The research key is shown only as set or not set. "
        "Leaving the field empty keeps the saved key. "
        "Clear research key removes it. "
        "Web research stays off until a presentation run turns it on.</p>"
        + "<div class='cardrow'>"
        "<button class='btn btn-primary' data-endpoint-save>Save</button>"
        "<button class='btn btn-secondary' data-endpoint-test>Test connection</button>"
        "<button class='btn btn-secondary' data-endpoint-clear>Clear</button>"
        "<button class='btn btn-secondary' type='button' data-research-clear>Clear research key</button>"
        "</div>"
        + "<div class='alert' id='endpoint-note' hidden></div>"
    )


def _toggle_button(key: str, value, label: str | None = None) -> str:
    """One settings row: its label and a button showing the current value.

    daily_cap is shown as a named level, plugin_instance_cap as a plain count, and every
    other key as On or Off, so the button text reads as the state the next click
    changes. data-setting names the key the client posts back.
    """
    label = label or _LABELS.get(key, key)
    if key == "daily_cap":
        shown = {3: "3 (normal)", 1: "1 (quiet)", 0: "0 (inbox only)"}[value]
        state = shown
    elif key == "plugin_instance_cap":
        state = str(value)
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


_THEMES = (
    ("unkey", "Unkey", "Dark, yellow-green"),
    ("coforge", "Coforge", "Navy, coral"),
    ("momentuum", "Momentuum blue", "Light, brand blue"),
)


def _theme_tiles() -> str:
    """The Appearance picker. A radiogroup of three tiles; app.js marks
    the stored theme as checked and keeps keyboard focus roving. Each
    swatch takes its colours from its own data-theme-preview scope."""
    tiles = "".join(
        f"<button type='button' class='theme-tile' role='radio' aria-checked='false' "
        f"tabindex='-1' data-theme-option='{tid}'>"
        f"<span class='tile-sw' data-theme-preview='{tid}' aria-hidden='true'><i></i><i></i><i></i></span>"
        f"<b>{name}</b><small>{note}</small></button>"
        for tid, name, note in _THEMES
    )
    return f"<div class='theme-tiles' role='radiogroup' aria-label='Theme'>{tiles}</div>"


_PREFERENCE_CHOICES = (
    (
        "chart",
        "Chart shape",
        "Automatic lets each reading choose; the others ask for that shape.",
        (
            ("auto", "Automatic, from the data"),
            ("bar", "Bar"),
            ("line", "Line"),
            ("table", "Table"),
        ),
    ),
    (
        "replyTone",
        "Reply tone",
        "Used when you press a draft control, never on its own.",
        (("direct", "Direct"), ("warm", "Warm"), ("formal", "Formal")),
    ),
    (
        "replyLength",
        "Reply length",
        "",
        (("one-line", "One line"), ("short", "Short"), ("paragraph", "A paragraph")),
    ),
    (
        "insightDensity",
        "How much each card says",
        "Quiet keeps one line; chatty adds the suggested rows and topics.",
        (("quiet", "Quiet"), ("normal", "Normal"), ("chatty", "Chatty")),
    ),
)


def _stored_preferences() -> dict:
    """The document the desk would use on its next dashboard read.

    The data directory is resolved by app.py, which imports this module,
    so the lookup happens here rather than at import time (the shape
    touches.py uses for its statement).
    """
    from agentdesk.server.app import default_data_dir

    return PreferenceStore(default_data_dir()).read()


def _preferences_section(document: dict, notice: str = "") -> str:
    """The six statements of preference, as the store currently holds them.

    Every value is server-rendered, so the card reads with no script at
    all. The form posts its six fields to /settings/preferences, which
    converts the two typed ones and answers with a 303 carrying the
    store's own refusal back here as the notice.
    """
    fields = []
    for key, label, hint, choices in _PREFERENCE_CHOICES:
        stored = str(document.get(key, ""))
        options = "".join(
            f"<option value='{value}'"
            + (" selected" if value == stored else "")
            + f">{name}</option>"
            for value, name in choices
        )
        fields.append(
            f"<label class='empty' for='pref-{key}'>{label}</label>"
            f"<select id='pref-{key}' name='{key}'>{options}</select>"
            + (f"<p class='empty'>{hint}</p>" if hint else "")
        )
    topics = document.get("focusTopics")
    topics = [str(topic) for topic in topics] if isinstance(topics, list) else []
    minutes = document.get("prepMinutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        minutes = 15
    stated = len(changed(document))
    stamp = f"{stated} SET" if stated else "DEFAULTS"
    topics_text = html.escape("\n".join(topics))
    note = (
        f"<div class='alert' id='preferences-note'>{html.escape(notice)}</div>"
        if notice
        else "<div class='alert' id='preferences-note' hidden></div>"
    )
    return f"""<section class='card settings-card' id='preferences'>
<div class='w-head'><h2>What the desk knows about you</h2><span class='stamp'>{stamp}</span></div>
<p>These six are the only preferences the desk uses. You state them here,
and it never infers them from what you open, select or reply to. A saved
value applies from the next dashboard read.</p>
<form method='post' action='/settings/preferences' class='cardform' id='preferences-form'>
{''.join(fields)}
<label class='empty' for='pref-focusTopics'>Focus topics</label>
<textarea id='pref-focusTopics' name='focusTopics' rows='3'>{topics_text}</textarea>
<p class='empty'>One topic per line, up to ten, each a short line.</p>
<label class='empty' for='pref-prepMinutes'>Meeting prep (minutes)</label>
<input id='pref-prepMinutes' name='prepMinutes' type='number' min='0' max='120' step='1' value='{minutes}'>
<p class='empty'>How much reading you want before a meeting, 0 to 120.</p>
<button class='btn btn-secondary' type='submit'>Save preferences</button>
</form>
{note}
<p class='empty'>A value the desk cannot accept leaves every stored
preference as it was, and the reason appears above in the server's words.</p>
</section>"""


def _record_card(audit_entries: list[dict], audit_total: int) -> str:
    """The trail's front door: the count, the last five rows, the links.

    The count comes from the store, not from this page's window, so a
    desk with a thousand actions does not claim there are sixty.
    """
    total = audit_total if audit_total is not None else len(audit_entries)
    stamp = f"{total} ACTIONS"
    if audit_entries:
        rows = "".join(
            "<tr><td class='mono'>"
            f"{audit_view.when_text(float(e.get('ts', 0)))}</td>"
            f"<td>{html.escape(audit_view.kind_for(str(e.get('action', ''))))}</td>"
            f"<td>{html.escape(audit_view.word_for(str(e.get('action', ''))))}</td>"
            f"<td class='mono'>{html.escape(str(e.get('status', 'ok')))}</td></tr>"
            for e in audit_entries[:5]
        )
        recent = (
            "<table class='rows'><thead><tr><th scope='col'>When</th>"
            "<th scope='col'>Kind</th><th scope='col'>Action</th>"
            "<th scope='col'>Status</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        recent = (
            "<p class='empty'>No actions recorded yet. The first one lands "
            "here and on the trail.</p>"
        )
    return f"""<section class='card settings-card' id='record'>
<div class='w-head'><h2>Record</h2><span class='stamp'>{stamp}</span></div>
<p>One trail for the whole desk. Every inbox decision, model call, file
read, plugin change, registry write, settings save and peer request is
recorded with its time and status, and nothing here can be edited.</p>
<h3>Review</h3>
<div class='settings-links'>
<a class='btn btn-secondary' href="/settings/activity">Open the activity trail</a>
<a class='btn btn-secondary' href="/capabilities">Check the environment</a>
<a class='btn btn-secondary' href="/audit/export.csv">Export as CSV</a>
</div>
{recent}
</section>"""


def _agent_section(settings_values: dict) -> str:
    """The Agent switch: whether the desk acts on its own.

    This ticket ships the stub only: the switch and the help text naming
    the four things that still ask first. The rest of the section lands
    with the tickets that give the autonomous loop something to act on.
    """
    on = bool(settings_values.get("autonomy", True))
    stamp = "AUTONOMY ON" if on else "AUTONOMY OFF"
    return f"""<section class='card settings-card' id='agent'>
<div class='w-head'><h2>Agent</h2><span class='stamp'>{stamp}</span></div>
<div class='settings-block'>
{_toggle_button("autonomy", on, label="Act on its own")}
</div>
<p class='empty'>On by default: the desk acts on its own, and every change it
makes by itself is recorded on <a href="/settings/activity">Activity</a> with
an Undo button. It still asks first before sending email or messages,
deleting your data, uninstalling a plugin, or installing a new plugin.</p>
</section>"""


def _connection_rows(connections: list[dict]) -> str:
    """The saved-connections table: label, preset, masked key, base URL,
    status badge with its inline cause, default star, Test, edit and
    delete. A raw key never reaches this markup; the masked hint is the
    only key-shaped thing on the page, and the badge state renders from
    the row alone, so the page works with no script at all."""
    rows = []
    for c in connections:
        preset = preset_for(c.get("provider", ""))
        preset_name = preset.name if preset else str(c.get("provider", ""))
        label = html.escape(str(c.get("label", "")))
        star = " <span aria-label='default connection'>&#9733;</span>" if c.get("isDefault") else ""
        masked = html.escape(str(c.get("maskedKey", "") or ""))
        key_cell = f"<span class='mono'>{masked}</span>" if masked else \
            "<span class='empty'>no key</span>"
        base = html.escape(str(c.get("baseUrl", "")))
        connection_id = html.escape(str(c.get("id", "")), quote=True)
        status = html.escape(str(c.get("status") or "unknown"))
        cause = html.escape(str(c.get("lastError", "") or ""))
        cause_line = f"<br><span class='empty'>{cause}</span>" if cause else ""
        checked = c.get("lastCheckedAt")
        when = (
            f"<br><span class='empty mono'>checked "
            + datetime.fromtimestamp(float(checked)).strftime("%m-%d %H:%M")
            + "</span>" if checked else ""
        )
        models = c.get("models") or []
        fetched = c.get("modelsFetchedAt")
        models_line = (
            f"<br><span class='empty'>{len(models)} model"
            f"{'s' if len(models) != 1 else ''} cached</span>"
            if fetched else ""
        )
        rows.append(
            "<tr>"
            f"<td><b>{label}</b>{star}</td>"
            f"<td>{html.escape(preset_name)}</td>"
            f"<td>{key_cell}</td>"
            f"<td class='mono'>{base}</td>"
            f"<td><span class='conn-status conn-{status}'>{status}</span>"
            f"{cause_line}{when}{models_line}</td>"
            f"<td><form method='post' action='/api/connections/{connection_id}/test'"
            " class='inlineform'>"
            "<button class='btn btn-secondary' type='submit'>Test</button></form> "
            f"<a class='btn btn-secondary' href='/settings?connection={connection_id}'>Edit</a> "
            f"<form method='post' action='/api/connections/{connection_id}/delete' class='inlineform'>"
            "<button class='btn btn-secondary' type='submit'>Delete</button></form></td>"
            "</tr>"
        )
    return (
        "<table class='rows'><thead><tr><th scope='col'>Connection</th>"
        "<th scope='col'>Preset</th><th scope='col'>Key</th>"
        "<th scope='col'>Base URL</th><th scope='col'>Status</th>"
        "<th scope='col'>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _preset_grid(selected: str) -> str:
    """The provider radios: one tile per preset, the selected one checked.

    Each input carries its preset's default base URL as data, so the
    script can fill the base field on choice; without script the server
    fills the same default when the field arrives empty."""
    tiles = []
    for preset in PRESETS:
        checked = " checked" if preset.id == selected else ""
        tiles.append(
            f"<label class='preset-tile'><input type='radio' name='provider'"
            f" value='{preset.id}'{checked} data-base='{html.escape(preset.base_url, quote=True)}'>"
            f"{html.escape(preset.name)}"
            + (" <span class='empty'>(no key)</span>" if preset.key_optional else "")
            + "</label>"
        )
    return (
        "<fieldset class='preset-grid'><legend class='empty'>Provider</legend>"
        + "".join(tiles) + "</fieldset>"
    )


def _console_links() -> str:
    """One deep-link per hosted preset: where its keys are issued."""
    links = "".join(
        f"<a class='btn btn-secondary' href='{preset.console_url}'>"
        f"{html.escape(preset.name)}</a>"
        for preset in PRESETS if preset.console_url
    )
    return f"<div class='settings-links'>{links}</div>"


def _health_forms(editing: dict | None) -> str:
    """The two check forms for one saved connection, or "" while adding.

    Test posts the free model-list request and never completes a chat.
    The deeper check takes the model typed by hand, always available and
    never gated on a listing existing, and completes exactly one token
    with it. Both are plain form posts, so the badge they refresh and
    the cause it shows render server-side on the redirect back."""
    if editing is None:
        return ""
    connection_id = html.escape(str(editing.get("id", "")), quote=True)
    return f"""<h3>Check the key</h3>
<form method='post' action='/api/connections/{connection_id}/test' class='cardform'>
<p class='empty'>Test makes one free model-list request with the saved
key; it never completes a chat. The badge in the list above shows the
outcome with its cause.</p>
<button class='btn btn-secondary' type='submit'>Test connection</button>
</form>
<form method='post' action='/api/connections/{connection_id}/check' class='cardform'>
<label class='empty' for='conn-check-model'>Model, typed by hand (the
deeper check completes exactly one token with it)</label>
<input id='conn-check-model' type='text' name='model'
 placeholder='for example gpt-4o-mini' autocomplete='off'>
<p class='empty'>For endpoints with no model listing, this one-token
completion is the only way to verify the key.</p>
<button class='btn btn-secondary' type='submit'>Deeper check (one-token completion)</button>
</form>"""


def _connections_section(
    connections: list[dict] | None,
    editing: dict | None,
    keychain_available: bool,
    notice: str = "",
) -> str:
    """The keys card: the connections list, then the add/edit form.

    Server-rendered throughout: the form posts as a plain form, the
    masked hints are printed, and the preset grid and console deep-links
    answer the two first-run questions with no script at all. The edit
    semantic is the one rule everywhere: an empty key field keeps the
    stored key, and only the separate clear action removes it.
    """
    if connections is None:
        body = (
            "<div class='alert'><p>The connections store is not available,"
            " so connections cannot be saved here.</p></div>"
        )
        stamp = "UNAVAILABLE"
    else:
        notice_block = (
            f"<div class='alert'><p>{html.escape(notice)}</p></div>" if notice else ""
        )
        keychain_block = "" if keychain_available else (
            "<div class='alert'><p>This machine has no keychain, so secrets"
            " cannot be stored here. Local presets still work without a"
            " key, and environment variables still resolve.</p></div>"
        )
        if connections:
            listing = _connection_rows(connections)
        else:
            listing = (
                "<p class='empty'>No connections yet. Pick a provider below,"
                " paste its key and save; it lands in this machine's"
                " keychain, never in a file the desk writes.</p>"
            )
        if editing is not None:
            heading = "Edit connection"
            action = f"/api/connections/{html.escape(str(editing['id']), quote=True)}/update"
            label_value = html.escape(str(editing.get("label", "")), quote=True)
            base_value = html.escape(str(editing.get("baseUrl", "")), quote=True)
            selected = str(editing.get("provider", ""))
            key_placeholder = html.escape(
                str(editing.get("maskedKey") or "not set"), quote=True)
            headers_text = html.escape("\n".join(
                f"{name}: {value}"
                for name, value in (editing.get("headers") or {}).items()))
            default_checked = " checked" if editing.get("isDefault") else ""
            clear_row = (
                "<label class='empty'><input type='checkbox' name='keyClear'"
                " value='1'> Remove the stored key</label>"
            )
            cancel = " <a class='btn btn-secondary' href='/settings'>Cancel</a>"
        else:
            heading = "Add a connection"
            action = "/api/connections"
            label_value = ""
            base_value = ""
            selected = PRESETS[0].id
            key_placeholder = "not required for local presets"
            headers_text = ""
            default_checked = ""
            clear_row = ""
            cancel = ""
        form = f"""<h3>{heading}</h3>
<form method='post' action='{action}' class='cardform' id='connection-form'>
{_preset_grid(selected)}
<label class='empty' for='conn-label'>Label</label>
<input id='conn-label' type='text' name='label' value='{label_value}' placeholder='OpenAI personal' autocomplete='off'>
<label class='empty' for='conn-base'>Base URL</label>
<input id='conn-base' type='text' name='baseUrl' value='{base_value}' placeholder='filled from the preset when empty' autocomplete='off'>
<label class='empty' for='conn-key'>API key</label>
<input id='conn-key' type='password' name='apiKey' placeholder='{key_placeholder}' autocomplete='new-password'>
<label class='empty' for='conn-key-show'><input type='checkbox' id='conn-key-show' data-key-reveal> Show the key while typing</label>
<label class='empty' for='conn-headers'>Extra headers (corporate gateways, one Name: Value per line)</label>
<textarea id='conn-headers' name='headers' rows='2' placeholder='X-Gateway: corp'>{headers_text}</textarea>
<label class='empty'><input type='checkbox' name='isDefault' value='1'{default_checked}> Make this the default connection</label>
{clear_row}
<button class='btn btn-primary' type='submit'>Save connection</button>{cancel}
</form>
<p class='empty'>Saving with the key field empty keeps the stored key;
Remove the stored key is the only action that deletes it. Leave the base
URL empty to use the preset's own address.</p>
{_health_forms(editing)}
<h3>Where to get a key</h3>
{_console_links()}"""
        stamp = f"{len(connections)} SAVED" if connections else "NONE YET"
        body = notice_block + keychain_block + listing + form
    return f"""<section class='card settings-card' id='connections'>
<div class='w-head'><h2>Connections</h2><span class='stamp'>{stamp}</span></div>
<p>Named model connections: pick a preset, paste its key, save. The key
lives in this machine's keychain; the desk keeps only a masked hint
(first three and last four characters) and never writes the key to any
file. Local presets (Ollama, LM Studio, vLLM) need no key at all.</p>
{body}
</section>"""


def _desk_check_section(desk_check: dict | None) -> str:
    """What the desk check last noticed, listed plainly.

    Read-only on this page: the check only detects, so a finding is its
    title and cause, never a button that pretends to know the fix.
    """
    desk_check = desk_check or {}
    findings = desk_check.get("findings") or []
    ran_ts = desk_check.get("ranTs")
    if ran_ts:
        last_run = (
            "Last run <span class='mono'>"
            + datetime.fromtimestamp(ran_ts).strftime("%Y-%m-%d %H:%M")
            + "</span>"
        )
        stamp = f"{len(findings)} TO CHECK" if findings else "ALL CLEAR"
    else:
        last_run = "Not run yet."
        stamp = "NOT RUN"
    if findings:
        rows = "".join(
            "<li class='settings-finding'>"
            f"<p class='finding-title'><b>{html.escape(finding['title'])}</b></p>"
            f"<p class='empty'>{html.escape(finding['cause'])}</p></li>"
            for finding in findings
        )
        findings_html = f"<ul class='findings'>{rows}</ul>"
    else:
        findings_html = "<p class='empty'>Everything the desk checks is fine.</p>"
    return f"""<section class='card settings-card' id='desk-check'>
<div class='w-head'><h2>Desk check</h2><span class='stamp'>{stamp}</span></div>
<p class='empty'>{last_run}</p>
{findings_html}
</section>"""


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
    audit_entries: list[dict] | None = None,
    audit_total: int | None = None,
    preferences: dict | None = None,
    preference_notice: str = "",
    desk_check: dict | None = None,
    connections: list[dict] | None = None,
    editing_connection: dict | None = None,
    keychain_available: bool = True,
    connections_notice: str = "",
) -> str:
    """The settings document: one card per concern, each stamped with
    the live state it actually reads (never a decoration)."""
    settings_values = settings_values or {}
    endpoint_status = endpoint_status or {"configured": False, "last": "never"}
    audit_entries = audit_entries or []
    audit_total = len(audit_entries) if audit_total is None else audit_total
    preferences = _stored_preferences() if preferences is None else preferences
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
        questions = (
            "<table class='rows'><thead><tr><th scope='col'>When</th>"
            "<th scope='col'>Kind</th><th scope='col'>What you asked</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        questions = "<p class='empty'>Nothing asked yet. Research and assistant questions land here, for you to see.</p>"

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
                "<article class='settings-skill'>"
                f"<div class='w-head'><h2 class='skill-name'>{html.escape(skill['name'])}</h2>"
                f"<span class='stamp'>{versions}</span></div>"
                f"<details><summary class='empty'>SKILL.md</summary><pre>{md}</pre></details>"
                f"{undo}</article>"
            )
        skills_html = "".join(blocks)
        skills_stamp = f"{len(skills)} ACTIVE"
    else:
        skills_html = "<p class='empty'>No skills yet. Accept a proposal in the inbox and it appears here with its history.</p>"
        skills_stamp = "NONE YET"

    desk_stamp = "SAMPLE DATA ON" if settings_values.get("sample_data") else "REAL DATA"
    endpoint_stamp = "CONFIGURED" if endpoint_status["configured"] else "NOT SET"
    mail_stamp = "MAIL ON" if settings_values.get("mail_enabled") else "MAIL OFF"
    registry = registry_status or {}
    registry_stamp = "READY" if registry.get("ok") else "NOT CONFIGURED"

    content = f"""<h1>Settings</h1>
<p>Everything this desk does, set from one page. A card's stamp is its
live state on this machine, read when the page rendered; a setting you
have never touched is the right setting.</p>
<div class='settings-stack'>
<section class='card settings-card' id='appearance'>
<div class='w-head'><h2>Appearance</h2><span class='stamp'>THIS BROWSER</span></div>
{_theme_tiles()}
<p class='empty'>The theme is kept in this browser and applies to every page of the desk.</p>
</section>

{_preferences_section(preferences, preference_notice)}

<section class='card settings-card' id='desk'>
<div class='w-head'><h2>Desk</h2><span class='stamp'>{desk_stamp}</span></div>
<div class='settings-block'>
{toggles_html}
</div>
<p class='empty'>Sample data fills a fresh desk with labelled example cards
and sample files (a workbook, a calendar file, header-only mail) so every
inbox action can be tried safely. Every cell it fills carries a Sample
data tag, and turning it off removes exactly what it added.</p>
</section>

{_agent_section(settings_values)}

{_connections_section(connections, editing_connection, keychain_available,
                      connections_notice)}

<section class='card settings-card' id='endpoint'>
<div class='w-head'><h2>Endpoint</h2><span class='stamp'>{endpoint_stamp}</span></div>
{endpoint_html}
</section>

<section class='card settings-card' id='sources'>
<div class='w-head'><h2>Sources</h2><span class='stamp'>{mail_stamp}</span></div>
<h3>Calendar source</h3>
<p>Calendar reading follows the OneDrive sync file by default. To pick
a different file, paste a path, upload the JSON by hand, or go back to
automatic, open the <a href="/walkthrough/calendar">calendar source page</a>.</p>
<h3>Mail source</h3>
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
</section>

{_desk_check_section(desk_check)}

<section class='card settings-card' id='registry'>
<div class='w-head'><h2>Plugin registry</h2><span class='stamp'>{registry_stamp}</span></div>
<p>The plugin registry is a local git checkout of the internal registry
repository. Installs are pinned by content hash and verified with the
same validator the registry's CI runs before anything executes. The
path is read from this setting first, then the AGENTDESK_REGISTRY
environment variable, then the app's own checkout.</p>
{_registry_section(registry_status)}
</section>

<section class='card settings-card' id='machine'>
<div class='w-head'><h2>Where the app opens</h2><span class='stamp'>LOOPBACK :{server_port}</span></div>
{_extra_hosts_section(extra_hosts, server_port)}
</section>

{_record_card(audit_entries, audit_total)}

<section class='card settings-card' id='skills'>
<div class='w-head'><h2>Skills</h2><span class='stamp'>{skills_stamp}</span></div>
{skills_html}
</section>

<section class='card settings-card' id='questions'>
<div class='w-head'><h2>Activity log</h2><span class='stamp'>LOCAL ONLY</span></div>
<p>Only what flows through the app: the asks you type into research and
the assistant. No keystrokes, no screen, and this list is yours.</p>
{questions}
</section>
</div>
"""
    return page_shell("Settings", "/settings", content, version, inbox_count=inbox_count)
