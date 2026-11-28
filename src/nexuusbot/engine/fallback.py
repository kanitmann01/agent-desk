"""The fallback backend: the desk's existing fixed loop, wrapped as a turn.

When the side-car is absent, a turn is exactly what the desk did before
this package existed: one pass of the supervised loop's fixed step
registry. The pass's step rows become the turn's note, and every ledger
entry the pass recorded becomes one action carrying the entry's own
undo kind, so a caller sees the same ledger toll a side-car turn pays.
The fallback is not a regression path; it is how the POC stays optional
on machines that cannot run the side-car.
"""

from nexuusbot.engine import vocab as engine_store

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

    A loop that is already running a pass answers with a no-op refusal:
    calling run_pass() there would be refused by the loop's own guard,
    and re-posting the pass's ledger entries through the tools route
    would execute its changes twice. The engine step never calls this
    function; it is for callers outside the loop.
    """
    if _loop_is_running(loop):
        return engine_store.TurnResult(
            backend=BACKEND, ok=False,
            note=("The fixed loop is already running a pass, so the fallback "
                  "did not run and nothing was executed again."))
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
    ok = all(row.get("ok", True) for row in rows if isinstance(row, dict))
    return engine_store.TurnResult(backend=BACKEND, actions=tuple(actions),
                                   events=(), note=note, ok=ok)


def _loop_is_running(loop) -> bool:
    """Whether this loop holds a pass right now, by its own public check.

    AgentLoop answers is_running(); a stand-in without it exposes no
    pass state, so a runner that keeps the guard answer here is also
    read. Anything else counts as not running, the caller's own risk.
    """
    check = getattr(loop, "is_running", None)
    if callable(check):
        try:
            return bool(check())
        except Exception:  # noqa: BLE001 - a broken check is not a pass
            return False
    return bool(getattr(loop, "_running", False))
