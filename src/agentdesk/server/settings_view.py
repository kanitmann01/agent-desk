"""The settings page, first section: the activity log and your skills.

Settings #15 will add the toggles; the log's visibility is a #13
acceptance, so the section ships here, readable, with the skills' undo
history next to it.
"""

import html
from datetime import datetime

from agentdesk.repetition.skills import render_skill_md


def render_settings_page(
    activity_entries: list[dict],
    skills: list[dict],
    histories: dict[int, list[dict]],
    version: str,
) -> str:
    esc_version = html.escape(version)
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
<p>The toggles arrive with the settings ticket; what ships first is the
part that has to be visible now: your activity log and your skills.</p>
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
