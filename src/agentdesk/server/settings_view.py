"""The settings page: toggles, connections, the visible parts.

Data sources, quiet hours and the notification budget are toggles or
small choices; endpoints and their keys live on the Connections card
(spec 018), and the endpoint card keeps the state line and the
presentation timeout, the one field its route still saves. A key is
secret: this module renders only masked hints, never a value. The
activity log, skills, audit export and the what-this-touches statement
are reachable from here. The preferences card is the only place the desk
is told what to assume about its reader; its values are read back from the
store on every render, never inferred.
"""

import html
from datetime import datetime

from agentdesk.insight.preferences import PreferenceStore, changed
from agentdesk.keys.presets import PRESETS, preset_for
from agentdesk.keys.resolve import JOB_LABELS
from agentdesk.keys.store import mask_key
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
    "recommendations": "Recommendations",
    "recommend_deadlines": "Deadline recommendations",
    "recommend_meetings": "Meeting prep recommendations",
    "recommend_horizon_days": "Look ahead",
    "recommend_model_rank": "Rank with my endpoint",
    "recommend_threshold": "Rank at or above",
}

ENDPOINT_HINT = (
    "<p>Endpoints and their keys are named connections now: configure "
    "them on the Connections card above. The legacy endpoint rows stay "
    "in the settings database as a read-only fallback, and the desk "
    "still answers on them when no connection serves a job.</p>"
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
    """The page-facing form of a saved key: state only, never the value.

    The last four characters appear only when keys.store.mask_key would
    show them (a key long enough to spare its middle): a short key is
    mostly tail, so it reads as "Set." with no tail at all.
    """
    key = (key or "").strip()
    if not key:
        return ""
    if mask_key(key) == "Set.":  # the short-key rule: no tail anywhere
        return "Set."
    return f"Set. Ends with {key[-4:]}."


def _endpoint_form(status: dict) -> str:
    """The reduced endpoint card body: the migration pointer, the
    read-only fallback statement, and the presentation timeout form,
    the one field the endpoint route still saves (spec 018 #234).

    The base URL, API key, model, research URL and research key fields
    retired to the Connections card. The timeout form is a plain form
    post, so it works with no script at all.
    """
    return (
        ENDPOINT_HINT
        + "<form method='post' action='/settings/endpoint/save' class='cardform'>"
        "<label class='empty' for='presentation-timeout'>Presentation timeout (seconds)</label>"
        f"<input id='presentation-timeout' type='text' name='presentationTimeout' "
        f"value='{_esc_timeout(status)}' placeholder='30' autocomplete='off'>"
        "<button class='btn btn-secondary' type='submit'>Save timeout</button>"
        "</form>"
        "<p class='empty'>How long presentation calls wait before the desk "
        "gives up, from 5 to 300 seconds; every other call keeps the "
        "10 second cap.</p>"
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
    elif key == "recommend_horizon_days":
        state = f"{value} days"
    elif key == "recommend_threshold":
        state = f"{value} or higher"
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


def _agent_section(settings_values: dict, agent_loop: dict | None) -> str:
    """The Agent section: autonomy, the loop cadence, and its last pass.

    Spec 016 section 9.3: the autonomy switch with the four ask-first
    classes in its help text, the Check every cycle, the last and next
    pass line with Run now, and the lastSteps table (step, ok, ms, note).
    Before the first pass the section carries the empty state; at Check
    every Off it says the automatic checks are off.
    """
    on = bool(settings_values.get("autonomy", True))
    stamp = "AUTONOMY ON" if on else "AUTONOMY OFF"
    loop = agent_loop or {}
    minutes = int(settings_values.get("agent_loop_minutes", 60) or 0)
    interval = _INTERVAL_LABELS.get(minutes, str(minutes))
    if minutes == 0:
        cadence = "<p class='empty'>Automatic checks are off.</p>"
    else:
        last_ts = loop.get("lastRunTs")
        next_ts = loop.get("nextRunTs")
        if last_ts:
            cadence = (f"<p class='empty'>Last pass <span class='mono'>"
                       f"{_agent_clock(last_ts)}</span>")
            if next_ts:
                cadence += (f" · next <span class='mono'>"
                            f"{_agent_clock(next_ts)}</span>")
            cadence += ".</p>"
        else:
            cadence = ("<p class='empty'>The agent hasn't run yet. It runs "
                       "about an hour after the app opens, or now.</p>")
    steps = loop.get("lastSteps") or []
    steps_html = _agent_steps_table(steps) if steps else ""
    return f"""<section class='card settings-card' id='agent'>
<div class='w-head'><h2>Agent</h2><span class='stamp'>{stamp}</span></div>
<div class='settings-block'>
{_toggle_button("autonomy", on, label="Act on its own")}
<div class='setting-row'><span>Check every</span>
<button class='btn btn-secondary' data-setting='agent_loop_minutes'>{interval}</button></div>
</div>
{cadence}
<form method="post" action="/api/agent-loop/run" class="cardform">
<input type="hidden" name="return_to" value="/settings#agent">
<button class="btn btn-secondary" type="submit">Run now</button>
</form>
{steps_html}
<h3>Recommendations</h3>
<div class='settings-block'>
{_toggle_button("recommendations", bool(settings_values.get("recommendations", True)))}
{_toggle_button("recommend_deadlines", bool(settings_values.get("recommend_deadlines", True)))}
{_toggle_button("recommend_meetings", bool(settings_values.get("recommend_meetings", True)))}
{_toggle_button("recommend_horizon_days", int(settings_values.get("recommend_horizon_days", 30)))}
{_toggle_button("recommend_model_rank", bool(settings_values.get("recommend_model_rank", True)))}
{_toggle_button("recommend_threshold", int(settings_values.get("recommend_threshold", 7)))}
</div>
<p class='empty'>On by default: a deadline in a saved fact becomes a waiting
card in Decisions, with the fact quoted and the day it was saved. Not now
keeps one gone for good, and removing or replacing the fact withdraws it.
With ranking on, the desk asks the company endpoint for a short reason and
keeps a card at or above the chosen score; a lower score rests until the
next morning.</p>
<p class='empty'>On by default: the desk acts on its own, and every change it
makes by itself is recorded on <a href="/settings/activity">Activity</a> with
an Undo button. It still asks first before sending email or messages,
deleting your data, uninstalling a plugin, or installing a new plugin.</p>
</section>"""


# The Check every cycle's button words, keyed by the setting's minutes.
_INTERVAL_LABELS = {60: "1 hour", 30: "30 min", 240: "4 hours", 0: "Off"}


def _agent_clock(ts) -> str:
    """An epoch stamp as the page's local wall-clock time, to the minute."""
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")


def _agent_steps_table(steps: list[dict]) -> str:
    """The last pass's steps: name, outcome, duration and one note each."""
    rows = "".join(
        "<tr><td class='mono'>" + html.escape(str(step.get("name", ""))) + "</td>"
        + ("<td>ok</td>" if step.get("ok") else "<td><b>failed</b></td>")
        + f"<td class='mono'>{html.escape(str(step.get('ms', 0)))}</td>"
        f"<td>{html.escape(str(step.get('note', '')))}</td></tr>"
        for step in steps
    )
    return ("<table class='rows'><thead><tr><th scope='col'>Step</th>"
            "<th scope='col'>Ok</th><th scope='col'>ms</th>"
            f"<th scope='col'>Note</th></tr></thead><tbody>{rows}</tbody></table>")


def _job_choices(connections: list[dict], selected: str) -> str:
    """One job's connection options, grouped by provider, with the job's
    bound connection preselected: the dropdown then tells the same truth
    the readback under the form tells, and an untouched save posts the
    binding back instead of silently unbinding it (spec 018 #235). The
    Not bound option is selected only when the job has no binding."""
    groups: dict[str, list[dict]] = {}
    for connection in connections:
        preset = preset_for(connection.get("provider", ""))
        name = preset.name if preset else str(connection.get("provider", ""))
        groups.setdefault(name, []).append(connection)
    options = [
        "<option value=''"
        + (" selected" if not selected else "")
        + ">Not bound (default connection or environment)</option>"
    ]
    for provider, rows in groups.items():
        items = "".join(
            f"<option value='{html.escape(row['id'], quote=True)}'"
            + (" selected" if row["id"] == selected else "")
            + f">{html.escape(str(row.get('label', '')))}</option>"
            for row in rows
        )
        options.append(
            f"<optgroup label='{html.escape(provider)}'>{items}</optgroup>")
    return "".join(options)


def _jobs_section(bindings: list[dict] | None,
                  connections: list[dict] | None) -> str:
    """The per-job picker: which connection and model serves which job.

    One plain form per job (the house rule: the page works with no
    script at all), the connection select grouped by provider and
    preselected to the job's own binding, and the model offered as a
    text input with a datalist of every cached model, so choosing from
    the cached list and typing by hand are the same control. The current
    binding reads back under each row, so the page always states what
    serves what, and the select shows the same state.
    """
    if bindings is None or connections is None:
        body = (
            "<div class='alert'><p>The connections store is not available,"
            " so jobs cannot be bound here.</p></div>"
        )
        stamp = "UNAVAILABLE"
    else:
        by_job = {binding["job"]: binding for binding in bindings}
        by_id = {connection["id"]: connection for connection in connections}
        cached = []
        for connection in connections:
            for model in connection.get("models") or []:
                if model not in cached:
                    cached.append(model)
        datalist = "".join(
            f"<option value='{html.escape(str(model), quote=True)}'></option>"
            for model in cached)
        forms = []
        for job in ("default", "assistant", "agents", "presentations",
                    "memory", "insights", "research-web"):
            binding = by_job.get(job)
            selected = str(binding.get("connectionId") or "") if binding else ""
            model = str(binding.get("model") or "") if binding else ""
            choices = _job_choices(connections, selected)
            if selected and selected in by_id:
                current = (
                    f"<span class='empty'>Serves through"
                    f" <b>{html.escape(str(by_id[selected].get('label', '')))}</b>"
                    + (f", model <span class='mono'>{html.escape(model)}</span>"
                       if model else "")
                    + ".</span>")
            elif binding:
                current = "<span class='empty'>Bound to a connection that is gone.</span>"
            else:
                current = "<span class='empty'>Unbound: the default binding, the single saved connection or the environment serves it.</span>"
            list_id = f"job-{job}-models"
            forms.append(f"""<div class='settings-block'>
<form method='post' action='/api/bindings' class='cardform job-form'>
<input type='hidden' name='job' value='{job}'>
<label class='empty' for='job-{job}-connection'><b>{JOB_LABELS[job]}</b></label>
<select id='job-{job}-connection' name='connectionId'>{choices}</select>
<label class='empty' for='job-{job}-model'>Model</label>
<input id='job-{job}-model' type='text' name='model' list='{list_id}'
 value='{html.escape(model, quote=True)}' autocomplete='off'>
<datalist id='{list_id}'>{datalist}</datalist>
<button class='btn btn-secondary' type='submit'>Save the {job} job</button>
</form>
{current}
</div>""")
        bound = sum(1 for job in by_job)
        stamp = f"{bound} BOUND" if bound else "NONE BOUND"
        body = (
            "<p class='empty'>Saving with Not bound chosen removes the job's"
            " binding; the default binding, a single saved connection or the"
            " environment then serves it.</p>"
            + "".join(forms)
        )
    return f"""<section class='card settings-card' id='jobs'>
<div class='w-head'><h2>Jobs</h2><span class='stamp'>{stamp}</span></div>
<p>Assign the desk's jobs to connections: the assistant on a personal
key, presentations on a work key, web research on a third. Every model
call asks one resolution hub: the job's binding here, then the default
binding, then the single enabled connection, then the environment. Each
model field is picked from the cached lists or typed.</p>
{body}
</section>"""


def render_connection_delete_warning(connection: dict, jobs: list[str],
                                     version: str,
                                     migrated: bool = False) -> str:
    """The no-JS confirmation page a bound connection's first delete post
    answers with: the jobs named before anything lands, one form that
    posts the same delete with confirm, and one link back.

    A migrated connection (spec 018 #234) gets the honest variant: its
    keychain entry survives and the connection returns on the next
    start, because the delete is the recovery path."""
    connection_id = html.escape(str(connection.get("id", "")), quote=True)
    label = html.escape(str(connection.get("label", "")))
    named = ", ".join(html.escape(job) for job in jobs)
    if migrated:
        consequence = (
            f"<p><b>{label}</b> came from the upgrade migration (the legacy"
            " endpoint rows). Deleting it removes the connection and those"
            " bindings, but the key stays in this machine's keychain, and"
            " on the next start the migration step sees the legacy rows and"
            " puts the connection back with its key and its jobs: nothing"
            " needs retyping. The jobs you left bound to your own"
            " connections stay exactly as they are.</p>"
        )
    else:
        consequence = (
            f"<p><b>{label}</b> is bound to the <b>{named}</b> job{'s' if len(jobs) != 1 else ''}."
            " Deleting it removes the connection, its keychain entry and those"
            " bindings; the jobs fall back to the default binding, the single"
            " remaining connection, or the environment, and a job with none of"
            " those answers with a named unbound error instead of a silent"
            " one.</p>"
        )
    content = f"""<h1>Delete a connection that serves jobs</h1>
{consequence}
<form method='post' action='/api/connections/{connection_id}/delete' class='cardform'>
<input type='hidden' name='confirm' value='1'>
<button class='btn btn-danger' type='submit'>Delete {label} and unbind {named}</button>
</form>
<p><a class='btn btn-secondary' href='/settings'>Keep it</a></p>"""
    return page_shell("Connections", "/settings", content, version)


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
            f"<td class='mono conn-url'>{base}</td>"
            f"<td><span class='conn-status conn-{status}'>{status}</span>"
            f"{cause_line}{when}{models_line}</td>"
            f"<td class='conn-actions'><form method='post' action='/api/connections/{connection_id}/test'"
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


def _provider_select(selected: str) -> str:
    """The provider picker: one native select, the presets grouped.

    Three optgroups in order: the hosted providers under their plain
    names, the local servers whose labels carry the discovery fact
    (this machine, no key needed), and Custom last. The hosted labels
    stay bare because the console disclosure below the form answers
    where keys come from. Each option carries its preset's default base
    URL as data, so the script can fill the base field on choice;
    without script the server fills the same default when the field
    arrives empty. The saved provider's option carries selected on the
    edit form, the first preset on the create form, exactly where the
    checked radio used to sit (spec 019 #263)."""
    groups: dict[str, list[str]] = {
        "Hosted providers": [],
        "Local servers, no key needed": [],
        "Custom": [],
    }
    for preset in PRESETS:
        chosen = " selected" if preset.id == selected else ""
        label = preset.name
        if preset.local:
            label += " (this machine, no key needed)"
            group = "Local servers, no key needed"
        elif preset.id == "custom":
            group = "Custom"
        else:
            group = "Hosted providers"
        groups[group].append(
            f"<option value='{preset.id}'{chosen}"
            f" data-base='{html.escape(preset.base_url, quote=True)}'>"
            f"{html.escape(label)}</option>")
    options = "".join(
        f"<optgroup label='{html.escape(group)}'>{''.join(items)}</optgroup>"
        for group, items in groups.items())
    return (
        "<label class='empty' for='conn-provider'>Provider</label>"
        "<select id='conn-provider' name='provider'>" + options + "</select>"
    )


def _console_links() -> str:
    """One deep-link per hosted preset, folded into a native disclosure:
    the summary names the block, the anchors stay plain links, and the
    open and close work with no script at all."""
    links = "".join(
        f"<a class='btn btn-secondary' href='{preset.console_url}'>"
        f"{html.escape(preset.name)}</a>"
        for preset in PRESETS if preset.console_url
    )
    return (
        "<details class='console-links'>"
        "<summary>Where to get a key</summary>"
        f"<div class='settings-links'>{links}</div>"
        "</details>"
    )


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
    masked hints are printed, and the provider select and console
    deep-links answer the two first-run questions with no script at
    all. The edit
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
{_provider_select(selected)}
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


def _finding_action(finding: dict) -> str:
    """The one action a finding offers: Fix it, Open, Review card, or nothing.

    An automatic finding's button posts to the fix endpoint, so it works
    without JavaScript; a link finding opens the page where the user connects
    the source, and an ask finding points at the inbox card the check made.
    """
    fix = finding.get("fix")
    finding_id = html.escape(str(finding.get("id", "")), quote=True)
    if fix == "auto":
        label = html.escape(str(finding.get("fixLabel") or "Fix it"))
        return (
            "<form method='post' action='/api/desk-check/fix' class='finding-fix'>"
            f"<input type='hidden' name='id' value='{finding_id}'>"
            f"<button class='btn btn-secondary' type='submit'>{label}</button>"
            "</form>"
        )
    if fix == "link" and finding.get("href"):
        label = html.escape(str(finding.get("fixLabel") or "Open"))
        href = html.escape(str(finding["href"]), quote=True)
        return f"<a class='btn btn-secondary' href='{href}'>{label}</a>"
    if fix == "ask":
        return "<a class='btn btn-secondary' href='/inbox'>Review card</a>"
    return ""


def _update_section(values: dict, update: dict) -> str:
    """The update share, its switches, and what the last check found.

    Everything here is a plain form post, so the section still works with no
    script: the share path, the two switches, and Check now.
    """
    channel = str(values.get("update_channel") or "")
    available = update.get("available") or ""
    auto = bool(values.get("auto_update"))
    last_result = str(update.get("lastResult") or "none")
    cause = str(update.get("lastCause") or "")
    check_ts = update.get("lastCheckTs")
    checked = (
        datetime.fromtimestamp(float(check_ts)).strftime("%Y-%m-%d %H:%M")
        if check_ts else "never"
    )
    if not channel:
        line = "No update share is set."
    elif last_result in ("channel-unreadable", "health-failed") and cause:
        line = cause
    elif last_result == "channel-unreadable":
        line = "The update share couldn't be read."
    elif available and not auto:
        line = f"Version {available} is on the share. Install updates is off."
    elif available:
        line = f"Version {available} is on the share."
    else:
        line = "No newer version is on the share."
    result_line = {
        "none": "Nothing staged.",
        "up-to-date": "The share has no newer version.",
        "staged": f"Version {available} is staged and ready.",
        "health-failed": "The last staged version failed its check.",
        "applied": "The last staged version is running.",
        "rolled-back": "The last version went back to the one before it.",
        "channel-unreadable": "The update share couldn't be read.",
    }.get(last_result, "Nothing staged.")
    return f"""<section class='card settings-card' id='updates'>
<div class='w-head'><h2>Updates</h2><span class='stamp'>{html.escape(last_result.upper())}</span></div>
<p>Updates come from a folder that IT publishes to. The desk reads only
that folder, checks every file against the manifest, and never installs a
version that fails its own check. It never restarts by itself.</p>
<form method='post' action='/settings/update/channel' class='cardform'>
<label class='empty' for='update-channel'>Update share</label>
<input id='update-channel' type='text' name='path' value="{html.escape(channel, quote=True)}" placeholder="//fileserver/AgentDesk/stable" autocomplete='off'>
<button class='btn btn-secondary' type='submit'>Save folder</button>
</form>
<div class='settings-block'>
{_toggle_button("auto_update", auto, "Install updates")}
{_toggle_button("auto_update_plugins", bool(values.get("auto_update_plugins")), "Update plugins too")}
</div>
<p class='empty'>Off until IT approves. When on, the desk installs only
versions that pass their check, and keeps the previous version. Plugin
updates are not installed automatically in this release.</p>
<p>{html.escape(line)}</p>
<p class='empty'>Current version <span class='mono'>{html.escape(str(update.get("current") or ""))}</span>.
Last check <span class='mono'>{html.escape(checked)}</span>. {html.escape(result_line)}</p>
<form method='post' action='/api/update/check' class='cardform'>
<input type='hidden' name='return_to' value='/settings#updates'>
<button class='btn btn-secondary' type='submit'>Check now</button>
</form>
</section>"""


def _desk_check_section(desk_check: dict | None) -> str:
    """What the desk check last noticed, each finding with its one action.

    A finding the desk is sure about offers Fix it; a link finding opens the
    page where the source is connected; an ask finding points at its inbox
    card; anything else is title and cause only.
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
            f"<p class='empty'>{html.escape(finding['cause'])}</p>"
            f"{_finding_action(finding)}</li>"
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
    mail_self_address: str = "",
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
    bindings: list[dict] | None = None,
    keychain_available: bool = True,
    connections_notice: str = "",
    agent_loop: dict | None = None,
    update: dict | None = None,
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

    questions = audit_view.questions_table(activity_entries[-30:])

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
                f"<button class='btn btn-secondary btn-start' "
                f"data-skill-undo='{html.escape(str(skill['id']))}'>"
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

{_agent_section(settings_values, agent_loop)}

{_connections_section(connections, editing_connection, keychain_available,
                      connections_notice)}

{_jobs_section(bindings, connections)}

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
<form method="post" action="/settings/mail/address" class="cardform">
<label class="empty" for="mail-self-address">Your mail address</label>
<input id="mail-self-address" type="text" name="address" value="{html.escape(mail_self_address, quote=True)}" placeholder="you@company.com" autocomplete="off">
<button class="btn btn-secondary" type="submit">Save address</button>
</form>
<p class="empty">The address is how the desk recognises your own replies (the
address inside the From header), so threads you already answered stop
producing follow-up cards. With no address set, self-detection is simply
off: the digest works, follow-up cards are not filed.</p>
<p class="empty">With the toggle off, nothing is read: no watcher runs and no mail cards are created. <a href="/mail">Open the mail page</a> to see the digest once it is on.</p>
</section>

{_desk_check_section(desk_check)}

{_update_section(settings_values, update or {})}

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
