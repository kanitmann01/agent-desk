"""The decision vocabulary behind the audit page's activity trail.

The audit store records every inbox decision under a dotted action name;
this module owns the mapping from those names to the plain words the
activity trail renders. The old /activity page that first used it is a
302 into Settings now, so only the vocabulary remains.
"""

# The decision vocabulary and the plain word each renders as.
DECISIONS = {
    "inbox.approved": "approved",
    "inbox.denied": "denied",
    "inbox.edited": "edited",
    "inbox.snoozed": "snoozed",
    "inbox.more-info": "more-info",
    "inbox.pending": "pending",
    "inbox.restored": "restored",
    "demo.seeded": "sample on",
    "demo.cleared": "sample off",
}


def decision_rows(entries: list[dict]) -> list[dict]:
    """Audit entries filtered to the decision vocabulary, newest first
    (the store already returns them newest first), each carrying the
    plain decision word it renders as."""
    return [
        {"ts": e["ts"], "word": DECISIONS[e["action"]],
         "target": e["target"], "detail": e["detail"]}
        for e in entries
        if e["action"] in DECISIONS
    ]


def render_activity_page(entries: list[dict], version: str, inbox_count: int = 0) -> str:
    """The full activity document: the decision log, newest first."""
    rows = decision_rows(entries)
    if rows:
        body = "".join(
            "<tr><td class='mono'>"
            f"{datetime.fromtimestamp(r['ts']).strftime('%m-%d %H:%M')}</td>"
            f"<td><b>{html.escape(r['word'])}</b></td>"
            f"<td>{html.escape(r['detail'])}"
            f" <span class='empty mono'>{html.escape(r['target'])}</span></td></tr>"
            for r in rows
        )
        table = (
            "<table class='rows'><thead><tr><th scope='col'>When</th>"
            "<th scope='col'>Decision</th><th scope='col'>What</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
    else:
        table = (
            "<p class='empty'>No decisions yet. Approvals, denials, edits, "
            "snoozes, more-info asks, restores, returns and sample-data "
            "turns will be listed here, newest first.</p>"
        )
    content = f"""<h1>Activity</h1>
<p>Every decision you have made on the inbox's cards, newest first:
approved, denied, edited, snoozed, more-info, restores of dismissed
cards, the returns of cards whose snooze ran out, and the sample-data
switch. The full audit log behind it, including model
calls and file reads, is the <a href="/audit/export.csv">CSV export</a>
Security reviews.</p>
{table}
"""
    return page_shell("Activity", "/activity", content, version, inbox_count=inbox_count)
