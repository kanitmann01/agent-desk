"""The turn vocabulary: the shapes and the tool list every backend shares.

One turn is context and tools in, an event stream through the backend,
structured actions out. Each action carries its ledger shape: the tool
name, the arguments the desk's handler receives, and the undo kinds the
change may land under. A read-only tool declares none, because a read
that changes nothing has nothing to undo; a write always declares at
least one real ledger undo kind, and a call the vocabulary does not
know is refused here rather than guessed at.
"""

from dataclasses import dataclass, field


class EngineUnavailable(Exception):
    """No backend could run the turn.

    Raised when the side-car is absent and no fixed loop was given; the
    desk that holds a loop never sees this, because the fallback is
    always that loop.
    """


@dataclass(frozen=True)
class ConnectionSpec:
    """One model connection a side-car turn runs against.

    Read from the desk's resolution hub per turn; the key is the real
    one (the hub fetches it from the keychain) and never outlives the
    call.
    """

    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class ToolSpec:
    """One tool the desk exposes to the engine, and its ledger shape.

    `args` names the JSON keys the call may carry; `undo_kinds` is empty
    exactly when the tool only reads.
    """

    name: str
    summary: str
    args: tuple[str, ...]
    undo_kinds: tuple[str, ...]

    @property
    def read_only(self) -> bool:
        """Whether the tool changes nothing: no undo kind is declared."""
        return not self.undo_kinds


# The desk's tools are the engine's hands (spec 023): the vocabulary is
# desk-owned and small. The undo kinds name ledger kinds that exist in
# agentdesk.ledger.undo; the route records the entry, the engine never
# touches a store.
TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="desk_names",
        summary="Read the dashboard's names: memory's org and person names, "
                "the next meeting, and the workbook rows summary.",
        args=(),
        undo_kinds=(),
    ),
    ToolSpec(
        name="add_card",
        summary="Add one suggestion card for the user, through the desk's "
                "recommendation builder.",
        args=("title", "body", "why"),
        undo_kinds=("card-added",),
    ),
    ToolSpec(
        name="propose_fact",
        summary="Propose one memory fact; the desk stages it for review or "
                "saves it when review is off.",
        args=("text",),
        undo_kinds=("memory-fact", "card-added"),
    ),
    ToolSpec(
        name="desk_probes",
        summary="Run the desk check's read-only probes and return what they "
                "found.",
        args=(),
        undo_kinds=(),
    ),
)


def tool_by_name(name) -> ToolSpec | None:
    """The tool spec for this name, or None when it is not one the desk offers."""
    if not isinstance(name, str):
        return None
    for spec in TOOL_SPECS:
        if spec.name == name.strip():
            return spec
    return None


@dataclass(frozen=True)
class Action:
    """One structured action a turn took, with the ledger shape it lands under.

    `undo_kinds` carries the declared kinds for the tool (reads carry
    none); `entry_id` is filled in by the desk's executor once the tool
    call landed and its ledger entry exists.
    """

    tool: str
    args: dict = field(default_factory=dict)
    undo_kinds: tuple[str, ...] = ()
    why: str = ""
    entry_id: str | None = None

    @property
    def read_only(self) -> bool:
        """Whether the action only reads: no undo kind is declared."""
        return not self.undo_kinds


@dataclass(frozen=True)
class TurnResult:
    """What one turn produced: its backend, its actions and the event kinds.

    `events` holds the parsed stream the backend saw (a side-car's JSON
    events; the fixed-loop fallback runs no event stream and answers an
    empty tuple). `note` carries the one-line human summary.
    """

    backend: str
    actions: tuple[Action, ...] = ()
    events: tuple[dict, ...] = ()
    note: str = ""
