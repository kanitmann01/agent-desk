"""The memory page: the facts the assistant may recall, and their recall.

Modeled on the teammate's memory page (list, add, delete) with edit and
a recall preview added, as server-rendered no-JS forms in this app's
style: everything escaped, every action a plain POST that lands back on
the page. Facts are derived abstractions only: the assistant rides them
in its prompt as one bounded block, nothing more.

Ticket #94 adds the encryption surfaces: the dry-run conversion form
(GET /memory/encrypt counts what would be sealed; the POST needs the
confirm checkbox), the already-encrypted note, and the locked banner a
marker without its key renders instead of any fact surface. A locked
store never reads or writes plaintext, so the page shows the cause and
nothing else.
"""

import html

from agentdesk.server.pages import page_shell
from datetime import datetime

from agentdesk.memory.core import Fact

# The ranked recall preview keeps the server's honest score display:
# deterministic, explainable, no pretense of intelligence.
_SCORE_PLACES = 3


def _count(value: int, noun: str) -> str:
    """One counted noun, singular handled honestly."""
    return f"{value} {noun}" + ("" if value == 1 else "s")


def _locked_banner(cause: str) -> str:
    """The locked state: the cause verbatim, and what it means. Nothing
    else renders: a locked store reads and writes nothing."""
    return (
        f"<p class='empty' id='memory-locked'><b>Memory is locked.</b> "
        f"{html.escape(cause)} Memory actions are paused until the key "
        "is back in place; nothing is read or written in plaintext in "
        "the meantime.</p>"
    )


def _encrypt_section(state: dict | None) -> str:
    """The encryption surfaces: the plain bank's pointer to the action,
    the sealed bank's note, or the dry-run form with its counts."""
    if state is None:
        return ""
    if state.get("already"):
        return (
            "<p class='empty' id='memory-encrypted'>Memory is already "
            "encrypted at rest: facts, sources, entities and observations "
            "are stored as AES-256-GCM ciphertext under the key file "
            "<span class='mono'>memory.key</span>, and this page "
            "decrypts them for you as you read.</p>"
        )
    if state.get("counts") is not None:
        counts = state["counts"]
        summary = (
            f"{_count(counts['facts'], 'fact')}, "
            f"{_count(counts['sources'], 'source')}, "
            f"{_count(counts['entities'], 'entity')} and "
            f"{_count(counts['observations'], 'observation')} would be "
            "sealed as AES-256-GCM ciphertext under a locally generated "
            "key file (<span class='mono'>memory.key</span>). Duplicates "
            "collapse and orphaned observations go first. This cannot "
            "be undone without the key."
        )
        return (
            "<h2>Encrypt memory at rest</h2>"
            f"<p id='encrypt-counts'>{summary}</p>"
            "<form method='post' action='/memory/encrypt' class='cardform'>"
            "<label class='empty' for='encrypt-confirm'>Confirm: rewrite every stored text and blank the plaintext.</label>"
            "<input id='encrypt-confirm' type='checkbox' name='confirm' value='on'>"
            "<button class='btn btn-primary' type='submit'>Encrypt memory</button>"
            "</form>"
        )
    return (
        "<p id='encrypt-offer'>This memory bank is plaintext on disk. "
        "<a href='/memory/encrypt'>Encrypt memory at rest</a>: one "
        "action seals every text field under a locally generated key "
        "file.</p>"
    )


def _fact_rows(facts: list[Fact]) -> str:
    """One row per fact: the text, its provenance, and its two actions."""
    if not facts:
        return "<p class='empty' id='memory-empty'>No facts yet. Add one below; it will ride in the assistant's context as a derived abstraction, at most five facts and 500 characters a turn.</p>"
    rows = []
    for fact in facts:
        fact_id = html.escape(str(fact.id))
        created = datetime.fromtimestamp(fact.created_ts).strftime("%Y-%m-%d")
        rows.append(
            f"<div class='ask' id='fact-{fact_id}'>"
            f"<b>{html.escape(fact.text)}</b> "
            f"<span class='empty mono'>source {html.escape(fact.source or 'unknown')},"
            f" saved {created}</span>"
            f"<form method='post' action='/memory/{fact_id}/edit' class='cardform'>"
            f"<label class='empty' for='edit-{fact_id}'>Edit fact {fact_id}</label>"
            f"<input id='edit-{fact_id}' type='text' name='text' "
            f"value='{html.escape(fact.text, quote=True)}'>"
            "<button class='btn btn-secondary' type='submit'>Save</button>"
            "</form>"
            f"<form method='post' action='/memory/{fact_id}/delete' class='cardform'>"
            "<button class='btn btn-secondary' type='submit'>Delete</button>"
            "</form>"
            "</div>"
        )
    return "".join(rows)


def _recall_section(recall: list[tuple[float, Fact]] | None, query: str) -> str:
    """The recall preview: the ranked answers to one query, best first."""
    form = (
        "<form method='post' action='/memory/recall' class='cardform'>"
        "<label class='empty' for='recall-query'>Recall preview</label>"
        "<input id='recall-query' type='text' name='query' "
        f"value='{html.escape(query, quote=True)}' "
        "placeholder='What would the assistant ask about?'>"
        "<button class='btn btn-secondary' type='submit'>Preview recall</button>"
        "</form>"
    )
    if recall is None:
        return form
    if not recall:
        return (
            form
            + "<p class='empty'>Nothing recalled: no fact shares a token with that query.</p>"
        )
    rows = "".join(
        f"<li>{html.escape(fact.text)} <span class='empty mono'>"
        f"score {score:.{_SCORE_PLACES}f}, source {html.escape(fact.source or 'unknown')}"
        "</span></li>"
        for score, fact in recall
    )
    return form + f"<ol id='recall-preview'>{rows}</ol>"


def render_memory_page(
    facts: list[Fact],
    version: str,
    recall: list[tuple[float, Fact]] | None = None,
    query: str = "",
    inbox_count: int = 0,
    locked: str | None = None,
    encrypt: dict | None = None,
) -> str:
    """The full memory document: list, add, edit, delete, recall preview,
    and the encryption surfaces. Locked: the banner alone."""
    if locked is not None:
        content = f"""<h1>Memory</h1>
{_locked_banner(locked)}
"""
        return page_shell("Memory", "/memory", content, version, inbox_count=inbox_count)
    content = f"""<h1>Memory</h1>
<p>Facts saved on this machine. The assistant recalls at most five of
them, 500 characters in total, as derived abstractions it may read;
nothing is captured from your conversations. Facts arrive here, or with
an inbox card you accept.</p>
{_encrypt_section(encrypt)}
{_recall_section(recall, query)}
<h2>Add a fact</h2>
<form method="post" action="/memory/add" class="cardform">
<label class="empty" for="new-fact">Fact</label>
<input id="new-fact" type="text" name="text" placeholder="The revenue total is 220.">
<button class="btn btn-primary" type="submit">Save fact</button>
</form>
<h2>Saved facts</h2>
{_fact_rows(facts)}
"""
    return page_shell("Memory", "/memory", content, version, inbox_count=inbox_count)
