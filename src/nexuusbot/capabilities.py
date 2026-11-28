"""The capabilities cache: each probe gate's last result, with its age.

Ported from the teammate's capabilities probe (their Check shape: a
name, a status of available or blocked, a plain cause). The deliberate
divergence: their panel probes the real environment on every view;
ours caches. The page renders what this store holds (the stored time
travels on every card, so a stale pass never reads as current) and
probing happens only on the explicit re-test POST, where the injected
runner set runs one gate and the answer is re-cached here. The store is
the repo's usual SQLite shape: one row per gate key, the GateResult as
JSON, the stamp beside it. Building the default runner set touches
nothing (closures over the adapter bundle only), so a server can carry
it from startup and a page render never probes.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from nexuusbot.probe import gates
from nexuusbot.probe.adapters import Adapters, real_adapters
from nexuusbot.probe.core import (
    GATE_EDR,
    GATE_EMBEDDINGS,
    GATE_EXEC,
    GATE_FLOW,
    GATE_ONEDRIVE,
    GATE_UV,
    GateResult,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS gate_cache (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_ts REAL NOT NULL
);
"""

# The five P0 gates in report order, then the endpoint embeddings gate
# (ticket #95): the page's card order and the never-tested cards'
# titles and numbers. A store test pins this table to what the gate
# functions themselves return, so it cannot drift. The embeddings gate
# probes the configured LLM endpoint, not this machine, so it is not
# part of the CLI environment verdict (it stays out of GATE_KEYS).
GATES: tuple[tuple[str, int, str], ...] = (
    (GATE_EXEC, 1, "User-space execution"),
    (GATE_UV, 2, "uv bootstrap under corporate TLS"),
    (GATE_FLOW, 3, "Power Automate personal cloud flows"),
    (GATE_ONEDRIVE, 4, "OneDrive sync root"),
    (GATE_EDR, 5, "EDR / AV identity"),
    (GATE_EMBEDDINGS, 6, "Endpoint embeddings"),
)


# The injectable runner set: gate key -> zero-argument gate call. Built
# once (closures only, nothing probes), called once per re-test.
GateRunners = dict[str, Callable[[], GateResult]]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the capability tables if they are missing."""
    conn.executescript(SCHEMA)
    conn.commit()


@dataclass(frozen=True)
class CachedGate:
    """One gate's last stored result, and when the store took it."""

    key: str
    result: GateResult
    updated_ts: float

    def to_json(self) -> dict:
        """The wire form (camelCase like the other API payloads), exactly
        as a JSON body would carry it: evidence as a list."""
        result = asdict(self.result)
        result["evidence"] = list(result["evidence"])
        return {
            "key": self.key,
            "result": result,
            "updatedTs": self.updated_ts,
        }


class CapabilitiesCache:
    """Gate results in SQLite. Reading never probes anything."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float]) -> None:
        """Bind the cache to a connection and clock, creating its schema first."""
        self.conn = conn
        self.clock = clock
        ensure_schema(conn)

    def save_result(self, result: GateResult) -> CachedGate:
        """Store one gate's answer, stamped by this store's own clock:
        the same clock the page ages against, so a card never ages by
        two different clocks."""
        ts = self.clock()
        with self.conn:
            self.conn.execute(
                "INSERT INTO gate_cache (key, value, updated_ts) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_ts = excluded.updated_ts",
                (result.key, json.dumps(asdict(result), ensure_ascii=False), ts),
            )
        return CachedGate(result.key, result, ts)

    def cached(self, key: str) -> CachedGate | None:
        """The last stored result for a gate, or None. None means the
        gate has never been tested here and the page must say so, never
        fabricate."""
        row = self.conn.execute(
            "SELECT value, updated_ts FROM gate_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        result = GateResult(
            key=data["key"],
            number=data["number"],
            title=data["title"],
            status=data["status"],
            evidence=tuple(data["evidence"]),
            note=data.get("note", ""),
        )
        return CachedGate(result.key, result, float(row[1]))


def default_gate_runners(
    workdir: Path,
    adapters: Adapters | None = None,
    embeddings: Callable[[], object] | None = None,
) -> GateRunners:
    """The production runner set: each gate bound to the real adapters
    over the given workdir (the app passes one beside its data dir).

    `embeddings` (ticket #95) is a zero-argument factory returning the
    embeddings client for gate 6; it is called only when the re-test
    POST runs that gate, and building the factory's product (the
    settings-backed embedder) touches nothing. Without the factory the
    gate reads UNKNOWN, the honest never-asked state.

    Building the set probes nothing: every entry is a plain closure, so
    no subprocess, network call, file write or process listing happens
    until the re-test POST calls exactly one entry.
    """
    bundle = adapters if adapters is not None else real_adapters()
    workdir = Path(workdir)
    return {
        GATE_EXEC: lambda: gates.gate_exec_user_space(
            bundle.runner, workdir, bundle.write_text
        ),
        GATE_UV: lambda: gates.gate_uv_tls_bootstrap(
            bundle.runner, workdir, bundle.find_uv
        ),
        GATE_FLOW: lambda: gates.gate_power_automate(bundle.reach),
        GATE_ONEDRIVE: lambda: gates.gate_onedrive(
            bundle.discover_onedrive, workdir, bundle.write_text, bundle.copy_file
        ),
        GATE_EDR: lambda: gates.gate_edr_identity(bundle.list_processes),
        GATE_EMBEDDINGS: lambda: gates.gate_embeddings(
            embeddings() if embeddings is not None else None
        ),
    }
