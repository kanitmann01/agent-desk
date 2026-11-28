"""The layout store: the dashboard's card arrangement in SQLite.

Every dashboard card has a stable key: the four builtins (``sales``,
``commitments``, ``research``, ``skills``) and, for plugin cards, the
plugin id. The store keeps one row per key: the saved position, a hidden
flag and an optional custom title, so the arrangement survives reloads
and browser changes. It follows the settings and memory store patterns:
``ensure_schema`` on construct, ``with conn`` writes, no timestamps (so
no clock). There is deliberately nothing else in a row: order and
visibility are the whole model.

The pinned save semantics (issue #66): POST carries the full desired
layout; the array order is the card order, and a row the save does not
mention is dropped. That rule is also the pruning story: a plugin that
is no longer installed is never listed by :meth:`LayoutStore.resolve`
(its row is kept silently, so an uninstall/reinstall cycle restores the
arrangement), and the next full save, posted from what the listing
actually said, drops the stale row.
"""

import sqlite3

# The stable builtin card keys, in canonical order: the arrangement a
# fresh desk renders before anyone customizes anything.
BUILTIN_KEYS = ("sales", "commitments", "research", "skills")

# A title longer than this is a paste accident, not a name.
MAX_TITLE = 120

SCHEMA = """
CREATE TABLE IF NOT EXISTS layout (
  card_key TEXT PRIMARY KEY,
  position INTEGER NOT NULL,
  hidden INTEGER NOT NULL DEFAULT 0,
  title TEXT
);
"""


class LayoutError(ValueError):
    """A refused layout save, carrying the named API error code.

    ``code`` is one of ``layout:invalid-card``, ``layout:duplicate-card``
    or ``layout:unknown-card``; ``key`` names the offending card when one
    can be named.
    """

    def __init__(self, code: str, message: str, key: str | None = None) -> None:
        """Build a refusal from its named API code and, when known, the card key.

        The message is the sentence for a human; code is what the handler switches
        on.
        """
        super().__init__(message)
        self.code = code
        self.key = key


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the layout table and commit; safe to run on every open."""
    conn.executescript(SCHEMA)
    conn.commit()


def parse_layout(entries: object, known_keys: set[str]) -> list[dict]:
    """A POSTed cards array as storable rows, or a named refusal.

    ``known_keys`` is the card universe at save time: the builtins plus
    the ids of installed plugins. Anything else is the named
    ``layout:unknown-card`` error, so a typo'd builtin and a stale plugin
    id fail loudly instead of being stored forever.
    """

    def refuse(code: str, message: str, key: str | None = None):
        """The named refusal for one invalid entry, as an exception to raise."""
        return LayoutError(code, message, key)

    if not isinstance(entries, list):
        raise refuse("layout:invalid-card", "expected a cards array")
    parsed: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise refuse("layout:invalid-card", "each card is an object")
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            raise refuse("layout:invalid-card", "each card names its key")
        key = key.strip()
        if key in seen:
            raise refuse("layout:duplicate-card", f"card {key} appears twice", key)
        seen.add(key)
        if key not in known_keys:
            raise refuse("layout:unknown-card", f"unknown card: {key}", key)
        hidden = entry.get("hidden", False)
        if not isinstance(hidden, bool):
            raise refuse("layout:invalid-card", f"card {key}: hidden is a boolean", key)
        title = entry.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise refuse("layout:invalid-card", f"card {key}: title is a string or null", key)
            title = title.strip()
            if len(title) > MAX_TITLE:
                raise refuse(
                    "layout:invalid-card",
                    f"card {key}: titles are capped at {MAX_TITLE} characters", key)
            if not title:
                title = None  # a blank title means "back to the default name"
        parsed.append({"key": key, "hidden": hidden, "title": title})
    return parsed


class LayoutStore:
    """Order, visibility and titles per card key; resolution is a read."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Open the store on a connection, creating the table if it is absent."""
        self.conn = conn
        ensure_schema(conn)

    # -- writes -----------------------------------------------------------

    def replace(self, cards: list[dict]) -> None:
        """Store the full desired layout; the array order is the order.

        Rows the save does not mention are dropped (full-replace, so the
        client and the store can never drift), which is also how a stale
        plugin row is pruned once its plugin is gone.
        """
        with self.conn:
            self.conn.execute("DELETE FROM layout")
            self.conn.executemany(
                "INSERT INTO layout (card_key, position, hidden, title)"
                " VALUES (?, ?, ?, ?)",
                [
                    (card["key"], position, 1 if card["hidden"] else 0, card["title"])
                    for position, card in enumerate(cards)
                ],
            )

    # -- reads ------------------------------------------------------------

    def rows(self) -> dict[str, dict]:
        """The raw stored rows keyed by card key (test and prune truth)."""
        result = self.conn.execute(
            "SELECT card_key, position, hidden, title FROM layout"
        ).fetchall()
        return {
            row[0]: {"position": row[1], "hidden": bool(row[2]), "title": row[3]}
            for row in result
        }

    def resolve(self, plugin_keys: list[str]) -> list[dict]:
        """Every card that exists right now, in render order.

        Stored rows come first in their saved order; cards the store has
        never seen follow in canonical order (builtins, then the caller's
        plugin order, which is the runtime's listing order). Rows whose
        key is neither a builtin nor a currently installed plugin are
        kept in the database but never listed: an uninstalled plugin is
        honestly absent until it is installed again.
        """
        known = list(BUILTIN_KEYS) + [k for k in plugin_keys if k not in BUILTIN_KEYS]
        known_set = set(known)
        stored = self.rows()
        ordered = sorted(
            (key for key in stored if key in known_set),
            key=lambda key: stored[key]["position"],
        )
        unseen = [key for key in known if key not in stored]
        return [
            {
                "key": key,
                "hidden": stored[key]["hidden"],
                "title": stored[key]["title"],
            }
            if key in stored
            else {"key": key, "hidden": False, "title": None}
            for key in ordered + unseen
        ]


def resolved_layout(store: LayoutStore | None, plugin_keys: list[str]) -> list[dict]:
    """The resolved layout whether or not a store opened.

    Without a store (its sqlite file could not open) the dashboard keeps
    the canonical default arrangement instead of failing: reads degrade
    honestly, saves refuse (the handler answers 503 for those).
    """
    if store is None:
        return [
            {"key": key, "hidden": False, "title": None}
            for key in list(BUILTIN_KEYS) + [
                k for k in plugin_keys if k not in BUILTIN_KEYS
            ]
        ]
    return store.resolve(plugin_keys)
