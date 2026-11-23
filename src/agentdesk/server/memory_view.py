"""The memory page: the facts the assistant may recall, and their recall.

Modeled on the teammate's memory page (list, add, delete) with edit and
a recall preview added, as server-rendered no-JS forms in this app's
style: everything escaped, every action a plain POST that lands back on
the page. Facts are derived abstractions only: the assistant rides them
in its prompt as one bounded block, nothing more.

Ticket #283 gives the page its shape: it leads with the explanation
("How memory works", under 90 words), then the facts with where each
came from and its own edit and Forget, then the "Forget everything"
control, which asks first. The maintenance tools (the graph, the recall
check, search by meaning, encryption and the cleanup) sit behind one
"Maintenance" disclosure at their existing addresses; a tool the user
asks for shows its result inside the open disclosure. Everything the
page must keep with or without scripting is rendered by the server
outside the island root the build mounts over the forms.

Ticket #94 adds the encryption surfaces: the dry-run conversion form
(GET /memory/encrypt counts what would be sealed; the POST needs the
confirm checkbox), the already-encrypted note, and the locked banner a
marker without its key renders instead of any fact surface. A locked
store never reads or writes plaintext, so the page shows the cause and
nothing else.

Ticket #92 adds the hygiene surfaces: an entities section (canonical
name, aliases, type, fact count) with the two-entity merge form, and the
junk-sweep preview (GET /memory/sweep lists the candidates with their
reasons and a checkbox each).

Ticket #95 adds the embeddings counts and the backfill action, a plain
no-JS POST like every other button here.

Ticket #96 adds the graph page; this page reaches it from Maintenance.
"""

import html

from agentdesk.server.core import count_noun
from agentdesk.server.memory_loop_api import _card_for, origin_of
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


# The explanation that leads the page (ticket #283): under 90 words with
# its heading, in plain words, answering what memory remembers, how it
# learns and who controls it.
HOW_MEMORY_WORKS = (
    "Agent Desk remembers facts about you and your work, such as who owns a "
    "renewal or when a deadline moved, and learns new ones as you work. "
    "Every fact is listed below with where it came from. You are in "
    "control: edit or forget any item, forget everything, or switch "
    "learning off. Memory never stores keys, passwords or the text of "
    "emails. It is all kept on this computer, though a few facts are "
    "shared with your AI when you use it."
)


def _how_memory_works() -> str:
    """The block that leads the page: what memory remembers, how it learns
    and who controls it, in plain words (ticket #283)."""
    return (
        '<section id="how-memory-works" class="card memory-explain" '
        'aria-labelledby="how-memory-works-h">\n'
        '<h2 id="how-memory-works-h">How memory works</h2>\n'
        f"<p>{html.escape(HOW_MEMORY_WORKS)}</p>\n"
        "</section>"
    )


def _forget_section(facts: list[Fact], confirming: bool) -> str:
    """The "Forget everything" control (ticket #283): one form posting to
    its own route. With facts present it asks first: the second submit
    carries the confirm field. An empty bank says so and offers nothing
    to forget."""
    if not facts:
        return "<p class='empty' id='forget-everything'>Memory is empty. No facts yet.</p>"
    # Double-quoted attributes: the readiness checks read these hooks
    # literally (the form's action, the confirm field).
    if confirming:
        return (
            '<section id="forget-everything" class="ml-maint" '
            'aria-labelledby="forget-everything-h">\n'
            '<form method="post" action="/memory/forget-all" class="ml-maint-row">\n'
            '<input type="hidden" name="confirm" value="yes">\n'
            "<div class='ml-maint-copy'>"
            "<b id='forget-everything-h'>Forget every fact?</b>"
            f"<p>This removes {count_noun(len(facts), 'fact')} and everything "
            "the desk made from them. It cannot be undone.</p></div>\n"
            "<div class='ml-maint-act'>"
            "<a class='btn btn-secondary' href='/memory' autofocus>Keep my facts</a>"
            "<button class='btn btn-danger' type='submit'>Forget everything</button>"
            "</div></form></section>"
        )
    return (
        '<section id="forget-everything" class="ml-maint" '
        'aria-labelledby="forget-everything-h">\n'
        "<div class='ml-maint-row'><div class='ml-maint-copy'>"
        "<b id='forget-everything-h'>Forget everything</b>"
        "<p>Removes every fact memory has learned. You will be asked first, "
        "and your settings are kept.</p></div>\n"
        "<div class='ml-maint-act'>"
        '<form method="post" action="/memory/forget-all">'
        "<button class='btn btn-danger' type='submit'>Forget everything</button>"
        "</form></div></div></section>"
    )


# The stylesheet of the server-rendered pieces that share the island's
# tile language (the Maintenance disclosure and the Forget control).
LOOP_STYLES_HTML = (
    '<link rel="stylesheet" href="/static/spa/assets/memory-loop.css">\n'
)


def loop_island_html(fallback_html: str) -> str:
    """The Memory page island (the SPA build's memory-loop entry): the
    whole capture, review, knowledge and removal page. The server forms
    inside the root are the no-JavaScript page; React replaces them on
    mount. Everything the page must keep with or without scripting (the
    explanation, the Forget control, the Maintenance disclosure) is
    rendered by the server outside the root."""
    return (
        '<div id="memory-loop-root" data-endpoint="/api/memory/loop">'
        f"{fallback_html}</div>"
        '<link rel="stylesheet" href="/static/spa/assets/memory-graph.css">'
        f"{LOOP_STYLES_HTML.strip()}"
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


def _maintenance_tile(
    encrypt: dict | None,
    embeddings: dict | None,
    recall: list | None = None,
    query: str = "",
    sweep: list | None = None,
) -> str:
    """The page's housekeeping, folded away by default (ticket #283). One
    disclosure holds every maintenance tool: the graph, the recall check,
    search by meaning, encryption and the cleanup, each saying in one
    line what it does for the user with its control on the right. A tool
    the user just asked for (a recall answer, the sweep's or the
    encryption's preview) shows its result inside the open disclosure in
    place of its link. Every form posts to the same routes as before, so
    each address keeps working and nothing needs JavaScript."""
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

    def result(markup: str) -> None:
        """Append one full-width block under the rows so far: what a tool answered."""
        rows.append(f"<div class='ml-maint-result'>{markup}</div>")

    row(
        "See the graph",
        "Every fact, where it came from and what it links to, as one picture.",
        '<a class="btn btn-secondary" href="/memory/graph">Open</a>',
    )
    answer = ""
    if recall:
        answer = "<ol id='recall-preview'>" + "".join(
            f"<li>{html.escape(fact.text)} "
            f"<span class='empty mono'>score {score:.{_SCORE_PLACES}f}</span></li>"
            for score, fact in recall
        ) + "</ol>"
    elif recall is not None:
        answer = ("<p class='empty'>Nothing recalled: no fact shares a word "
                  "with that question.</p>")
    row(
        "Check what the assistant would recall",
        "Type a question to see which saved facts the assistant would read when answering it.",
        "<form method='post' action='/memory/recall' class='ml-maint-form'>"
        "<label class='sr-only' for='recall-query'>Recall preview</label>"
        "<input id='recall-query' type='text' name='query' "
        f"value='{html.escape(query, quote=True)}' "
        "placeholder='e.g. Who owns the Acme renewal?'>"
        "<button class='btn btn-secondary' type='submit'>Check</button></form>",
    )
    if answer:
        result(answer)
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
            "<span id='memory-encrypted'>Memory is already encrypted at rest: the "
            "database is unreadable without the key file <span class='mono'>memory.key</span> "
            "on this computer.</span>",
            "<span class='ml-maint-done'>On</span>",
        )
    elif encrypt is not None and encrypt.get("counts") is not None:
        counts = encrypt["counts"]
        summary = (
            f"<span id='encrypt-counts'>{count_noun(counts['facts'], 'fact')}, "
            f"{count_noun(counts['sources'], 'source')}, "
            f"{count_noun(counts['entities'], 'entity')} and "
            f"{count_noun(counts['observations'], 'observation')} would be "
            "sealed as AES-256-GCM ciphertext under a locally generated "
            "key file (<span class='mono'>memory.key</span>). Duplicates "
            "collapse and orphaned observations go first. This cannot "
            "be undone without the key.</span>"
        )
        row(
            "Encrypt memory on this computer",
            summary,
            "<form method='post' action='/memory/encrypt' class='inlineform'>"
            "<label for='encrypt-confirm'>Confirm</label> "
            "<input id='encrypt-confirm' type='checkbox' name='confirm' value='on'> "
            "<button class='btn btn-primary' type='submit'>Encrypt memory</button></form>",
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
        "" if sweep is not None else "<a class='btn btn-secondary' href='/memory/sweep'>Review</a>",
    )
    if sweep is not None:
        result(_sweep_markup(sweep))
    sealed = bool(encrypt and encrypt.get("already"))
    hint = "Encrypted" if sealed else "Not encrypted"
    asked = recall is not None or sweep is not None or (
        encrypt is not None and encrypt.get("counts") is not None
    )
    return (
        f"<details class='ml-maint' id='memory-maintenance'{' open' if asked else ''}>"
        "<summary><span class='ml-maint-title'>Maintenance</span>"
        "<span class='ml-maint-sub'>Graph, recall check, search by meaning, encryption, cleanup</span>"
        f"<span class='ml-maint-chip'>{hint}</span></summary>"
        f"<div class='ml-maint-body'>{''.join(rows)}</div></details>"
    )


def _sweep_markup(candidates: list[SweepCandidate]) -> str:
    """The junk sweep's preview (ticket #92), shown inside the Maintenance
    disclosure in place of its link: every candidate with its reason and
    a checkbox, deleting only what is checked."""
    if not candidates:
        return (
            "<p class='empty' id='sweep-empty'>No junk candidates: every "
            "stored fact carries real content.</p>"
        )
    rows = "".join(
        f'<li><input type="checkbox" id="sweep-{candidate.fact.id}"'
        f' name="sweep_{candidate.fact.id}" value="on">'
        f'<label for="sweep-{candidate.fact.id}">{html.escape(candidate.fact.text)}</label>'
        f" <span class='empty mono'>{html.escape(candidate.reason)}</span></li>"
        for candidate in candidates
    )
    return (
        f"<p class='empty'>{count_noun(len(candidates), 'candidate')} the "
        "assistant would drop (placeholders, its own knowledge gaps and "
        "session narration). Check what to delete; citations, orphaned "
        "observations and edge-less entities go with them.</p>"
        '<form method="post" action="/memory/sweep">'
        f"<ul id='sweep-candidates' class='ml-maint-checks'>{rows}</ul>"
        "<button class='btn btn-secondary' type='submit'>Delete checked</button>"
        "</form>"
    )


def _origin_line(fact: Fact, inbox, excerpts: dict) -> str:
    """Where one fact came from and when it was saved, as a single plain
    line (ticket #283): the same words the island shows, never the stored
    bookkeeping."""
    origin = origin_of(fact.source, _card_for(inbox, fact.source),
                       excerpts.get(fact.source_id))
    parts = [origin["label"]]
    if origin["how"] and origin["how"] != "Saved":
        parts.append(origin["how"].lower())
    parts.append("saved " + datetime.fromtimestamp(fact.created_ts).strftime("%Y-%m-%d"))
    return ", ".join(parts)


def _fact_rows(facts: list[Fact], inbox=None, sources=()) -> str:
    """One row per fact: the text, where it came from, and its two
    actions, edit and forget. The list's own empty line stays with the
    list; the page's "Memory is empty" sits beside the Forget control."""
    if not facts:
        return "<p class='empty' id='memory-empty'>No facts yet. Type one above, or let the desk learn as you work.</p>"
    excerpts = {excerpt.id: excerpt for excerpt in sources}
    rows = []
    for fact in facts:
        fact_id = html.escape(str(fact.id))
        rows.append(
            f"<div class='ask' id='fact-{fact_id}'>"
            f"<b>{html.escape(fact.text)}</b> "
            f"<span class='empty mono'>{html.escape(_origin_line(fact, inbox, excerpts))}</span>"
            f"<form method='post' action='/memory/{fact_id}/edit' class='cardform'>"
            f"<label class='empty' for='edit-{fact_id}'>Edit fact {fact_id}</label>"
            f"<input id='edit-{fact_id}' type='text' name='text' "
            f"value='{html.escape(fact.text, quote=True)}'>"
            "<button class='btn btn-secondary' type='submit'>Save</button>"
            "</form>"
            f"<form method='post' action='/memory/{fact_id}/delete' class='cardform'>"
            "<button class='btn btn-secondary' type='submit'>Forget</button>"
            "</form>"
            "</div>"
        )
    return "".join(rows)


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
                f'<a href="#fact-{html.escape(str(fact.id))}">'
                f"{html.escape(fact.text)}</a>"
            )
        cited = ", ".join(citations) if citations else "nothing citable left"
        rows.append(
            f"<li id='observation-{html.escape(str(observation.id))}'>"
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
    loop_island: bool = False,
    confirm_forget_all: bool = False,
    inbox=None,
    sources=(),
) -> str:
    """The full memory document. It opens with the explanation (ticket
    #283), then the facts with where each came from and its own edit and
    Forget, then the "Forget everything" control, which asks first when
    `confirm_forget_all` is set, then the one Maintenance disclosure
    (the graph, the recall check, search by meaning, encryption and the
    cleanup), open when it carries an answer the user just asked for.
    The plain page also carries the add form, the entities with their
    merge form (ticket #92) and the observations with their reflect form
    (ticket #93); with the build present the island replaces that part.
    Locked: the banner alone."""
    if locked is not None:
        content = f"""<h1>Memory</h1>
{_locked_banner(locked)}
"""
        return page_shell("Memory", "/memory", content, version, inbox_count=inbox_count)
    notice_row = f'<p id="memory-notice">{html.escape(notice)}</p>\n' if notice else ""
    entities_row = _entities_section(entities) if entities is not None else ""
    observations_row = (
        _observations_section(observations, facts)
        if observations is not None else ""
    )
    tile = _maintenance_tile(encrypt, embeddings, recall=recall, query=query, sweep=sweep)
    add_form = """<h2>Add a fact</h2>
<form method="post" action="/memory/add" class="cardform">
<label class="empty" for="new-fact">Fact</label>
<input id="new-fact" type="text" name="text" placeholder="The revenue total is 220.">
<button class="btn btn-primary" type="submit">Save fact</button>
</form>"""
    forget = _forget_section(facts, confirm_forget_all)
    # The plain page (no query, no sweep, no notice) is the loop island
    # when the build carries it; a form result keeps the server page so
    # the answer it rendered stays on screen.
    if loop_island and recall is None and sweep is None and not notice:
        fallback = f"""{add_form}
<h2>Saved facts</h2>
{_fact_rows(facts, inbox, sources)}
{observations_row}
{entities_row}"""
        content = f"""<h1>Memory</h1>
{_how_memory_works()}
{loop_island_html(fallback)}
{forget}
{tile}
"""
        return page_shell(
            "Memory", "/memory", content, version, inbox_count=inbox_count, wide=True,
        )
    # The disclosure and the Forget control speak the island's tile
    # language, so a build carrying the island lends them its stylesheet.
    styles = LOOP_STYLES_HTML if loop_island else ""
    content = f"""<h1>Memory</h1>
{notice_row}{_how_memory_works()}
{styles}{add_form}
<h2>Saved facts</h2>
{_fact_rows(facts, inbox, sources)}
{observations_row}
{entities_row}
{forget}
{tile}
"""
    return page_shell("Memory", "/memory", content, version, inbox_count=inbox_count)
