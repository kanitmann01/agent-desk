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
    "endpoint_enabled": "AI calls (assistant and research)",
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
    "recommend_model_rank": "Rank with my AI",
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


def _learned_section(document: dict | None, settings_values: dict) -> str:
    """What the desk learned about you (spec 016 section 9.3), under the
    stated preferences card.

    The learned topics and lines come from profile.learned.json, each
    with its provenance and a Remove button that posts to the JSON
    route (a no-JS post redirects back here). Every value here is
    server-rendered from the stores, never guessed. The two learning
    switches sit under Advanced and memory itself has its own card in the
    Memory section (spec 022), so this card is only what was learned.
    """
    values = settings_values or {}
    rows = []
    for topic in (document or {}).get("focusTopics") or []:
        name = html.escape(str(topic.get("topic", "")), quote=True)
        asks = topic.get("learnedFrom", {}).get("asks")
        provenance = f"Learned from {asks} asks" if isinstance(asks, int) else "Learned"
        rows.append(
            f"<div class='setting-row'><span>{name} "
            f"<span class='empty'>{html.escape(provenance)}</span></span>"
            "<form method='post' action='/api/profile/learned/remove' class='inlineform'>"
            f"<input type='hidden' name='topic' value='{name}'>"
            "<input type='hidden' name='return_to' value='/settings#learned'>"
            "<button class='btn btn-secondary' type='submit'>Remove</button>"
            "</form></div>"
        )
    for entry in (document or {}).get("entries") or []:
        text = html.escape(str(entry.get("text", "")), quote=True)
        stamp = entry.get("ts")
        when = datetime.fromtimestamp(stamp).strftime("%d %b %Y") \
            if isinstance(stamp, (int, float)) else "activity"
        rows.append(
            f"<div class='setting-row'><span>{text} "
            f"<span class='empty'>Learned from activity on {html.escape(when)}</span></span>"
            "<form method='post' action='/api/profile/learned/remove' class='inlineform'>"
            f"<input type='hidden' name='id' value='{html.escape(str(entry.get('id', '')), quote=True)}'>"
            "<input type='hidden' name='return_to' value='/settings#learned'>"
            "<button class='btn btn-secondary' type='submit'>Remove</button>"
            "</form></div>"
        )
    if rows:
        learned_html = "".join(rows)
    else:
        learned_html = (
            "<p class='empty'>Nothing learned yet. The desk learns from "
            "what you ask it; nothing here is guessed.</p>"
        )
    return f"""<section class='card settings-card' id='learned'>
<div class='w-head'><h2>What the desk learned about you</h2><span class='stamp'>{len(rows)} LEARNED</span></div>
<p>The desk learns only from what you ask it: a topic shows up here when
several of your questions named the same thing, and a line only when a
review of your recent asks cites them. Each line lists where it came
from, and removing one keeps it from coming back.</p>
{learned_html}
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
<a class='btn btn-secondary' href="/capabilities">Computer check (for IT)</a>
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
    every Off it says the automatic checks are off. The recommendation
    switches are not here: they are rendered once, on the Desk card (spec
    022).
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
    chosen connection preselected: the dropdown then tells the same truth
    the readback under the form tells, and an untouched save posts the
    choice back instead of silently clearing it (spec 018 #235). "Same as
    everything else" is selected only when the place has no choice of its
    own (spec 022: the page never says job, binding or bound)."""
    groups: dict[str, list[dict]] = {}
    for connection in connections:
        preset = preset_for(connection.get("provider", ""))
        name = preset.name if preset else str(connection.get("provider", ""))
        groups.setdefault(name, []).append(connection)
    options = [
        "<option value=''"
        + (" selected" if not selected else "")
        + ">Same as everything else</option>"
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
                  connections: list[dict] | None, ai: dict) -> str:
    """What uses your AI: one sentence on what serves everything, and,
    behind a disclosure, one form per place the desk uses a model.

    The forms are the per-place picker of spec 018 (#235), in the words of
    spec 022: one plain form per place, so the page works with no script;
    the connection select grouped by provider and preselected to the
    place's own choice; the model offered as a text input with a datalist
    of every cached model, so choosing from the cached list and typing by
    hand are the same control. What serves each place reads back under its
    row, so the page always states what answers what. `ai` is the one
    sentence's subject: whether an AI is saved, its label and its model.
    """
    if bindings is None or connections is None:
        body = (
            "<div class='alert'><p>The connections store is not available,"
            " so this cannot be changed here.</p></div>"
        )
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
                    f"<span class='empty'>Answers through"
                    f" <b>{html.escape(str(by_id[selected].get('label', '')))}</b>"
                    + (f", model <span class='mono'>{html.escape(model)}</span>"
                       if model else "")
                    + ".</span>")
            elif binding:
                current = ("<span class='empty'>The AI it used was removed, so it"
                           " answers like everything else.</span>")
            else:
                current = "<span class='empty'>Answers like everything else.</span>"
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
<button class='btn btn-secondary' type='submit'>Save</button>
</form>
{current}
</div>""")
        body = "".join(forms)
    if ai.get("connected"):
        serves = (f"<b>{html.escape(str(ai.get('label', '')))}</b> answers everything"
                  + (f" with <span class='mono'>{html.escape(str(ai.get('model', '')))}</span>"
                     if ai.get("model") else "")
                  + ". Change one of these only if you want to, for example web"
                    " research on a different key.")
    else:
        serves = "No AI key is saved yet. Add one above first."
    return f"""<section class='card settings-card' id='jobs'>
<div class='w-head'><h2>What uses your AI</h2></div>
<p>{serves}</p>
<details class='settings-disclosure'><summary>Use a different model for one of these</summary>
<p class='empty'>Each model field is picked from the cached lists or typed.
Leave "Same as everything else" to use the AI that serves the rest.</p>
{body}
</details>
</section>"""


def joined_job_labels(jobs: list[str]) -> str:
    """Join the plain names of what an AI answers: one reads alone, two
    read "A and B", three or more read "A, B and C" (spec 022's plain
    words, the same join on the warning page and in the JSON answer)."""
    names = [JOB_LABELS[job] for job in jobs]
    if len(names) < 2:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def render_connection_delete_warning(connection: dict, jobs: list[str],
                                     version: str,
                                     migrated: bool = False) -> str:
    """The no-JS confirmation page a serving connection's first delete
    post answers with: what it answers named before anything lands, one
    form that posts the same delete with confirm, and one link back.

    A migrated connection (spec 018 #234) gets the honest variant: its
    keychain entry survives and the connection returns on the next
    start, because the delete is the recovery path."""
    connection_id = html.escape(str(connection.get("id", "")), quote=True)
    label = html.escape(str(connection.get("label", "")))
    named = html.escape(joined_job_labels(jobs))
    if migrated:
        consequence = (
            f"<p><b>{label}</b> came from an older version of the app."
            " Deleting it removes the connection, but its key stays in this"
            " computer's keychain, and the next time the app starts it comes"
            " back with its key: nothing needs retyping. What your other"
            " saved AIs answer stays exactly as it is.</p>"
        )
    else:
        consequence = (
            f"<p><b>{label}</b> answers <b>{named}</b>."
            " Deleting it removes the connection and its key from this"
            " computer. Those stop answering until you save another"
            " key.</p>"
        )
    content = f"""<h1>Delete an AI that is in use</h1>
{consequence}
<form method='post' action='/api/connections/{connection_id}/delete' class='cardform'>
<input type='hidden' name='confirm' value='1'>
<button class='btn btn-danger' type='submit'>Delete {label} anyway</button>
</form>
<p><a class='btn btn-secondary' href='/settings'>Keep it</a></p>"""
    return page_shell("Connections", "/settings", content, version)


def _connection_rows(connections: list[dict]) -> str:
    """The saved-connections table: label, preset, masked key, base URL,
    status badge with its inline cause, default star, Test, edit and
    delete. Each row names the model the connection sends, or "(default)"
    when it has none (spec 022). A raw key never reaches this markup; the
    masked hint is the only key-shaped thing on the page, and the badge
    state renders from the row alone, so the page works with no script at
    all."""
    rows = []
    for c in connections:
        preset = preset_for(c.get("provider", ""))
        preset_name = preset.name if preset else str(c.get("provider", ""))
        label = html.escape(str(c.get("label", "")))
        star = " <span aria-label='default connection'>&#9733;</span>" if c.get("isDefault") else ""
        masked = html.escape(str(c.get("maskedKey", "") or ""))
        key_cell = f"<span class='mono'>{masked}</span>" if masked else \
            "<span class='empty'>no key</span>"
        model = html.escape(str(c.get("model") or "(default)"))
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
            f"<td><b>{label}</b>{star}"
            f"<br><span class='empty'>Model: {model}</span></td>"
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
    checked radio used to sit (spec 019 #263). Each option also carries
    the preset's default model as data, so the script can fill the model
    field on the same choice."""
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
            f" data-base='{html.escape(preset.base_url, quote=True)}'"
            f" data-model='{html.escape(preset.default_model, quote=True)}'>"
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


def _model_field(value: str, models: list) -> str:
    """The connection form's Model field: the model every call on this
    connection sends (spec 022).

    A select over the models the save-time check listed when there are
    any, the saved model selected and "default" (no model) always offered;
    a text field otherwise, able to carry any name. A model the listing
    does not include stays as its own option, so saving another change
    never swaps it. An empty value reads "default", the word the saved
    rows use. On a new connection the field starts empty and the script
    fills the selected preset's default; without script the server saves
    that default when the field arrives empty.
    """
    label = "<label class='empty' for='conn-model'>Model</label>"
    if not models:
        return (
            label
            + "<input id='conn-model' type='text' name='model'"
            f" value='{html.escape(value, quote=True)}'"
            " placeholder='default' autocomplete='off'>"
        )
    unlisted = [value] if value and value not in models else []
    options = [f"<option value=''{'' if value else ' selected'}>default</option>"]
    for model in unlisted + list(models):
        name = html.escape(str(model))
        chosen = " selected" if str(model) == value else ""
        options.append(
            f"<option value='{html.escape(str(model), quote=True)}'{chosen}>{name}</option>")
    return label + "<select id='conn-model' name='model'>" + "".join(options) + "</select>"


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
            # With nothing saved the status line above the card already says
            # what to do, so the card goes straight to the form.
            listing = ""
        if editing is not None:
            heading = "Edit this AI"
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
            model_value = str(editing.get("model") or "")
            model_options = list(editing.get("models") or [])
        else:
            heading = "Add an AI"
            action = "/api/connections"
            label_value = ""
            base_value = ""
            selected = PRESETS[0].id
            key_placeholder = "Paste the key from your provider"
            headers_text = ""
            default_checked = ""
            clear_row = ""
            cancel = ""
            model_value = ""
            model_options = []
        # Three fields are all a person needs to add an AI: provider, key
        # and model. The rest sit behind "More options" (spec 022). An
        # address is the one field a provider without one of its own cannot
        # do without, so for Custom it stays outside the disclosure. An edit
        # shows every field, as before.
        chosen_preset = preset_for(selected)
        needs_address = not (chosen_preset and chosen_preset.base_url)
        address = (
            "<label class='empty' for='conn-base'>Address (base URL)</label>"
            f"<input id='conn-base' type='text' name='baseUrl' value='{base_value}'"
            " placeholder='https://your-gateway/v1' autocomplete='off'>")
        name_field = (
            "<label class='empty' for='conn-label'>Name (optional: the"
            " provider's own name when left empty)</label>"
            f"<input id='conn-label' type='text' name='label' value='{label_value}'"
            f" placeholder='{html.escape(chosen_preset.name if chosen_preset else 'My AI', quote=True)}'"
            " autocomplete='off'>")
        rest = (
            "<label class='empty' for='conn-headers'>Extra headers (corporate"
            " gateways, one Name: Value per line)</label>"
            f"<textarea id='conn-headers' name='headers' rows='2'"
            f" placeholder='X-Gateway: corp'>{headers_text}</textarea>"
            "<label class='empty'><input type='checkbox' name='isDefault'"
            f" value='1'{default_checked}> Use this AI for everything by default</label>"
            f"{clear_row}")
        if editing is None:
            shown_address = address if needs_address else ""
            optional = (f"<details class='settings-disclosure' id='conn-more'>"
                        "<summary>More options</summary>"
                        + (name_field if needs_address else address + name_field)
                        + rest + "</details>")
        else:
            shown_address = address
            optional = name_field + rest
        # Only an edit has a stored key to keep or remove, so only it states
        # the rule.
        keep_rule = (
            "" if editing is None else
            "<p class='empty'>Saving with the key field empty keeps the stored"
            " key; Remove the stored key is the only action that deletes it.</p>")
        form = f"""<h3>{heading}</h3>
<form method='post' action='{action}' class='cardform' id='connection-form'>
{_provider_select(selected)}
<label class='empty' for='conn-key'>API key</label>
<input id='conn-key' type='password' name='apiKey' placeholder='{key_placeholder}' autocomplete='new-password'>
<label class='empty' for='conn-key-show'><input type='checkbox' id='conn-key-show' data-key-reveal> Show the key while typing</label>
{_model_field(model_value, model_options)}
{shown_address}
{optional}
<button class='btn btn-primary' type='submit'>Save</button>{cancel}
</form>
{keep_rule}
<p class='empty'>The key is kept in this computer's keychain. The desk keeps
a masked hint (first three and last four characters) and never writes the
key to a file. Local servers (Ollama, LM Studio, vLLM) need no key.</p>
{_health_forms(editing)}
{_console_links()}"""
        stamp = f"{len(connections)} SAVED" if connections else "NONE SAVED"
        body = notice_block + keychain_block + listing + form
    return f"""<section class='card settings-card' id='connections'>
<div class='w-head'><h2>Your AI</h2><span class='stamp'>{stamp}</span></div>
<p>Pick who you have a key from, paste the key and save. One saved AI
answers everything; add a second only if you want a different one for
something.</p>
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


# The six Settings sections in bar order (spec 022). The key is the
# wrapper's data-settings-section and, where no card inside needs that id,
# the wrapper's own id; the address is what the bar links to. Preferences
# links to its card's own anchor, because a section and its card cannot
# share one id. Activity is the existing page of the same name.
SETTINGS_SECTIONS = (
    ("ai", "Your AI", "#ai"),
    ("tools", "Your tools", "#tools"),
    ("memory", "Memory", "#memory"),
    ("preferences", "Preferences", "#preferences"),
    ("activity", "Activity", "/settings/activity"),
    ("advanced", "Advanced", "#advanced"),
)
_SECTION_TITLES = {key: title for key, title, _href in SETTINGS_SECTIONS}


def _settings_section(key: str, cards_html: str) -> str:
    """One Settings section: a group of cards the section bar shows alone.

    The wrapper carries data-settings-section for the script and its own id
    unless a card inside needs that id (Preferences keeps its card's). With
    script one section shows at a time; without it every section renders,
    each under its own title, so the page is its own index. The title is a
    label, not a heading: the page keeps one display heading and its cards
    as the second level.
    """
    wrapper_id = "" if key == "preferences" else f" id='{key}'"
    return (f"<div class='settings-section' data-settings-section='{key}'{wrapper_id}>"
            f"<p class='settings-section-title'>{_SECTION_TITLES[key]}</p>"
            f"{cards_html}</div>")


def _settings_bar() -> str:
    """The section bar: six entries, one address each (Activity is a page)."""
    links = "".join(
        f"<a href='{href}'>{title}</a>" for _key, title, href in SETTINGS_SECTIONS)
    return ("<nav class='settings-bar' data-settings-bar"
            " aria-label='Settings sections'>" + links + "</nav>")


def _tools_section(excel_status: dict | None, calendar_status: dict | None,
                   settings_values: dict, mail_folder: str,
                   mail_self_address: str) -> str:
    """Your tools: the workbook, the calendar and the mail folder, each
    with its live state and one action (spec 022).

    Every state is the source's own status, read when the page rendered.
    The workbook's one action is the picker, which needs script (hidden
    without it, so the page never shows a control that cannot work); the
    calendar's is its setup page; the mail's is its on/off switch. The
    folder and address forms fold into a disclosure.
    """
    excel_status = excel_status or {}
    calendar_status = calendar_status or {}
    values = settings_values or {}
    workbook_path = str(excel_status.get("path") or "")
    if workbook_path:
        name = html.escape(workbook_path.replace("\\", "/").rsplit("/", 1)[-1])
        rows = excel_status.get("rowsSeen")
        workbook_state = f"Watching <b>{name}</b>" + (
            f", {rows} rows" if isinstance(rows, int) else "")
        workbook_verb = "Change"
    else:
        workbook_state = "No sales workbook is connected."
        workbook_verb = "Open a workbook"
    if calendar_status.get("state") in (None, "empty"):
        calendar_state = "No calendar is connected."
        calendar_verb = "Set up"
    else:
        calendar_state = "Reading your calendar."
        calendar_verb = "Change"
    mail_on = bool(values.get("mail_enabled"))
    folder = html.escape(mail_folder, quote=True)
    mail_state = ("On. Only the headers of the .eml files in the folder are read."
                  if mail_on else "Off. Nothing is read.")
    mail_switch = _toggle_button("mail_enabled", mail_on)
    return f"""<section class='card settings-card' id='sources'>
<div class='w-head'><h2>Workbook, calendar and mail</h2></div>
<div class='settings-block'>
<div class='setting-row'><span>Workbook<br><span class='empty'>{workbook_state}</span></span>
<button class='btn btn-secondary needs-script' data-pick type='button'>{workbook_verb}</button></div>
<div class='setting-row'><span>Calendar<br><span class='empty'>{calendar_state}</span></span>
<a class='btn btn-secondary' href='/walkthrough/calendar'>{calendar_verb}</a></div>
<div class='setting-row'><span>Mail<br><span class='empty'>{mail_state}</span></span>
{mail_switch}</div>
</div>
<p class='alert' id='pick-note' hidden></p>
<details class='settings-disclosure'><summary>Mail folder and your address</summary>
<p>The desk reads one folder of exported .eml files and only their headers
(From, To, Cc, Subject, Date, Message-ID, In-Reply-To). Bodies are
discarded as the file is read and nothing is sent to any model. Reply
drafts you accept are written to the local outbox folder for you to send
yourself. With the switch off, no watcher runs and no mail cards are
created. <a href="/mail">Open the mail page</a> to see the digest once it is on.</p>
<form method="post" action="/settings/mail/folder" class="cardform">
<label class="empty" for="mail-folder">Mail folder</label>
<input id="mail-folder" type="text" name="folder" value="{folder}" placeholder="C:/Users/you/mail-exports" autocomplete="off">
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
</details>
</section>"""


def _memory_card(settings_values: dict) -> str:
    """The Memory card: how memory works in plain words, the learning
    switches and the way to forget everything (spec 022).

    Every switch is server-rendered from the store. "Forget everything"
    posts to the Memory page's own form, which asks once before it acts,
    so a click here can never delete anything on its own.
    """
    values = settings_values or {}
    switches = "".join(
        _toggle_button(key, values.get(key), label)
        for key, label in (
            ("memory_auto_approve", "Learn automatically"),
            ("memory_capture_assistant", "Learn from Assistant conversations"),
            ("memory_capture_research", "Learn from Research questions"),
        )
    )
    return f"""<section class='card settings-card' id='memory-settings'>
<div class='w-head'><h2>Memory</h2><span class='stamp'>ON THIS COMPUTER</span></div>
<p>Agent Desk remembers facts about you and your work, such as who owns a
renewal or when a deadline falls, and uses them when you ask a question.
It learns as you work: from what you tell the Assistant and from what you
ask in Research, and only while the switches below are on. Everything it
holds is on the Memory page with where it came from, and you can edit or
forget any of it.</p>
<div class='settings-block'>
{switches}
</div>
<p class='empty'>With Learn automatically on, a fact is saved as soon as the
desk notices it. Off, it waits for you in the inbox.</p>
<div class='settings-links'>
<a class='btn btn-secondary' href='/memory'>Open the Memory page</a>
</div>
<form method='post' action='/memory/forget-all' class='cardform'>
<button class='btn btn-secondary' type='submit'>Forget everything</button>
</form>
<p class='empty'>Forgetting cannot be undone, so the desk asks you to confirm
on the Memory page first.</p>
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
    learned: dict | None = None,
    desk_check: dict | None = None,
    connections: list[dict] | None = None,
    editing_connection: dict | None = None,
    bindings: list[dict] | None = None,
    keychain_available: bool = True,
    connections_notice: str = "",
    agent_loop: dict | None = None,
    update: dict | None = None,
    curator_last_run: str | None = None,
    ai: dict | None = None,
    excel_status: dict | None = None,
    calendar_status: dict | None = None,
) -> str:
    """The settings document: six sections, one card per concern, each
    stamped with the live state it actually reads (never a decoration).

    Your AI comes first (spec 022): the key form is the first thing on the
    page. `ai` is what serves the desk (connected, label, model), read by
    the same resolution hub every model call uses; `excel_status` and
    `calendar_status` are the sources' own status for the Your tools rows.
    """
    settings_values = settings_values or {}
    endpoint_status = endpoint_status or {"configured": False, "last": "never"}
    audit_entries = audit_entries or []
    audit_total = len(audit_entries) if audit_total is None else audit_total
    preferences = _stored_preferences() if preferences is None else preferences
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
            made_by = ("Made by the desk" if skill.get("created_by") == "agent"
                       else "Made by you")
            state_word = {"active": "Active", "stale": "Stale",
                          "archived": "Archived"}.get(str(skill.get("state", "active")),
                                                      "Active")
            skill_id = html.escape(str(skill["id"]), quote=True)
            pinned = bool(skill.get("pinned"))
            pin_form = (
                f"<form method='post' action='/skills/{skill_id}/pin' class='cardform'>"
                "<input type='hidden' name='return_to' value='/settings#skills'>"
                f"<input type='hidden' name='pinned' value='{0 if pinned else 1}'>"
                f"<button class='btn btn-secondary' type='submit'>"
                f"{'Unpin' if pinned else 'Pin'}</button></form>"
            )
            improve = ""
            if skill.get("created_by") == "agent" and not pinned:
                improve = (
                    f"<form method='post' action='/skills/{skill_id}/feedback'"
                    " class='cardform'>"
                    "<input type='hidden' name='return_to' value='/settings#skills'>"
                    f"<label class='empty' for='skill-{skill_id}-improve'>"
                    "Improve this skill</label>"
                    f"<input id='skill-{skill_id}-improve' type='text' name='text'"
                    " maxlength='1000' placeholder='be shorter, lead with the number'"
                    " autocomplete='off'>"
                    "<button class='btn btn-secondary' type='submit'>Queue feedback"
                    "</button></form>"
                    "<p class='empty'>Queued feedback is sent to the company"
                    " endpoint with this skill's prompt on the next pass, and"
                    " the rewrite lands as a new version with an Undo.</p>"
                )
            blocks.append(
                "<article class='settings-skill'>"
                f"<div class='w-head'><h2 class='skill-name'>{html.escape(skill['name'])}</h2>"
                f"<span class='stamp'>{versions}</span></div>"
                f"<p><b>{made_by}</b> · {state_word}"
                + (f" · used {skill['use_count']} times" if skill.get("use_count") else "")
                + "</p>"
                f"<details><summary class='empty'>SKILL.md</summary><pre>{md}</pre></details>"
                f"{improve}{pin_form}{undo}</article>"
            )
        skills_html = "".join(blocks)
        active_count = sum(1 for s in skills if s.get("active"))
        skills_stamp = (f"{active_count} ACTIVE" if active_count == len(skills)
                        else f"{active_count} OF {len(skills)} ACTIVE")
    else:
        skills_html = "<p class='empty'>No skills yet. Accept a proposal in the inbox and it appears here with its history.</p>"
        skills_stamp = "NONE YET"

    if curator_last_run:
        try:
            curator_when = datetime.fromisoformat(curator_last_run).strftime(
                "%Y-%m-%d %H:%M")
        except ValueError:
            curator_when = curator_last_run
        curator_line = f"Curator last ran <b class='mono'>{curator_when}</b>."
    else:
        curator_line = ("Curator last ran <b class='mono'>never</b>; the first"
                        " pass comes a week after it first sees the desk.")

    desk_stamp = "SAMPLE DATA ON" if settings_values.get("sample_data") else "REAL DATA"
    endpoint_stamp = "CONFIGURED" if endpoint_status["configured"] else "NOT SET"
    mail_stamp = "MAIL ON" if settings_values.get("mail_enabled") else "MAIL OFF"
    registry = registry_status or {}
    registry_stamp = "READY" if registry.get("ok") else "NOT CONFIGURED"

    ai = ai or {"connected": False, "label": "", "model": ""}
    if ai.get("connected"):
        ai_status = (f"<b>{html.escape(str(ai.get('label', '')))}</b> answers everything"
                     + (f" with <span class='mono'>{html.escape(str(ai.get('model', '')))}</span>."
                        if ai.get("model") else ".")
                     # A saved AI whose last call failed never reads as healthy.
                     + (" The last call did not succeed."
                        if endpoint_status.get("last") == "error" else ""))
    else:
        ai_status = "No AI key is saved yet. Add one below; it takes a minute."
    # The everyday switches a person rarely needs. The six recommendation
    # switches are rendered here once (spec 022).
    desk_toggles = "".join(
        _toggle_button(key, settings_values[key]) for key in (
            "excel_enabled", "calendar_enabled", "endpoint_enabled",
            "quiet_hours", "daily_cap", "sample_data", "semantic_memory",
            "suggest_headers_only", "plugin_instance_cap",
        )
    )
    recommendation_toggles = "".join(
        _toggle_button(key, settings_values[key]) for key in (
            "recommendations", "recommend_deadlines", "recommend_meetings",
            "recommend_horizon_days", "recommend_model_rank",
            "recommend_threshold",
        )
    )
    learning_toggles = "".join(
        _toggle_button(key, settings_values.get(key), label)
        for key, label in (
            ("learn_topics", "Learn focus topics from repeated asks"),
            ("learn_profile", "Learn lines about you from your recent asks"),
        )
    )
    ai_html = (
        f"<p class='settings-status' id='ai-status'>{ai_status}</p>"
        + _connections_section(connections, editing_connection, keychain_available,
                               connections_notice)
        + _jobs_section(bindings, connections, ai))
    tools_html = _tools_section(excel_status, calendar_status, settings_values,
                                mail_folder, mail_self_address)
    memory_html = _memory_card(settings_values) + _learned_section(learned, settings_values)
    preferences_html = _preferences_section(preferences, preference_notice) + f"""<section class='card settings-card' id='appearance'>
<div class='w-head'><h2>Appearance</h2><span class='stamp'>THIS BROWSER</span></div>
{_theme_tiles()}
<p class='empty'>The theme is kept in this browser and applies to every page of the desk.</p>
</section>"""
    advanced_html = f"""<p class='empty' id='settings-advanced'>The defaults are right for most people. Change these only if you know why.</p>
<section class='card settings-card' id='desk'>
<div class='w-head'><h2>Desk</h2><span class='stamp'>{desk_stamp}</span></div>
<div class='settings-block'>
{desk_toggles}
</div>
<p class='empty'>Sample data fills a fresh desk with labelled example cards
and sample files (a workbook, a calendar file, header-only mail) so every
inbox action can be tried safely. Every cell it fills carries a Sample
data tag, and turning it off removes exactly what it added.</p>
<h3>Recommendations</h3>
<div class='settings-block'>
{recommendation_toggles}
</div>
<p class='empty'>On by default: a deadline in a saved fact becomes a waiting
card in Decisions, with the fact quoted and the day it was saved. Not now
keeps one gone for good, and removing or replacing the fact withdraws it.
With ranking on, the desk asks your AI for a short reason and keeps a card
at or above the chosen score; a lower score rests until the next
morning.</p>
<h3>Learning about you</h3>
<div class='settings-block'>
{learning_toggles}
</div>
<p class='empty'>These two shape what the desk learns from your questions
over time (topics and short lines about you), shown in the Memory
section. Facts themselves have their own switches on the Memory card.</p>
</section>

{_agent_section(settings_values, agent_loop)}

{_desk_check_section(desk_check)}

{_update_section(settings_values, update or {})}

<section class='card settings-card' id='endpoint'>
<div class='w-head'><h2>Presentation timeout</h2></div>
<form method='post' action='/settings/endpoint/save' class='cardform'>
<label class='empty' for='presentation-timeout'>Presentation timeout (seconds)</label>
<input id='presentation-timeout' type='text' name='presentationTimeout' value='{_esc_timeout(endpoint_status)}' placeholder='30' autocomplete='off'>
<button class='btn btn-secondary' type='submit'>Save timeout</button>
</form>
<p class='empty'>How long presentation calls wait before the desk gives
up, from 5 to 300 seconds; every other call keeps the 10 second cap.</p>
</section>

<section class='card settings-card' id='registry'>
<div class='w-head'><h2>Plugin registry</h2><span class='stamp'>{registry_stamp}</span></div>
<p>The plugin registry is a local git checkout of the internal registry
repository. Installs are pinned by content hash and verified with the
same validator the registry's CI runs before anything executes. The
path is read from this setting first, then the AGENTDESK_REGISTRY
environment variable, then the app's own checkout.</p>
{_registry_section(registry)}
</section>

<section class='card settings-card' id='machine'>
<div class='w-head'><h2>Where the app opens</h2><span class='stamp'>LOOPBACK :{server_port}</span></div>
{_extra_hosts_section(extra_hosts, server_port)}
</section>

{_record_card(audit_entries, audit_total)}

<section class='card settings-card' id='skills'>
<div class='w-head'><h2>Skills</h2><span class='stamp'>{skills_stamp}</span></div>
<p>A skill is a saved ask: one click re-runs it. Skills the desk made
itself can be improved from feedback and are curated weekly; pinning one
keeps it out of both. Skills you made are never touched by either.</p>
<div class='settings-block'>
{_toggle_button("skills_auto_create", settings_values.get("skills_auto_create", True), label="Skills: create from repeated asks")}
{_toggle_button("skills_auto_refine", settings_values.get("skills_auto_refine", True), label="Skills: improve from feedback")}
{_toggle_button("skills_curator", settings_values.get("skills_curator", True), label="Skills: weekly curator")}
</div>
<p class='empty'>{curator_line}</p>
{skills_html}
</section>

<section class='card settings-card' id='questions'>
<div class='w-head'><h2>Activity log</h2><span class='stamp'>LOCAL ONLY</span></div>
<p>Only what you typed into research and the assistant. No keystrokes, no
screen, and this list is yours. The full trail is on
<a href="/settings/activity">Activity</a>.</p>
{questions}
</section>"""
    content = f"""<h1>Settings</h1>
<p>Everything this desk does, set from one page. Your AI comes first; the
rest is grouped, so nothing you need every day sits under a switch you
will touch once. A card's stamp is its live state on this machine, read
when the page rendered, and a setting you have never touched is the right
setting.</p>
{_settings_bar()}
<div class='settings-stack'>
{_settings_section('ai', ai_html)}
{_settings_section('tools', tools_html)}
{_settings_section('memory', memory_html)}
{_settings_section('preferences', preferences_html)}
{_settings_section('advanced', advanced_html)}
</div>
"""
    return page_shell("Settings", "/settings", content, version, inbox_count=inbox_count)
