"""The settings page: toggles only, plus the parts that must be visible.

Data sources, quiet hours and the notification budget are toggles or
small choices; the endpoint status is a read-only indicator that tells
the truth under failure. The activity log, skills, audit export and the
what-this-touches statement are reachable from here.
"""

import html
from datetime import datetime

from agentdesk.repetition.skills import render_skill_md

_LABELS = {
    "excel_enabled": "Sales workbook watching",
    "calendar_enabled": "Calendar reading",
    "endpoint_enabled": "Company endpoint calls",
    "quiet_hours": "Quiet hours (18:00-08:00)",
    "daily_cap": "Notifications per day",
}


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


def render_settings_page(
    activity_entries: list[dict],
    skills: list[dict],
    histories: dict[int, list[dict]],
    version: str,
    settings_values: dict | None = None,
    endpoint_status: dict | None = None,
) -> str:
    esc_version = html.escape(version)
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
    endpoint_html = f"<p>{indicator}</p>"

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

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Settings, Agent Desk</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="doc">
<h1>Settings</h1>
<p>Toggles only. The defaults are the recommended ones; a setting you
have never touched is the right setting.</p>
<div class='settings-block'>
{toggles_html}
</div>
<h1 style="margin-top:24px">Company endpoint</h1>
{endpoint_html}
<h1 style="margin-top:24px">Review</h1>
<p><a href="/audit/export.csv">Export the audit log as CSV</a> (Security reads this) <span class="empty">or</span> <a href="/what-this-touches">read what this app touches</a>.</p>
<h1 style="margin-top:24px">Activity log</h1>
<p>Only what flows through the app: the asks you type into research and
the assistant. No keystrokes, no screen, and this list is yours.</p>
{activity}
<h1 style="margin-top:24px">Skills</h1>
{skills_html}
<p class="empty" style="margin-top:18px"><a href="/">Back to the dashboard</a> <span class="mono">{esc_version}</span></p>
</div>
<script src="/static/app.js"></script>
</body>
</html>
"""
