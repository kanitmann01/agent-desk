"""Skills: versioned SKILL.md documents, honest to undo.

A skill is a saved ask: one click re-runs it through the same loop as
research, with the same widget context and the same audit trail. Every
activation and deactivation lands in the version history, so "undo" is a
fact, not a promise. The markdown follows the agentskills.io shape:
frontmatter with a name and a description inside the length limits.
"""

import re
import sqlite3
import time
from collections.abc import Callable

NAME_MAX = 64
DESCRIPTION_MAX = 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,
  prompt TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_versions (
  id INTEGER PRIMARY KEY,
  skill_id INTEGER NOT NULL,
  version INTEGER NOT NULL,
  active INTEGER NOT NULL,
  ts REAL NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class SkillError(Exception):
    """The skill name or description breaks the format contract."""


def slugify(name: str) -> str:
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
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    def activate(self, name: str, description: str, prompt: str) -> dict:
        """Create (or re-activate) a skill and record the version."""
        slug = slugify(name)
        if not description.strip():
            raise SkillError("a skill without a description is not a skill")
        if len(description) > DESCRIPTION_MAX:
            raise SkillError("skill description exceeds 1024 characters")
        now = self.clock()
        row = self.conn.execute("SELECT id, active FROM skills WHERE name = ?", (slug,)).fetchone()
        with self.conn:
            if row is None:
                cursor = self.conn.execute(
                    "INSERT INTO skills (name, description, prompt, active, created_ts)"
                    " VALUES (?, ?, ?, 1, ?)",
                    (slug, description, prompt, now),
                )
                skill_id = cursor.lastrowid
                version = 1
            else:
                skill_id = row[0]
                version = self._next_version(skill_id)
                self.conn.execute(
                    "UPDATE skills SET description = ?, prompt = ?, active = 1 WHERE id = ?",
                    (description, prompt, skill_id),
                )
            self.conn.execute(
                "INSERT INTO skill_versions (skill_id, version, active, ts, note)"
                " VALUES (?, ?, 1, ?, ?)",
                (skill_id, version, now, "activated"),
            )
        return {"id": skill_id, "name": slug, "version": version, "active": True}

    def deactivate(self, skill_id: int) -> dict:
        """The undo: the prior state is the version history's to prove."""
        row = self.conn.execute("SELECT id, active FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            raise SkillError(f"no skill {skill_id}")
        now = self.clock()
        version = self._next_version(skill_id)
        with self.conn:
            self.conn.execute("UPDATE skills SET active = 0 WHERE id = ?", (skill_id,))
            self.conn.execute(
                "INSERT INTO skill_versions (skill_id, version, active, ts, note)"
                " VALUES (?, ?, 0, ?, ?)",
                (skill_id, version, now, "deactivated (undo)"),
            )
        return {"id": skill_id, "version": version, "active": False}

    def _next_version(self, skill_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM skill_versions WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
        return int(row[0])

    def active(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, description, prompt FROM skills WHERE active = 1 ORDER BY id"
        ).fetchall()
        return [{"id": r[0], "name": r[1], "description": r[2], "prompt": r[3]} for r in rows]

    def get(self, skill_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id, name, description, prompt, active FROM skills WHERE id = ?",
            (skill_id,),
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "name": row[1], "description": row[2], "prompt": row[3], "active": bool(row[4])}

    def history(self, skill_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT version, active, ts, note FROM skill_versions WHERE skill_id = ? ORDER BY version",
            (skill_id,),
        ).fetchall()
        return [{"version": r[0], "active": bool(r[1]), "ts": r[2], "note": r[3]} for r in rows]

    def markdown(self, skill_id: int) -> str:
        skill = self.get(skill_id)
        if skill is None:
            raise SkillError(f"no skill {skill_id}")
        return render_skill_md(skill["name"], skill["description"], skill["prompt"])
