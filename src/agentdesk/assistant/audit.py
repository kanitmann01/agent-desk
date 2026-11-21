"""The audit store: what touched what, and when.

Append-only by policy and by schema (no update or delete statements
anywhere). Every outbound model call and every brokered watch action
lands here as (actor, action, target, timestamp) plus status metadata,
exportable as plain CSV for Security review. The log describes calls; it
never carries prompt text or raw file contents.
"""

import csv
import io
import sqlite3
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  actor TEXT NOT NULL DEFAULT 'agent-desk',
  action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  request_bytes INTEGER NOT NULL DEFAULT 0,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS assistant_log (
  id INTEGER PRIMARY KEY,
  ts REAL NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL
);
"""

# The audit event vocabulary: every action the app can record, with the
# plain-language statement the what-this-touches page shows. The page is
# generated from this table and the store's observed actions, so it
# cannot drift from reality by more than one entry.
VOCABULARY: list[tuple[str, str, str]] = [
    ("excel.register", "file", "You choose a workbook through a file picker; its name is remembered so the app can watch it."),
    ("excel.poll", "file", "The watched workbook is copied to a temp file and read there, read-only, never opened in place."),
    ("calendar.ingest", "file", "The calendar JSON your own Power Automate flow writes to OneDrive is read, read-only."),
    ("calendar.poll", "file", "The calendar file is checked for updates, read-only."),
    ("llm.research", "endpoint", "Research questions are sent to the company LLM endpoint, as derived text only."),
    ("llm.assistant", "endpoint", "Assistant questions are sent to the company LLM endpoint, with widget context attached."),
    ("llm.breakdown", "endpoint", "Meeting breakdowns are sent to the company LLM endpoint, meeting name only."),
    ("llm.rank", "endpoint", "The desk sends the titles of waiting recommendations and the facts they cite to the company LLM endpoint so it can rank them; the row names the model and the request size, never the text."),
    ("llm.wizard", "endpoint", "Your plain-English plugin description, with the app's fixed list of data-source kinds, is sent to the company LLM endpoint so the wizard can draft its questions and the plugin manifest. No workbook, calendar or mail data is attached."),
    # The pressed-card press (spec 017 workstream 3): the reply draft or
    # explanation a pressed card spends, audited on both doors (the SPA's
    # JSON route and the no-JS page) with the same row.
    ("insight.press", "endpoint", "A pressed card sends what its disclosure named (a thread's subject, sender and last line, or one finding sentence) to the company LLM endpoint; the row names the kind and the source, never the words."),
    # The mail vocabulary (ticket #44), off by default in settings. The
    # mail path is metadata-only by construction: bodies are discarded
    # at parse time and no LLM call exists anywhere in it.
    ("mail.poll", "file", "The mail folder you chose is listed and the .eml headers are read, read-only. Message bodies are discarded at parse time and never stored. Off by default."),
    ("mail.draft", "decision", "A reply draft card was created from the message's headers (recipients, subject). The draft text is what you typed, never message content."),
    ("mail.sent", "file", "Accepting a reply draft wrote a threaded .eml file into the local outbox folder. Nothing is transmitted by this app; sending the reply is yours to do in your own mail client."),
    # The approvals vocabulary (ticket #41): every decision on an inbox
    # card, and every plugin lifecycle mutation.
    ("inbox.approved", "decision", "You accepted a card in the inbox; the acceptance is recorded against that card."),
    ("inbox.denied", "decision", "You dismissed a card in the inbox; the dismissal is recorded against that card."),
    ("inbox.edited", "decision", "You edited a card's draft; a plain-text preview of the draft is recorded, never markup."),
    ("inbox.snoozed", "decision", "You snoozed a card for one hour or until the next morning; the return time is recorded."),
    ("inbox.more-info", "decision", "You asked for more information; your instruction is recorded with the card."),
    ("inbox.pending", "decision", "A snoozed card came back due, or a plugin update began waiting for your OK; recorded so nothing reappears silently."),
    ("inbox.restored", "decision", "You restored a dismissed card to the waiting inbox; the recovery is recorded against that card."),
    # The memory vocabulary (ticket #42): the one non-page creation path.
    # The row names the fact's source, never the fact's text.
    ("memory.fact", "decision", "An accepted inbox card carried a fact, and it was saved to the memory store. The row names where the fact came from, never the fact itself."),
    ("memory.capture", "decision", "A conversation excerpt from one of the desk's surfaces (the assistant, research, the workbook tracker or the agents) was scanned for durable facts; candidates wait as inbox cards until you accept them. The row names the channel and how many went to review or were saved, never the excerpt."),
    ("llm.retain", "endpoint", "A conversation excerpt you chose to save was sent to the company LLM endpoint to be turned into candidate facts; the excerpt is all the endpoint sees, and the candidates wait as inbox cards until you accept them."),
    # The background observation pass (spec 017 workstream 3): after
    # memory changes the endpoint redrafts the derived observations.
    ("llm.observe", "endpoint", "Facts already stored on this desk are sent to the company LLM endpoint so the observations derived from them stay current; the row names how many observations were written, never their text."),
    # The encryption action (ticket #94): a local rewrite of the memory
    # database, no network anywhere in it. The row names the field count,
    # never a stored text, and never any part of the key.
    ("memory.encrypt", "decision", "You chose to encrypt the memory database: every stored fact, source, entity and observation text was rewritten as AES-256-GCM ciphertext under the local memory.key file. The row names how many fields were sealed, never their text."),
    # The rest of the memory-bank port's actions (#92, #93): local
    # decisions and one more endpoint call; counts and ids only, never
    # stored text.
    ("memory.sweep", "decision", "You ran the junk sweep after its preview: the listed knowledge-gap facts were deleted together with their orphaned citations, observations and entities. The row counts what went, never what it said."),
    ("memory.merge", "decision", "You merged two duplicate entities on the memory page: their aliases were unioned and every fact mention relinked to the survivor. The row names the two ids, never a name."),
    # The memory page's removal bookkeeping (spec 017 workstream 3):
    # every row names ids and counts, never the stored text.
    ("memory.remove", "decision", "Rows were deleted from the memory store through the memory page's delete or the junk sweep: the row names the kind, the id and the counts that went, never the stored text."),
    ("memory.keep", "decision", "You kept a replaced fact in the bank beside its replacement, so both stay recallable and reviewable. The row names the fact's id, never its text."),
    ("memory.undo", "decision", "You undid a removal within its window: the removed rows were put back into the memory store. The row counts what came back, never the text."),
    ("llm.reflect", "endpoint", "Facts you already accepted were sent to the company LLM endpoint to draft observations; only those facts and the topic you typed reach the endpoint, and the drafts wait as inbox cards until you accept them."),
    ("memory.observation", "decision", "An accepted card carried an observation: it was saved to the memory store with its citations. The row counts the citations, never their text."),
    # The semantic recall vocabulary (ticket #95): every outbound
    # embeddings call is one row (the model and input size, never the
    # text), and the backfill action is one row of counts.
    ("llm.embeddings", "endpoint", "Fact and query texts are sent to the company LLM endpoint to be turned into embedding vectors for semantic recall. Each row names the endpoint, the model and the input's size in bytes, never the text itself."),
    ("memory.embeddings", "decision", "You ran the embeddings backfill on the memory page: facts stored without a vector were embedded oldest-first, one committed row at a time. The row counts how many were embedded and how many remain, never their text."),
    ("plugin.install", "plugin", "A plugin zip you chose, or a registry release you picked, is validated and installed under the app's own data folder, in pilot mode."),
    ("plugin.update", "plugin", "A plugin update is validated; identical or narrower permissions apply, wider ones hold for your OK."),
    ("plugin.consent", "plugin", "A held plugin update is applied after you approved its added permissions."),
    ("plugin.enable", "plugin", "An installed plugin is turned back on; its widget returns to the dashboard."),
    ("plugin.disable", "plugin", "An installed plugin is turned off; its files and data stay untouched."),
    ("plugin.uninstall", "plugin", "An installed plugin's program files are deleted; its data is kept until a separate purge."),
    ("plugin.rollback", "plugin", "A plugin is switched back to its previous version; both versions stay recorded."),
    ("plugin.retest", "plugin", "A plugin's declared data source is checked again, right now, to refresh its card."),
    ("plugin.purge-data", "plugin", "A plugin's kept data folder is deleted, only after the separate named confirmation."),
    # The registry bridge: reads stay local, no network anywhere in it.
    ("registry.read", "file", "The plugins page reads the local registry checkout's index.json, read-only, to list what can be installed."),
    # Publishing (ticket #63): the create-to-publish loop, local only.
    ("registry.publish", "plugin", "An installed plugin is validated and copied into the local registry checkout as a new release pinned by a tree digest; the index entry is appended. No network anywhere in it."),
    ("settings.registry", "decision", "The registry checkout folder was saved or cleared in settings; the choice itself is the record."),
    # The remaining settings decisions (spec 017 workstream 3).
    ("settings.preferences", "decision", "Your working preferences (quiet hours, channel switches, preparation minutes and the like) were saved in settings; the row names which keys changed, never any text you typed."),
    ("settings.hosts", "decision", "The list of extra host names the server may accept was saved or cleared in settings; the row says whether it was updated or cleared, not the names."),
    # The demo vocabulary (ticket #68): the Sample data switch is a
    # decision like the others, and both turns say exactly what happened.
    ("demo.seeded", "decision", "The Sample data switch was turned on: labelled sample cards and sample fixtures (a workbook, a calendar file, header-only mail files) were created under the app's sample folder. Everything is marked Sample; none of it is live."),
    ("demo.cleared", "decision", "The Sample data switch was turned off: the labelled sample cards and the sample folder were removed. Nothing you created yourself is touched."),

    # The agents vocabulary (spec 012): one row per task run and one per
    # its feedback. The run row names the agent, the outcome and how many
    # recalled facts the run used; the feedback row names the run and the
    # feedback's length. Neither ever carries the brief, the artifact,
    # any fact's text or the feedback's words.
    ("agents.run", "decision", "You ran one of the desk's agents on a brief. The brief, at most five recalled facts and the agent's instructions were sent to the company LLM endpoint as one prompt; the row names the agent, whether the run succeeded and how many facts it used, never the brief or the artifact."),
    ("agents.feedback", "decision", "You said how an agent run landed. The feedback is stored on the run and offered to the memory loop on the agents channel as a review card you accept or reject; the row names the agent, the run and the feedback's length, never its words."),
    ("agents.download", "file", "A run's presentation files (the deck, its PDF or an image) were served for download from this desk's own data folder. The row names the agent, the run and the file kind, never the content."),

    # The peer-to-peer vocabulary (ticket #67): sharing plugins between
    # desks with nothing centralized. Discovery announces on the local
    # network only and starts on the first peers page visit; reads are
    # token-gated; installs run the shared validator exactly like
    # registry installs.
    ("peer.code", "decision", "A short-lived single-use pairing code was generated so another desk can pair with this one. The code itself is never recorded; only the fact that one was made."),
    ("peer.pair", "network", "This desk submitted a pairing code to another desk over the local network and pinned that desk's identity and channel token, so its shared plugins can be installed here."),
    ("peer.paired", "network", "Another desk redeemed a pairing code on this desk; its identity and the channel token are now recorded here. Verification compares only the token's hash; the token is kept so pairing works in both directions, like any API client credential."),
    ("peer.share", "plugin", "An installed plugin was marked shared (or unshared) with paired desks. Only shared plugins are ever served to a peer, and only their plugin files, never this desk's data."),
    ("peer.read", "network", "A paired desk read this desk's shared plugin list, a manifest, or a bundle over the token-gated local peer endpoint. The row names what was read, not any content."),
    ("peer.install", "plugin", "A plugin was downloaded from a paired desk, verified against the publisher's recorded digest, validated by the shared validator, and installed with the peer recorded as its source."),
    ("peer.update", "plugin", "A plugin that came from a paired desk was updated to the publisher's newer version, through the same validate-and-consent path as every update."),
    ("deskcheck.fixed", "decision", "The desk check found a problem it was sure about and fixed it by itself; the change is listed under Activity with Undo."),
    ("deskcheck.fix-failed", "decision", "A fix the desk tried did not work; the cause is shown in Settings › Desk check."),
    # The supervised loop's own rows (spec 016, ticket 04): one per pass and
    # one per step that raised. The pass row names each step's outcome and
    # duration, never any data the step read.
    ("agentloop.pass", "decision", "The agent loop ran one pass while the app was open; the row lists the steps and how long each took."),
    ("agentloop.step-failed", "decision", "One step of the agent loop failed; the other steps still ran."),
    ("ledger.undo", "decision", "You pressed Undo on a change the desk made by itself; the earlier state was put back, and the undo is itself recorded and undoable."),

    # The self-improving skills vocabulary (spec 016, ticket 10): rows name
    # the skill and counts, never the prompt or the feedback's words. Only
    # agent-made skills are ever created, refined or curated by the desk.
    ("skill.created", "decision", "The desk noticed the same ask coming back and made it a skill by itself, active immediately, with an Undo on Activity. The row names the skill, never the ask's words."),
    ("skill.refined", "decision", "The desk rewrote one of its own skills from the queued feedback through the endpoint, as a new version with an Undo that restores the earlier prompt. The row names the skill, never the prompt or the feedback."),
    ("llm.skill-refine", "endpoint", "One desk-made skill's prompt and the queued feedback about it were sent to the company LLM endpoint so the skill can be rewritten. The row names the model and the request's size, never the prompt or the feedback's words."),
    ("skill.curated", "decision", "The weekly curator moved unused, unpinned, desk-made skills between active, stale and archived, after writing a snapshot. The row carries the pass's counts; each move is its own Undo row on Activity."),

    # The key lifecycle (spec 018): a saved, changed or deleted model
    # connection. The rows name the label and the preset only; the key
    # itself lives in the OS keychain and never reaches the trail.
    ("keys.create", "decision", "You saved a named model connection: its label and provider preset are recorded here, its key went to this machine's keychain, and only the masked hint (first three, last four) is kept beside it."),
    ("keys.update", "decision", "You changed a saved connection (its label, base URL, headers, default star or key). The row names the connection; an empty key field kept the stored key, and the stored key changed only when you typed a new one or pressed clear."),
    ("keys.delete", "decision", "You deleted a saved connection; its row and its keychain entry went together, and no secret material is recorded here."),
    ("keys.test", "decision", "You checked a saved connection: the desk made one free model-list request against its endpoint with its key (or, only when you pressed the deeper check, one one-token completion with the model you typed), and recorded the outcome and its plain-language cause. The row names the connection; no key material is ever recorded."),
    ("recommend.added", "decision", "The desk added a recommendation built from facts you saved; the row names the rule and the fact ids, never the fact text."),
    ("recommend.withdrawn", "decision", "A recommendation was withdrawn because the fact behind it was removed or replaced."),
    ("update.applied", "decision", "The desk staged a version from the update share after it passed its own check; the row names the version, and Undo puts the previous pointer back."),
    ("update.rolled-back", "decision", "A staged version failed its check at the first start, so the desk went back to the previous version and repaired any store that failed its integrity check."),
    ("update.check-failed", "decision", "An update check could not read the share or refused the bundle before running it; the row names the result, never file contents."),
]

ACTOR = "agent-desk"


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the audit tables, adding the columns older stores lack.

    Append-only means the migration only ever adds columns: each ALTER is
    tried and a duplicate-column error is ignored, so the call is safe on a
    fresh store and on one created by an earlier build.
    """
    conn.executescript(SCHEMA)
    # Light migration for stores created by earlier builds: append-only
    # means we add columns, never rewrite rows.
    for column in ("actor", "target"):
        try:
            conn.execute(f"ALTER TABLE audit ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already there
    conn.commit()


def record(
    conn: sqlite3.Connection,
    action: str,
    target: str = "",
    status: str = "ok",
    detail: str = "",
    model: str = "",
    request_bytes: int = 0,
    clock: Callable[[], float] = time.time,
) -> None:
    """Append one audited call, committed before the function returns.

    The timestamp comes from the injected clock and the actor is always
    ACTOR: the store describes calls made by this app, never by anyone else.
    detail is stored verbatim, so the caller decides how much to keep.
    """
    with conn:
        conn.execute(
            "INSERT INTO audit (ts, actor, action, target, status, model, request_bytes, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (clock(), ACTOR, action, target, status, model, request_bytes, detail),
        )


_SELECT = ("SELECT ts, actor, action, target, status, model, request_bytes,"
           " detail FROM audit")


def _as_entries(rows) -> list[dict]:
    """Turn the selected audit columns into the dicts the pages consume.

    Positions are fixed by _SELECT; the two change together.
    """
    return [
        {
            "ts": r[0],
            "actor": r[1],
            "action": r[2],
            "target": r[3],
            "status": r[4],
            "model": r[5],
            "request_bytes": r[6],
            "detail": r[7],
        }
        for r in rows
    ]


def entries(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Return the newest audit rows, newest first.

    Ordering is by row id rather than by ts, so rows written within the same
    clock tick keep their insertion order.
    """
    rows = conn.execute(
        _SELECT + " ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return _as_entries(rows)


def count(conn: sqlite3.Connection) -> int:
    """Every row in the store, not just the newest page's window."""
    row = conn.execute("SELECT COUNT(*) FROM audit").fetchone()
    return int(row[0]) if row else 0


def decision_entries(conn: sqlite3.Connection, actions, limit: int = 100) -> list[dict]:
    """Rows for the given actions only, newest first, filtered in SQL.

    The background polls (hourly excel, half-hourly calendar) fill the
    newest-100 window of a plain entries() call in a couple of days; a
    page that promises every decision must filter before the limit, not
    after it.
    """
    actions = tuple(actions)
    if not actions:
        return []
    placeholders = ",".join("?" for _ in actions)
    rows = conn.execute(
        f"{_SELECT} WHERE action IN ({placeholders}) ORDER BY id DESC LIMIT ?",
        (*actions, limit),
    ).fetchall()
    return _as_entries(rows)


def observed_actions(conn: sqlite3.Connection) -> set[str]:
    """Return the action names that appear in the store.

    Lets a page tell a vocabulary entry that has actually run from one that
    is only described.
    """
    return {r[0] for r in conn.execute("SELECT DISTINCT action FROM audit")}


def csv_bytes(conn: sqlite3.Connection) -> bytes:
    """The export Security reviews: actor, action, target, timestamp.

    RFC 4180 quoting, CRLF rows, single-line fields by construction: the
    file opens in Excel exactly as it opened here.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["actor", "action", "target", "timestamp"])
    for row in conn.execute(
        "SELECT actor, action, target, ts FROM audit ORDER BY id ASC"
    ):
        writer.writerow([row[0], row[1], row[2], format_ts(row[3])])
    return buffer.getvalue().encode("utf-8")


def format_ts(ts: float) -> str:
    """Render a stored timestamp for display and CSV export.

    Local time to the second with no UTC offset, so the string is for human
    reading only; keep the stored float for arithmetic.
    """
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def last_ok_ts(conn: sqlite3.Connection, action: str) -> float | None:
    """Return when the given action last succeeded, or None if it never has.

    Failed rows are ignored: this answers when the action last worked, not
    when it was last attempted.
    """
    row = conn.execute(
        "SELECT MAX(ts) FROM audit WHERE action = ? AND status = 'ok'", (action,)
    ).fetchone()
    return row[0] if row and row[0] is not None else None
