"""The what-this-touches page: generated from the audit vocabulary.

The statement cannot drift from reality: each line in the vocabulary is
shown with whether the audit store has actually seen it, and the static
facts (no processes, no persistence, delete-folder uninstall) live in the
same file as the code that would change them.
"""

import html
import os
from datetime import datetime
from pathlib import Path

from agentdesk.assistant import audit as audit_store


def data_dir_statement() -> str:
    """Where app data lives, in the same terms the uninstall story uses."""
    override = os.environ.get("AGENTDESK_DATA")
    if override:
        return str(Path(override))
    return str(Path.home() / ".agent-desk")


def render_touches(observed: set[str], version: str, now: datetime) -> str:
    """The one-page statement IT reviews."""
    esc_version = html.escape(version)
    rows = []
    for action, kind, statement in audit_store.VOCABULARY:
        state = "in use" if action in observed else "not observed yet"
        badge = (
            '<span class="touch-badge on">in use</span>'
            if action in observed
            else '<span class="touch-badge">not observed yet</span>'
        )
        rows.append(
            "<tr><td class='mono'>"
            f"{html.escape(action)}</td><td>{html.escape(kind)}</td>"
            f"<td>{statement}</td><td>{badge}</td></tr>"
        )
    table = "".join(rows)
    generated = now.strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What this app touches, Agent Desk</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="doc">
<h1>What this app touches</h1>
<p>One page, kept honest by the audit log: every line below is a kind of
touch the app can make, and the badge says whether it has actually
happened on this machine. Generated {html.escape(generated)}, version
<span class="mono">{esc_version}</span>.</p>
<table class="rows touches">
<thead><tr><th scope="col">Action</th><th scope="col">Kind</th><th scope="col">What it means</th><th scope="col">Status</th></tr></thead>
<tbody>{table}</tbody>
</table>
<h1 style="margin-top:28px">The facts</h1>
<ul>
<li><b>Processes started:</b> none. The app never launches another program.</li>
<li><b>Persistence:</b> none. No Run key, no scheduled task, no service. The app runs only while you keep it open.</li>
<li><b>Network:</b> only the company LLM endpoint, only derived text, every call logged in the audit you can export as CSV.</li>
<li><b>Data location:</b> <span class="mono">{html.escape(data_dir_statement())}</span>. The watched workbook is copied to the temp folder before parsing and never modified.</li>
<li><b>Uninstall:</b> delete the folder. Nothing is left behind, nothing to unregister.</li>
<li><b>License:</b> MIT. No third-party components; see <span class="mono">THIRD-PARTY-LICENSES.md</span>.</li>
</ul>
<p class="empty"><a href="/">Back to the dashboard</a></p>
</div>
<script src="/static/app.js"></script>
</body>
</html>
"""
