"""Skills: versioned SKILL.md documents, honest to undo.

A skill is a saved ask: one click re-runs it through the same loop as
research, with the same widget context and the same audit trail. Every
activation and deactivation lands in the version history, so "undo" is a
fact, not a promise. The markdown follows the agentskills.io shape:
frontmatter with a name and a description inside the length limits.

The lifecycle columns (spec 016 section 5.5) say who made a skill and
where it stands: `active` keeps its old meaning (runs on the dashboard),
`state` is the curator's word (active, stale, archived), a pinned skill
is exempt from the curator and from refine, and use_count with
last_used_ts feed the staleness clock. Nothing here ever deletes a
skills or skill_versions row.
"""

import functools
import re
import sqlite3
import threading
import time
from collections.abc import Callable

from agentdesk.repetition.refine import first_threat

NAME_MAX = 64
DESCRIPTION_MAX = 1024
# The refined prompt's ceiling (spec 016 section 6.6): a DESCRIPTION_MAX-style
# bound for the prompt, which had no limit before ticket 10.
PROMPT_MAX = 4000

# The lifecycle states (Hermes tools/skill_usage.py spelling).
STATE_ACTIVE = "active"
STATE_STALE = "stale"
STATE_ARCHIVED = "archived"
STATES = (STATE_ACTIVE, STATE_STALE, STATE_ARCHIVED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,
  prompt TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_ts REAL NOT NULL,
  created_by TEXT NOT NULL DEFAULT 'user',
  state TEXT NOT NULL DEFAULT 'active',
  pinned INTEGER NOT NULL DEFAULT 0,
  use_count INTEGER NOT NULL DEFAULT 0,
  last_used_ts REAL
);
CREATE TABLE IF NOT EXISTS skill_versions (
  id INTEGER PRIMARY KEY,
  skill_id INTEGER NOT NULL,
  version INTEGER NOT NULL,
  active INTEGER NOT NULL,
  ts REAL NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS curator_state (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the skill and version tables and commit; safe on every open.

    The migration is append-only, the inbox store's pattern: each column a
    later build introduced is added with ALTER and a duplicate-column error
    is ignored, so an older store comes forward without rewriting a row.
    """
    conn.executescript(SCHEMA)
    for ddl in (
        "ALTER TABLE skills ADD COLUMN created_by TEXT NOT NULL DEFAULT 'user'",
        "ALTER TABLE skills ADD COLUMN state TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE skills ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE skills ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE skills ADD COLUMN last_used_ts REAL",
        "ALTER TABLE skill_versions ADD COLUMN prompt TEXT NOT NULL DEFAULT ''",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # column already there
    conn.commit()


class SkillError(Exception):
    """The skill name or description breaks the format contract."""


def _serialized(method):
    """Every read and write holds the store's one lock, the inbox store's
    pattern. The connection is shared (check_same_thread=False) by the
    server's request threads and the agent loop's skills and curator
    steps; Python's sqlite3 connection keeps one implicit transaction, so
    a request-thread refine committing mid-way through a loop-thread
    set_state can commit the other's half-done write, and the
    MAX(version)+1 read races another writer. An RLock, because methods
    call each other (markdown reads through get)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        """Run one store method with the store's re-entrant lock held."""
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


def slugify(name: str) -> str:
    """A skill name as a stable slug: lower case, single dashes, length-capped.

    A name that leaves nothing behind becomes "skill", because an empty slug
    cannot name a row.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:NAME_MAX].rstrip("-") or "skill"


def render_skill_md(name: str, description: str, prompt: str) -> str:
    """The agentskills.io-shaped document for one saved ask."""
    slug = slugify(name)
    if len(slug) > NAME_MAX:
        raise SkillError("skill name exceeds 64 characters")
    if len(description) > DESCRIPTION_MAX:
        raise SkillError("skill description exceeds 1024 characters")
    return (
        f"---\nname: {slug}\ndescription: {description}\n---\n\n"
        f"# {name}\n\n"
        "Run the saved ask below through the research loop with the current"
        " widget context attached.\n\n"
        f"```\n{prompt}\n```\n"
    )


class SkillStore:
    """Skills and their versions, thread-safe: every method serializes on
    one lock (see _serialized). The default lock is the store's own; two
    stores sharing one connection (the default boot's repetition.sqlite3)
    are handed the same lock so the connection really is serial."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time,
                 lock: threading.RLock | None = None) -> None:
        """Open the store on a connection, creating both tables if they
        are absent.

        lock is injectable so stores sharing a connection can share its
        one lock; the store's methods are re-entrant under it.
        """
        self.conn = conn
        self.clock = clock
        self._lock = lock if lock is not None else threading.RLock()
        with self._lock:
            ensure_schema(conn)

    @_serialized
    def activate(self, name: str, description: str, prompt: str,
                 created_by: str = "user") -> dict:
        """Create (or re-activate) a skill and record the version.

        Re-activation keeps the row's creator: a user skill never becomes
        agent-made because the desk noticed the same ask again, and an
        agent skill stays the desk's through a user's re-acceptance.
        """
        slug = slugify(name)
        if not description.strip():
            raise SkillError("a skill without a description is not a skill")
        if len(description) > DESCRIPTION_MAX:
            raise SkillError("skill description exceeds 1024 characters")
        now = self.clock()
        row = self.conn.execute(
            "SELECT id, active, created_by FROM skills WHERE name = ?", (slug,)
        ).fetchone()
        with self.conn:
            if row is None:
                cursor = self.conn.execute(
                    "INSERT INTO skills (name, description, prompt, active,"
                    " created_ts, created_by, state)"
                    " VALUES (?, ?, ?, 1, ?, ?, 'active')",
                    (slug, description, prompt, now, created_by),
                )
                skill_id = cursor.lastrowid
                version = 1
            else:
                skill_id = row[0]
                created_by = row[2]  # the row's own creator stays
                version = self._next_version(skill_id)
                self.conn.execute(
                    "UPDATE skills SET description = ?, prompt = ?, active = 1,"
                    " state = 'active' WHERE id = ?",
                    (description, prompt, skill_id),
                )
            self.conn.execute(
                "INSERT INTO skill_versions (skill_id, version, active, ts, note, prompt)"
                " VALUES (?, ?, 1, ?, ?, ?)",
                (skill_id, version, now, "activated", prompt),
            )
        return {"id": skill_id, "name": slug, "version": version, "active": True,
                "description": description, "prompt": prompt, "created_by": created_by}

    @_serialized
    def deactivate(self, skill_id: int) -> dict:
        """The undo: the prior state is the version history's to prove."""
        row = self.conn.execute("SELECT id, active, prompt FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            raise SkillError(f"no skill {skill_id}")
        now = self.clock()
        version = self._next_version(skill_id)
        with self.conn:
            self.conn.execute("UPDATE skills SET active = 0 WHERE id = ?", (skill_id,))
            self.conn.execute(
                "INSERT INTO skill_versions (skill_id, version, active, ts, note, prompt)"
                " VALUES (?, ?, 0, ?, ?, ?)",
                (skill_id, version, now, "deactivated (undo)", row[2]),
            )
        return {"id": skill_id, "version": version, "active": False}

    @_serialized
    def refine(self, skill_id: int, prompt: str, note: str) -> dict:
        """Store a better prompt as a new version row (spec 016 section 6.6).

        Refused for a skill the desk did not make, for a pinned skill, for
        an empty or over-length prompt, and for a prompt the strict threat
        scan refuses. Nothing is written on a refusal.
        """
        row = self.conn.execute(
            "SELECT id, created_by, pinned, prompt FROM skills WHERE id = ?",
            (skill_id,),
        ).fetchone()
        if row is None:
            raise SkillError(f"no skill {skill_id}")
        if row[1] != "agent":
            raise SkillError("only skills the desk made can be refined")
        if row[2]:
            raise SkillError("a pinned skill is not refined")
        if not prompt or not prompt.strip():
            raise SkillError("a refined prompt cannot be empty")
        if len(prompt) > PROMPT_MAX:
            raise SkillError(f"a refined prompt exceeds {PROMPT_MAX} characters")
        threat = first_threat(prompt)
        if threat is not None:
            raise SkillError(threat)
        now = self.clock()
        version = self._next_version(skill_id)
        with self.conn:
            self.conn.execute("UPDATE skills SET prompt = ? WHERE id = ?",
                              (prompt, skill_id))
            self.conn.execute(
                "INSERT INTO skill_versions (skill_id, version, active, ts, note, prompt)"
                " VALUES (?, ?, 1, ?, ?, ?)",
                (skill_id, version, now, note, prompt),
            )
        return {"id": skill_id, "version": version, "prompt": prompt}

    @_serialized
    def set_state(self, skill_id: int, state: str, *,
                  active: bool | None = None) -> dict:
        """Move a skill between the curator's states (spec 016 section 5.5).

        archived forces active=0; active sets active=1 (the pinned case is
        coming back from archived); stale keeps the active flag it finds,
        so a stale skill still runs. The change lands in the version
        history so the trail stays honest about when it stopped running.

        active overrides the derived flag, for the skill-state undo alone:
        the undo restores the exact pair its capture holds, because the
        pair it found can no longer be re-derived (an archived skill that
        was stale was running when it was captured, and stale keeps the
        flag rather than setting it).
        """
        if state not in STATES:
            raise SkillError(f"unknown skill state {state}")
        row = self.conn.execute(
            "SELECT id, active, state FROM skills WHERE id = ?", (skill_id,)
        ).fetchone()
        if row is None:
            raise SkillError(f"no skill {skill_id}")
        if active is None:
            active = 0 if state == STATE_ARCHIVED else (
                1 if state == STATE_ACTIVE else row[1])
        flag = 1 if active else 0
        now = self.clock()
        version = self._next_version(skill_id)
        with self.conn:
            self.conn.execute(
                "UPDATE skills SET state = ?, active = ? WHERE id = ?",
                (state, flag, skill_id),
            )
            self.conn.execute(
                "INSERT INTO skill_versions (skill_id, version, active, ts, note)"
                " VALUES (?, ?, ?, ?, ?)",
                (skill_id, version, flag, now, f"state: {state}"),
            )
        return {"id": skill_id, "state": state, "active": bool(flag)}

    @_serialized
    def pin(self, skill_id: int, pinned: bool) -> dict:
        """Pin a skill out of the curator and out of refine, or release it."""
        row = self.conn.execute("SELECT id FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            raise SkillError(f"no skill {skill_id}")
        with self.conn:
            self.conn.execute("UPDATE skills SET pinned = ? WHERE id = ?",
                              (1 if pinned else 0, skill_id))
        return {"id": skill_id, "pinned": bool(pinned)}

    @_serialized
    def record_use(self, skill_id: int) -> None:
        """Count one run: use_count up by one, last_used_ts to now.

        A no-op for an unknown id: the caller has already named a skill it
        verified, and a usage counter must never break a run.
        """
        with self.conn:
            self.conn.execute(
                "UPDATE skills SET use_count = use_count + 1, last_used_ts = ?"
                " WHERE id = ?",
                (self.clock(), skill_id),
            )

    @_serialized
    def _next_version(self, skill_id: int) -> int:
        """The next version for a skill: its history's high-water mark plus one."""
        row = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM skill_versions WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
        return int(row[0])

    @_serialized
    def active(self) -> list[dict]:
        """Every active skill, oldest first, each with the ask it re-runs."""
        rows = self.conn.execute(
            "SELECT id, name, description, prompt FROM skills WHERE active = 1 ORDER BY id"
        ).fetchall()
        return [{"id": r[0], "name": r[1], "description": r[2], "prompt": r[3]} for r in rows]

    @_serialized
    def all_skills(self) -> list[dict]:
        """Every skill with its lifecycle columns, oldest first (the settings page)."""
        rows = self.conn.execute(_SKILL_COLUMNS + " ORDER BY id").fetchall()
        return [_skill_row(r) for r in rows]

    @_serialized
    def agent_skills(self) -> list[dict]:
        """The desk-made skills with their lifecycle columns, oldest first."""
        rows = self.conn.execute(
            _SKILL_COLUMNS + " WHERE created_by = 'agent' ORDER BY id"
        ).fetchall()
        return [_skill_row(r) for r in rows]

    @_serialized
    def get(self, skill_id: int) -> dict | None:
        """One skill by id, active or not, or None when the id is unknown."""
        row = self.conn.execute(
            _SKILL_COLUMNS + " WHERE id = ?", (skill_id,)
        ).fetchone()
        if row is None:
            return None
        return _skill_row(row)

    @_serialized
    def history(self, skill_id: int) -> list[dict]:
        """Every recorded version of a skill, oldest first, deactivations included."""
        rows = self.conn.execute(
            "SELECT version, active, ts, note FROM skill_versions WHERE skill_id = ? ORDER BY version",
            (skill_id,),
        ).fetchall()
        return [{"version": r[0], "active": bool(r[1]), "ts": r[2], "note": r[3]} for r in rows]

    def markdown(self, skill_id: int) -> str:
        """The SKILL.md text for one skill.

        Raises SkillError for an unknown id: a document that names no skill would be
        worse than a refusal.
        """
        skill = self.get(skill_id)
        if skill is None:
            raise SkillError(f"no skill {skill_id}")
        return render_skill_md(skill["name"], skill["description"], skill["prompt"])

    # -- the curator's snapshot and restore ---------------------------------

    @_serialized
    def snapshot_rows(self) -> dict:
        """The agent skills and their version rows, as a snapshot payload.

        The curator writes this before it changes anything, so a rollback
        has the whole picture: every column of the desk-made skills and
        every version row they own, as named dicts (a snapshot nobody can
        misread by column order).
        """
        skills = self.conn.execute(
            "SELECT id, name, description, prompt, active, created_ts,"
            " created_by, state, pinned, use_count, last_used_ts"
            " FROM skills WHERE created_by = 'agent' ORDER BY id"
        ).fetchall()
        ids = [row[0] for row in skills]
        versions: list[tuple] = []
        if ids:
            placeholders = ",".join("?" for _ in ids)
            versions = self.conn.execute(
                "SELECT id, skill_id, version, active, ts, note, prompt"
                f" FROM skill_versions WHERE skill_id IN ({placeholders})"
                " ORDER BY skill_id, version",
                ids,
            ).fetchall()
        return {
            "skills": [
                {"id": r[0], "name": r[1], "description": r[2], "prompt": r[3],
                 "active": r[4], "created_ts": r[5], "created_by": r[6],
                 "state": r[7], "pinned": r[8], "use_count": r[9],
                 "last_used_ts": r[10]}
                for r in skills
            ],
            "versions": [
                {"id": r[0], "skill_id": r[1], "version": r[2], "active": r[3],
                 "ts": r[4], "note": r[5], "prompt": r[6]}
                for r in versions
            ],
        }

    @_serialized
    def restore_rows(self, payload: dict) -> None:
        """Put a snapshot's rows back (Hermes rollback, row-shaped).

        Restore never deletes: skills are updated in place (their rows are
        never gone) and version rows are inserted only where their id is
        absent, so the row counts can only stay or grow. A row the
        snapshot holds that this build does not know is skipped, never
        guessed at.
        """
        skills = payload.get("skills") or []
        versions = payload.get("versions") or []
        with self.conn:
            for row in skills:
                if not isinstance(row, dict) or "id" not in row:
                    continue
                self.conn.execute(
                    "UPDATE skills SET name = ?, description = ?, prompt = ?,"
                    " active = ?, created_ts = ?, created_by = ?, state = ?,"
                    " pinned = ?, use_count = ?, last_used_ts = ? WHERE id = ?",
                    (row.get("name"), row.get("description"), row.get("prompt"),
                     1 if row.get("active") else 0, row.get("created_ts"),
                     row.get("created_by", "agent"), row.get("state", "active"),
                     1 if row.get("pinned") else 0, row.get("use_count", 0),
                     row.get("last_used_ts"), row["id"]),
                )
            for row in versions:
                if not isinstance(row, dict) or "id" not in row:
                    continue
                self.conn.execute(
                    "INSERT OR IGNORE INTO skill_versions"
                    " (id, skill_id, version, active, ts, note, prompt)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (row["id"], row.get("skill_id"), row.get("version"),
                     1 if row.get("active") else 0, row.get("ts"),
                     row.get("note", ""), row.get("prompt", "")),
                )

    @_serialized
    def curator_state_value(self, key: str) -> str | None:
        """One value from the curator's k/v table, or None when unset."""
        row = self.conn.execute(
            "SELECT v FROM curator_state WHERE k = ?", (key,)
        ).fetchone()
        return None if row is None else row[0]

    @_serialized
    def set_curator_state(self, key: str, value: str) -> None:
        """Remember one curator value (the interval clock's home)."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO curator_state (k, v) VALUES (?, ?)"
                " ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                (key, value),
            )


_SKILL_COLUMNS = (
    "SELECT id, name, description, prompt, active, created_by, state,"
    " pinned, use_count, last_used_ts, created_ts FROM skills"
)


def _skill_row(row) -> dict:
    """One skills-table row as the dict the surfaces read."""
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "prompt": row[3],
        "active": bool(row[4]),
        "created_by": row[5],
        "state": row[6],
        "pinned": bool(row[7]),
        "use_count": row[8],
        "last_used_ts": row[9],
        "created_ts": row[10],
    }
