"""The fallback backend: the desk's existing fixed loop, wrapped as a turn.

When the side-car is absent, a turn is exactly what the desk did before
this package existed: one pass of the supervised loop's fixed step
registry. The pass's step rows become the turn's note, and every ledger
entry the pass recorded becomes one action carrying the entry's own
undo kind, so a caller sees the same ledger toll a side-car turn pays.
The fallback is not a regression path; it is how the POC stays optional
on machines that cannot run the side-car.
"""

from agentdesk.engine import vocab as engine_store

BACKEND = "fallback"

# How many recent entries the before/after scan reads. A pass is short
# local database work; the cap keeps a pathological ledger from making
# the scan unbounded while staying far above what one pass can record.
ENTRY_SCAN_LIMIT = 200


def run(loop) -> engine_store.TurnResult:
    """Run one pass of the fixed loop and answer its actions.

    `loop` is the desk's AgentLoop (or anything with run_pass() and a
    reachable ledger). Entries recorded during the pass are matched by
    id, so an injected or advanced clock cannot pull an older entry into
    the turn.
    """
    ledger = getattr(loop, "ledger", None)
    if ledger is None:
        ledger = getattr(getattr(loop, "server", None), "ledger", None)
    before: set[str] = set()
    if ledger is not None:
        before = {entry.id for entry in ledger.entries(limit=ENTRY_SCAN_LIMIT)}
    rows = loop.run_pass()
    actions: list[engine_store.Action] = []
    if ledger is not None:
        fresh = [entry for entry in ledger.entries(limit=ENTRY_SCAN_LIMIT)
                 if entry.id not in before]
        newest_last = sorted(fresh, key=lambda entry: entry.ts)
        actions = [
            engine_store.Action(
                tool=entry.action,
                undo_kinds=(entry.undo_kind,),
                why=entry.why,
                entry_id=entry.id,
            )
            for entry in newest_last
        ]
    note = ", ".join(
        f"{row.get('name')} {'ok' if row.get('ok') else 'failed'}"
        for row in rows if isinstance(row, dict)
    )
    return engine_store.TurnResult(backend=BACKEND, actions=tuple(actions),
                                   events=(), note=note)
