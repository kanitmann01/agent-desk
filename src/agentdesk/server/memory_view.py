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

Ticket #92 adds the hygiene surfaces: an entities section (canonical
name, aliases, type, fact count) with the two-entity merge form, the
junk-sweep preview (GET /memory/sweep lists the candidates with their
reasons and a checkbox each), and the plain notice an edit that merged
into an existing duplicate renders.

Ticket #95 adds the embeddings section: the live embedded and
remaining counts and the backfill action, a plain no-JS POST like
every other button here.

Ticket #96 adds the Graph action beside the entities section: the
link to the server-rendered memory graph page.
"""

import html

from agentdesk.server.core import count_noun
from agentdesk.server.pages import page_shell
from datetime import datetime

from agentdesk.memory.core import (
    EntitySummary,
    Fact,
    Observation,
    SweepCandidate,
)

# The ranked recall preview keeps the server's honest score display:
# deterministic, explainable, no pretense of intelligence.
_SCORE_PLACES = 3

# The plain notice the edit route renders when the edit merged into an
# existing fact with the same text (ticket #92).
EDIT_MERGE_NOTICE = (
    "That edit matched a fact already saved with the same words: the "
    "edited row merged into the older copy, its entity mentions moved "
    "with it, and only one fact remains."
)


# The Graph action (ticket #96), rendered beside the entities section.
GRAPH_LINK = (
    '<p id="graph-link"><a href="/memory/graph">Graph</a>: the facts '
    "and observations as one static picture, with their entity, "
    "temporal, citation and semantic links.</p>"
)


def graph_island_html(mode: str) -> str:
    """The mount point of the interactive memory graph (the SPA build's
    memory-graph island) with its stylesheet and module script. Without
    JavaScript the section keeps a plain pointer to the static graph."""
    return (
        f'<section id="memory-graph-root" data-endpoint="/api/memory/graph"'
        f' data-mode="{html.escape(mode, quote=True)}" aria-label="Memory graph">'
        '<p class="empty">The interactive graph needs JavaScript. '
        '<a href="/memory/graph">Open the static graph</a>.</p></section>'
        '<link rel="stylesheet" href="/static/spa/assets/memory-graph.css">'
        '<script type="module" src="/static/spa/assets/memory-graph.js"></script>\n'
    )


def loop_island_html(fallback_html: str) -> str:
    """The Memory page island (the SPA build's memory-loop entry): the
    whole capture, review, knowledge and removal page. The server forms
    inside the root are the no-JavaScript page; React replaces them on
    mount. The graph stylesheet rides along because the page embeds it."""
    return (
        '<div id="memory-loop-root" data-endpoint="/api/memory/loop">'
        f"{fallback_html}</div>"
        '<link rel="stylesheet" href="/static/spa/assets/memory-graph.css">'
        '<link rel="stylesheet" href="/static/spa/assets/memory-loop.css">'
        '<script type="module" src="/static/spa/assets/memory-loop.js"></script>\n'
    )


def _locked_banner(cause: str) -> str:
    """The locked state: the cause verbatim, and what it means. Nothing
    else renders: a locked store reads and writes nothing."""
    return (
        f"<p class='empty' id='memory-locked'><b>Memory is locked.</b> "
        f"{html.escape(cause)} Memory actions are paused until the key "
        "is back in place; nothing is read or written in plaintext in "
        "the meantime.</p>"
    )


def _embeddings_section(state: dict | None) -> str:
    """The semantic half's surface (ticket #95): the live counts and
    the backfill action, styled like the sweep and encrypt forms. The
    counts are data, not a promise: the button refuses in plain
    language when the probe has not passed or the toggle is off."""
    if state is None:
        return ""
    return (
        "<h2 id='embeddings'>Embeddings</h2>"
        f"<p class='empty mono' id='embeddings-counts'>"
        f"{state['embedded']} embedded, {state['remaining']} remaining</p>"
        "<form method='post' action='/memory/embeddings/backfill' class='cardform'>"
        "<label class='empty' for='backfill-embeddings'>Backfill embeddings: "
        "the facts above without a vector embed oldest-first, one committed "
        "row at a time, so a failed run leaves the earlier rows done.</label>"
        "<button class='btn btn-secondary' type='submit' id='backfill-embeddings'>"
        "Backfill embeddings</button>"
        "</form>"
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
            f"{count_noun(counts['facts'], 'fact')}, "
            f"{count_noun(counts['sources'], 'source')}, "
            f"{count_noun(counts['entities'], 'entity')} and "
            f"{count_noun(counts['observations'], 'observation')} would be "
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


def _maintenance_tile(encrypt: dict | None, embeddings: dict | None) -> str:
    """The loop page's housekeeping, folded away by default: one row per
    action, each saying in one line what it does for the user, with its
    control on the right. Every form posts to the same routes as the
    plain page, so it works without JavaScript."""
    rows: list[str] = []

    def row(title: str, line: str, control: str, row_id: str = "") -> None:
        """Append one maintenance row to the tile: a title, a description line and a
        control.

        row_id is optional and exists only to give the row a DOM id a client-side update
        can target.
        """
        ident = f" id='{row_id}'" if row_id else ""
        rows.append(
            f"<div class='ml-maint-row'{ident}><div class='ml-maint-copy'>"
            f"<b>{title}</b><p>{line}</p></div>"
            f"<div class='ml-maint-act'>{control}</div></div>"
        )

    row(
        "Check what the assistant would recall",
        "Type a question to see which saved facts the assistant would read when answering it.",
        "<form method='post' action='/memory/recall' class='ml-maint-form'>"
        "<label class='sr-only' for='recall-query'>Question</label>"
        "<input id='recall-query' type='text' name='query' "
        "placeholder='e.g. Who owns the Acme renewal?'>"
        "<button class='btn btn-secondary' type='submit'>Check</button></form>",
    )
    if embeddings is not None:
        total = embeddings["embedded"] + embeddings["remaining"]
        ready = (
            f"<span class='mono' id='embeddings-counts'>{embeddings['embedded']} of "
            f"{count_noun(total, 'fact')} ready</span>"
        )
        button = (
            "<form method='post' action='/memory/embeddings/backfill' class='ml-maint-form'>"
            "<button class='btn btn-secondary' type='submit' id='backfill-embeddings'>"
            "Prepare the rest</button></form>"
            if embeddings["remaining"] else ""
        )
        row(
            "Find facts by meaning",
            "Lets recall match facts that say the same thing in different words. "
            f"{ready}.",
            button or "<span class='ml-maint-done'>Up to date</span>",
        )
    if encrypt is not None and encrypt.get("already"):
        row(
            "Encrypted on this computer",
            "<span id='memory-encrypted'>Memory is encrypted at rest: the database "
            "is unreadable without the key file <span class='mono'>memory.key</span> "
            "on this computer.</span>",
            "<span class='ml-maint-done'>On</span>",
        )
    elif encrypt is not None:
        row(
            "Encrypt memory on this computer",
            "<span id='encrypt-offer'>Locks every saved fact with a key file kept here, "
            "so the database file is unreadable without it. You review the counts first.</span>",
            "<a class='btn btn-secondary' href='/memory/encrypt'>Review</a>",
        )
    row(
        "Clear out junk facts",
        "Lists near-empty and duplicate facts so you can delete them; nothing goes "
        "until you tick and confirm.",
        "<a class='btn btn-secondary' href='/memory/sweep'>Review</a>",
    )
    sealed = bool(encrypt and encrypt.get("already"))
    hint = "Encrypted" if sealed else "Not encrypted"
    return (
        "<details class='ml-maint' id='memory-maintenance'>"
        "<summary><span class='ml-maint-title'>Maintenance</span>"
        "<span class='ml-maint-sub'>Recall check, search by meaning, encryption, cleanup</span>"
        f"<span class='ml-maint-chip'>{hint}</span></summary>"
        f"<div class='ml-maint-body'>{''.join(rows)}</div></details>"
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


def _entities_section(entities: list[EntitySummary]) -> str:
    """The compact entity list with the two-entity merge form (ticket
    #92): one row per entity, canonical name, aliases, type and the
    fact count; the form only renders when there is something to
    merge."""
    if not entities:
        return (
            "<h2>Entities</h2>"
            "<p class='empty' id='entities-empty'>No entities yet: they "
            "appear when a retained fact names someone or something.</p>"
            f"{GRAPH_LINK}"
        )
    rows = []
    for entity in entities:
        entity_id = html.escape(str(entity.id))
        aka = ""
        if entity.aliases:
            aka = ", aka " + ", ".join(html.escape(a) for a in entity.aliases)
        rows.append(
            f"<li id='entity-{entity_id}'>{html.escape(entity.canonical_name)}"
            f" <span class='empty mono'>{html.escape(entity.type)},"
            f" {count_noun(entity.fact_count, 'fact')}{aka}</span></li>"
        )
    merge_form = ""
    if len(entities) >= 2:
        options = "".join(
            f'<option value="{html.escape(str(entity.id))}">'
            f"{html.escape(entity.canonical_name)}</option>"
            for entity in entities
        )
        merge_form = (
            '<form method="post" action="/memory/entities/merge" class="cardform">'
            '<label class="empty" for="merge-survivor">Merge two entities the '
            "automatic rules missed: the second one's names and facts join "
            "the first.</label>"
            f'<select id="merge-survivor" name="survivor">{options}</select>'
            f'<select id="merge-removed" name="removed">{options}</select>'
            '<button class="btn btn-secondary" type="submit">Merge entities</button>'
            "</form>"
        )
    return (
        "<h2>Entities</h2>"
        f"<ul id='entities-list'>{''.join(rows)}</ul>{merge_form}"
        f"{GRAPH_LINK}"
    )


def _sweep_section(candidates: list[SweepCandidate]) -> str:
    """The junk sweep preview (ticket #92): every candidate with its
    reason and a checkbox, deleting only what is checked."""
    if not candidates:
        return (
            "<h2 id='sweep'>Junk sweep</h2>"
            "<p class='empty' id='sweep-empty'>No junk candidates: every "
            "stored fact carries real content.</p>"
        )
    rows = []
    for candidate in candidates:
        fact_id = html.escape(str(candidate.fact.id))
        rows.append(
            f'<li><input type="checkbox" id="sweep-{fact_id}"'
            f' name="sweep_{fact_id}" value="on">'
            f'<label for="sweep-{fact_id}">{html.escape(candidate.fact.text)}</label>'
            f' <span class="empty mono">{html.escape(candidate.reason)}</span></li>'
        )
    return (
        '<h2 id="sweep">Junk sweep</h2>'
        f"<p class='empty'>{count_noun(len(candidates), 'candidate')} the "
        "assistant would drop (placeholders, its own knowledge gaps and "
        "session narration). Check what to delete; citations, orphaned "
        "observations and edge-less entities go with them.</p>"
        '<form method="post" action="/memory/sweep" class="cardform">'
        f"<ul id='sweep-candidates'>{''.join(rows)}</ul>"
        '<button class="btn btn-secondary" type="submit">Delete checked</button>'
        "</form>"
    )


def _observations_section(
    observations: list[Observation], facts: list[Fact]
) -> str:
    """The observations section (ticket #93): the reflect form, then
    one row per stored observation, most recently updated first, each
    with its confidence and its citations linked to their facts. The
    cards that stage a new observation land in the inbox; the section
    only ever shows what acceptance wrote."""
    form = (
        '<form method="post" action="/memory/reflect" class="cardform">'
        '<label class="empty" for="reflect-topic">Reflect: derive '
        "observations from the saved facts. Optional topic or entity "
        "name; the cards land in your inbox to accept.</label>"
        '<input id="reflect-topic" type="text" name="topic" '
        'placeholder="Optional topic"> '
        '<input id="reflect-entity" type="text" name="entity" '
        'placeholder="Optional entity name">'
        '<button class="btn btn-primary" type="submit">Reflect</button>'
        "</form>"
    )
    by_id = {fact.id: fact for fact in facts}
    rows = []
    for observation in observations:
        citations = []
        for fact_id in observation.fact_ids:
            fact = by_id.get(fact_id)
            if fact is None:
                continue
            citations.append(
                f'<a href="#fact-{fact.id}">{html.escape(fact.text)}</a>'
            )
        cited = ", ".join(citations) if citations else "nothing citable left"
        rows.append(
            f"<li id='observation-{observation.id}'>"
            f"<b>{html.escape(observation.text)}</b> "
            f"<span class='empty mono'>confidence "
            f"{observation.confidence:.2f}, cites {cited}</span></li>"
        )
    if not rows:
        empty = (
            "<p class='empty' id='observations-empty'>No observations yet:"
            " reflect derives them from the facts above, and one card per"
            " observation waits in your inbox.</p>"
        )
        return f"<h2>Observations</h2>{form}{empty}"
    return (
        "<h2>Observations</h2>"
        f"{form}<ul id='observations-list'>{''.join(rows)}</ul>"
    )


def render_memory_page(
    facts: list[Fact],
    version: str,
    recall: list[tuple[float, Fact]] | None = None,
    query: str = "",
    inbox_count: int = 0,
    locked: str | None = None,
    encrypt: dict | None = None,
    entities: list[EntitySummary] | None = None,
    sweep: list[SweepCandidate] | None = None,
    notice: str | None = None,
    observations: list[Observation] | None = None,
    embeddings: dict | None = None,
    graph_island: bool = False,
    loop_island: bool = False,
) -> str:
    """The full memory document: list, add, edit, delete, recall preview,
    the entities with their merge form, the optional junk-sweep preview,
    the observations with their reflect form (ticket #93), the
    embeddings counts with their backfill action (ticket #95), and the
    encryption surfaces. Locked: the banner alone."""
    if locked is not None:
        content = f"""<h1>Memory</h1>
{_locked_banner(locked)}
"""
        return page_shell("Memory", "/memory", content, version, inbox_count=inbox_count)
    notice_row = f'<p id="memory-notice">{html.escape(notice)}</p>\n' if notice else ""
    sweep_row = _sweep_section(sweep) if sweep is not None else ""
    entities_row = _entities_section(entities) if entities is not None else ""
    observations_row = (
        _observations_section(observations, facts)
        if observations is not None else ""
    )
    embeddings_row = _embeddings_section(embeddings)
    intro = """<p>Facts saved on this machine. The assistant recalls at most five of
them, 500 characters in total, as derived abstractions it may read.
Facts arrive here, from an inbox card you accept, or by capture from the
Assistant and Research when it is on in the memory settings.</p>"""
    add_form = """<h2>Add a fact</h2>
<form method="post" action="/memory/add" class="cardform">
<label class="empty" for="new-fact">Fact</label>
<input id="new-fact" type="text" name="text" placeholder="The revenue total is 220.">
<button class="btn btn-primary" type="submit">Save fact</button>
</form>"""
    # The plain page (no query, no sweep, no notice) is the loop island
    # when the build carries it; a form result keeps the server page so
    # the answer it rendered stays on screen.
    if loop_island and recall is None and sweep is None and not notice:
        fallback = f"""<h1>Memory</h1>
{intro}
{add_form}
<h2>Saved facts</h2>
{_fact_rows(facts)}
{observations_row}
{entities_row}"""
        content = f"""{loop_island_html(fallback)}
{_maintenance_tile(encrypt, embeddings)}
"""
        return page_shell(
            "Memory", "/memory", content, version, inbox_count=inbox_count, wide=True,
        )
    island_row = graph_island_html("page") if graph_island else ""
    content = f"""<h1>Memory</h1>
{notice_row}{intro}
{island_row}{_encrypt_section(encrypt)}
{_recall_section(recall, query)}
{add_form}
<h2>Saved facts</h2>
{_fact_rows(facts)}
{observations_row}
{entities_row}
{embeddings_row}
{sweep_row}
"""
    return page_shell("Memory", "/memory", content, version, inbox_count=inbox_count)
