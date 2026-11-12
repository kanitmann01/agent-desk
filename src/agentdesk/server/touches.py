"""The what-this-touches page: generated from the audit vocabulary.

The statement cannot drift from reality: each line in the vocabulary is
shown with whether the audit store has actually seen it, and the static
facts (no processes, no persistence, delete-folder uninstall) live in the
same file as the code that would change them.
"""

import html

from agentdesk.server.pages import page_shell
from datetime import datetime

from agentdesk.assistant import audit as audit_store


def data_dir_statement() -> str:
    """Where app data lives, in the same terms the uninstall story uses.

    Delegates to the app's own resolution so the statement and the real
    folder can never drift apart (imported here, not at module level:
    app.py imports this module).
    """
    from agentdesk.server.app import default_data_dir

    return str(default_data_dir())


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
    content = f"""<h1>What this app touches</h1>
<p>One page, kept honest by the audit log: every line below is a kind of
touch the app can make, and the badge says whether it has actually
happened on this machine. Generated {html.escape(generated)}, version
<span class="mono">{esc_version}</span>.</p>
<table class="rows touches">
<thead><tr><th scope="col">Action</th><th scope="col">Kind</th><th scope="col">What it means</th><th scope="col">Status</th></tr></thead>
<tbody>{table}</tbody>
</table>
<h2>The facts</h2>
<ul>
<li><b>Processes started:</b> none. The app never launches another program.</li>
<li><b>Persistence:</b> none. No Run key, no scheduled task, no service. The app runs only while you keep it open.</li>
<li><b>Network:</b> only the company LLM endpoint, only derived text, every call logged in the audit you can export as CSV.</li>
<li><b>Mail:</b> off by default. When enabled, the app reads only the headers of the .eml files in a folder you choose (From, To, Cc, Subject, Date, Message-ID, In-Reply-To); message bodies are discarded at parse time and never reach any model, any store or any page, and accepted reply drafts are written as files to the local outbox folder for you to send yourself.</li>
<li><b>Data location:</b> <span class="mono">{html.escape(data_dir_statement())}</span>. The watched workbook is copied to the temp folder before parsing and never modified.</li>
<li><b>Uninstall:</b> delete the folder. Nothing is left behind, nothing to unregister.</li>
<li><b>License:</b> MIT. The Python runtime has no third-party dependencies; the dashboard bundle ships a documented, licensed set (see <span class="mono">THIRD-PARTY-LICENSES.md</span>).</li>
</ul>"""
    return page_shell("What this app touches", "", content, version)
