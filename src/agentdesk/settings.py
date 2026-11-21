"""Settings: toggles and the typed endpoint, with defaults that need no
documentation.

The controls are booleans or small choices; the endpoint rows (base URL,
API key, model) are free text the user types once in the app, so research
works without touching environment variables. The inbox reads its
quiet-hours and budget values from here, so what this page shows is what
the app enforces. The key row is a secret: callers render its masked
state, never the value.
"""

import sqlite3
import threading
import time
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# The whole surface. Read-only indicators are not settings and live
# elsewhere; anything here is either a bool, a small ordered choice, or
# one of the typed endpoint strings.
TOGGLES = {
    "excel_enabled": True,
    "calendar_enabled": True,
    "endpoint_enabled": True,
    "quiet_hours": True,
    "mail_enabled": False,  # mail digest: off until the user turns it on
    "sample_data": False,  # demo seed (#68): off until the user asks for it
    # Semantic recall (ticket #95): embeddings stay inactive until the
    # embeddings probe passes on the capabilities page, so this default
    # on changes nothing until the endpoint answers the probe.
    "semantic_memory": True,
    # Suggestion sends column names only when this is on. Off sends up to 5 rows.
    "suggest_headers_only": False,
    # The memory loop (memory/loop.py): capture facts from what you do,
    # review them before they are saved unless auto-approve is on, and
    # one switch per channel capture reads. Auto-approve defaults on for
    # data folders born on this build (spec 016 section 8); create_server
    # stores an explicit False for a folder an earlier build already
    # used, so an existing desk keeps "ask me first".
    "memory_capture": True,
    "memory_auto_approve": True,
    "memory_capture_assistant": True,
    "memory_capture_research": True,
    "memory_capture_workbook": True,
    # Run feedback on the agents page captures on its own channel (#170).
    "memory_capture_agents": True,
    # Learned focus topics (spec 016 section 8): five or more similar
    # asks naming a memory entity add it to the learned profile. Off
    # stops the learning; what was learned stays until removed.
    "learn_topics": True,
    # The profile review (spec 016 section 6.5): every ten new asks the
    # loop sends the last 24 to the company endpoint and applies only
    # grounded, injection-scanned learned lines. Off stops the review;
    # what was learned stays until removed. Needs an endpoint too (the
    # endpoint_enabled switch and a connection or startup endpoint the
    # hub can resolve), not just this switch.
    "learn_profile": True,
    # Spec §8: the desk acts by itself and every change it makes is logged
    # in the action ledger with Undo. The four ask-first classes are
    # enforced in code (ledger.may_act), not by this switch.
    "autonomy": True,
    # Recommendations (spec 016 §8): deadlines saved in memory become
    # inbox cards on their own. Off stops creating; existing cards stay.
    "recommendations": True,
    "recommend_deadlines": True,
    "recommend_meetings": True,
    # Ranking (spec 016 section 6.3): the endpoint rewrites a waiting
    # recommendation's why line. Off keeps the rule's own why line.
    "recommend_model_rank": True,
    # Self-update (spec 016 section 6.8): shipped off until Security signs
    # off on the launcher stub. Off still reads the share and reports a
    # newer version, but copies and runs nothing.
    "auto_update": False,
    "auto_update_plugins": False,
    # The self-improving skills (spec 016 section 8, confirmed by Kanit):
    # a repeated ask becomes an active skill by itself, queued feedback
    # refines desk-made skills through the endpoint, and the weekly
    # curator moves unused unpinned desk-made skills toward archived.
    # All three touch only agent-made skills.
    "skills_auto_create": True,
    "skills_auto_refine": True,
    "skills_curator": True,
}
CHOICES = {
    "daily_cap": [3, 1, 0],  # notifications per day; 0 means inbox only
    "plugin_instance_cap": [6, 5, 4, 3, 2, 1],
    # How far ahead a saved deadline becomes a recommendation (spec 016 §8).
    "recommend_horizon_days": [14, 7, 30],
    # The score at or above which a ranked recommendation is shown
    # (spec 016 section 6.3). Below it, the card rests until tomorrow.
    "recommend_threshold": [7, 5, 9],
    # The agent loop's pass interval (spec 016 section 8); 0 turns the
    # loop off, including the startup desk check.
    "agent_loop_minutes": [60, 30, 240, 0],
}
# The embeddings model default below is the spec's Further Notes
# default (decision: text-embedding-3-small); agentdesk.memory.embed
# holds the same constant, and a test pins the two together.
EMBEDDINGS_MODEL_DEFAULT = "text-embedding-3-small"
TEXT_KEYS = {
    # The legacy endpoint rows (spec 018 #234): read-only fallback since
    # the connections surface landed. The migration leaves base, model
    # and the research URL in place (the resolution hub's environment
    # leg still reads them) and clears the two secret columns once the
    # keys have landed in the keychain.
    "llm_base": "",  # OpenAI-compatible base URL
    "llm_key": "",   # legacy API key; cleared on migration, masked wherever rendered
    "llm_model": "",  # empty means the adapter's default model
    "embeddings_model": EMBEDDINGS_MODEL_DEFAULT,  # the semantic recall model (#95)
    "mail_folder": "",  # the .eml folder the mail watcher polls when enabled
    "mail_self_address": "",  # the user's own address; empty means mail self-detection is off
    "registry_path": "",  # the local registry checkout the plugins page browses; empty means auto
    "extra_allowed_hosts": "",  # host[:port] entries the guard admits beyond loopback (#61); comma or space separated
    # Presentation-agent calls only. Other agents stay on the 10s adapter cap.
    "presentation_timeout_s": "30",
    # Web research for a presentation run (the migrated pair's fallback half).
    "research_provider_url": "",
    "research_provider_key": "",  # legacy research key; cleared on migration
    # The share folder IT publishes versions to (spec 016 section 5.6).
    "update_channel": "",
}
DEFAULTS = {
    **TOGGLES,
    "daily_cap": 3,
    "plugin_instance_cap": 6,
    "recommend_horizon_days": 30,
    "recommend_threshold": 7,
    # The agent loop's pass interval in minutes (spec 016 section 8).
    "agent_loop_minutes": 60,
    **TEXT_KEYS,
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the settings table and commit; safe to run on every open."""
    conn.executescript(SCHEMA)
    conn.commit()


class SettingsStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        """Open the store on a connection, with the lock that serializes it.

        One connection is shared across request threads, so every statement runs
        under the lock; clock is injectable for tests.
        """
        self.conn = conn
        self.clock = clock
        # One lock around every statement: the connection is shared
        # across request threads (check_same_thread=False), the guard
        # reads it on EVERY request, and without this the interleaved
        # cursor use raises InterfaceError on the hot path (the same
        # shared-connection class the calendar bridge fixed with a
        # lock; see the research store for the third instance).
        self._lock = threading.RLock()
        ensure_schema(conn)

    def get(self, key: str):
        """The stored value, or the default. Unknown keys are not settings."""
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        with self._lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return DEFAULTS[key]
        default = DEFAULTS[key]
        if isinstance(default, bool):
            return row[0] == "1"
        if key in TEXT_KEYS:
            return row[0]
        return int(row[0])

    def set(self, key: str, value) -> None:
        """Store one value, coerced by the key's default type.

        A choice outside the allowed list raises ValueError; booleans are stored as
        "1"/"0" and text exactly as given.
        """
        if key not in DEFAULTS:
            raise KeyError(f"unknown setting: {key}")
        if isinstance(DEFAULTS[key], bool):
            stored = "1" if value else "0"
        elif key in TEXT_KEYS:
            stored = str(value)
        else:
            if value not in CHOICES[key]:
                raise ValueError(f"{key} must be one of {CHOICES[key]}")
            stored = str(value)
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, stored),
            )

    def toggle(self, key: str):
        """Flip a boolean; cycle a choice. Returns the new value."""
        current = self.get(key)
        if key in TOGGLES:
            new = not current
        else:
            options = CHOICES[key]
            new = options[(options.index(current) + 1) % len(options)]
        self.set(key, new)
        return new

    def all(self) -> dict:
        """Every setting with its effective value, defaults included."""
        return {key: self.get(key) for key in DEFAULTS}
