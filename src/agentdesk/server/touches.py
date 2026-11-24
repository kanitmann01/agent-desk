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


def render_touches(observed: set[str], version: str, now: datetime, inbox_count: int = 0) -> str:
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
<li><b>Processes started:</b> the desk launches no separate program when it starts. While it is open and Outlook alerts are on, it reads the local OS notification store for Outlook alerts, read-only, and writes header-only .eml files into your mail folder; that helper runs only inside the app, starts no scheduled task, service or autostart entry, and stops when the app closes. When an update is staged with Install updates on, it runs the staged program's own <span class="mono">--self-check</span> against a copy of the data before pointing at it; nothing else is launched.</li>
<li><b>Persistence:</b> none. No Run key, no scheduled task, no service, no autostart entry. The app, and its local Outlook alert reader, run only while you keep it open.</li>
<li><b>Network:</b> only the company LLM endpoint, only derived text, every call logged in the audit you can export as CSV.</li>
<li><b>Mail:</b> off by default. When enabled, the app reads only the headers of the .eml files in a folder you choose (From, To, Cc, Subject, Date, Message-ID, In-Reply-To); message bodies are discarded at parse time and never reach any model, any store or any page, and accepted reply drafts are written as files to the local outbox folder for you to send yourself. With Outlook alerts on, the app also reads the local OS notification store for Outlook alerts while it is open: sender and subject lines only, the preview dropped, saved as header-only .eml files; the manual .eml folder stays the history source.</li>
<li><b>Data location:</b> <span class="mono">{html.escape(data_dir_statement())}</span>. The watched workbook is copied to the temp folder before parsing and never modified.</li>
<li><b>Change ledger:</b> every change the desk makes by itself is recorded in <span class="mono">ledger.sqlite3</span> in that folder, with the before and after state of each change so Undo can put it back; the undo is itself recorded and can be undone in turn.</li>
<li><b>Run claim:</b> while the desk's supervised loop runs a pass, a small <span class="mono">agentloop.lock</span> file in that folder holds this process's id, so two desks on one folder never run two passes at once; the file is removed when the pass ends.</li>
<li><b>Updates:</b> off by default. When Install updates is on and a share is set, the desk reads only that share, checks every file against the bundle's manifest, refuses paths that escape the archive, and runs the staged program's check against a copy of the data before writing <span class="mono">update/current.json</span>. A failed check or first start rolls the pointer back and repairs any SQLite store that no longer passes its integrity check. The desk never restarts itself, and nothing runs while it is closed.</li>
<li><b>Uninstall:</b> delete the folder. Nothing is left behind, nothing to unregister.</li>
<li><b>License:</b> the core app is proprietary, all rights reserved; the plugin SDK is Apache-2.0. The Python runtime ships two third-party dependencies, <span class="mono">cryptography</span> (memory encryption at rest; Apache-2.0 OR BSD-3-Clause) and <span class="mono">keyring</span> (model-connection API keys in the OS keychain; MIT), recorded with the dashboard bundle's documented, licensed set in <span class="mono">THIRD-PARTY-NOTICES.md</span>.</li>
</ul>"""
    return page_shell("What this app touches", "", content, version, inbox_count=inbox_count)
