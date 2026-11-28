"""The engine boundary: one call runs a turn, two backends sit behind it.

The desk's agent system speaks one vocabulary here: context and tools
in, an event stream through the chosen backend, structured actions out
(each carrying the ledger shape its change lands with). Two backends:
the side-car process (the pinned engine CLI in its own contained venv,
`sidecar.py`) and the desk's existing fixed loop as the fallback
(`fallback.py`). Nothing outside this package imports a backend by
name; callers ask the boundary and the boundary picks, which is what
keeps the adapter interface the asset and the engine replaceable.

The side-car is never a hard dependency: absent, run_turn delegates to
the fixed loop and the desk behaves exactly as it did before this
package existed. A turn whose process fails answers a failed result
with the cause in its note; a tool call the vocabulary does not know is
refused at this boundary, never guessed at.
"""

import json

from nexuusbot.engine import fallback, sidecar
from nexuusbot.engine.sidecar import SidecarError, read_marker, redact, write_marker
from nexuusbot.engine.vocab import (
    Action,
    ConnectionSpec,
    EngineUnavailable,
    TOOL_SPECS,
    ToolSpec,
    TurnResult,
    tool_by_name,
)

__all__ = [
    "ACTION_KEYS",
    "ARG_MAX_CHARS",
    "Action",
    "ConnectionSpec",
    "EngineUnavailable",
    "MAX_ACTIONS_PER_TURN",
    "PROMPT_CONTEXT_MAX_CHARS",
    "PROMPT_MAX_CHARS",
    "SidecarError",
    "TOOL_SPECS",
    "ToolSpec",
    "TurnResult",
    "actions_from_events",
    "available",
    "cli_path",
    "home_for",
    "pinned_tag",
    "prompt_for",
    "read_marker",
    "redact",
    "run_turn",
    "sidecar_home",
    "tool_by_name",
    "venv_path",
    "write_marker",
]

# The verbs a tool call's JSON may use for its tool name and arguments;
# the tolerant pair keeps the boundary honest about what it accepts
# while a real turn's reply wording settles.
ACTION_KEYS = ("tool", "name")

# The most tool calls one turn may carry. A reply that proposes more is
# a flood, not a plan: the calls past this count are refused by name so
# the pass can see what it did not do. The desk's executor applies the
# same cap again.
MAX_ACTIONS_PER_TURN = 5

# The longest value each argument may carry. A write's text lands on a
# card, in memory and in the ledger's capture, so an unbounded value is
# an unbounded write; an overlong call is refused rather than silently
# truncated.
ARG_MAX_CHARS = {"title": 500, "body": 2000, "why": 500, "text": 2000}

# The context the prompt may carry, and the whole prompt's ceiling. The
# CLI has no stdin prompt mode, so the prompt rides argv; 14,000
# characters stays far below the OS command-line limit (32,767 on
# Windows) even with the fixed instructions, and the context is cut with
# a marker rather than dropped.
PROMPT_CONTEXT_MAX_CHARS = 12000
PROMPT_MAX_CHARS = 14000
CONTEXT_CUT_MARKER = "\n\n[The desk's context was cut at this length.]"

DEFAULT_TURN_TIMEOUT_S = sidecar.DEFAULT_TIMEOUT_S


def pinned_tag() -> str:
    """The side-car tag the installer pins: what this build was verified against."""
    return sidecar.PINNED_TAG


def sidecar_home():
    """The side-car's contained home folder for this machine's data folder."""
    return sidecar.default_home()


def home_for(data_dir):
    """The side-car's contained home folder under one data folder."""
    return sidecar.home_dir(data_dir)


def venv_path(home):
    """The pinned venv folder inside one side-car home."""
    return sidecar.venv_dir(home)


def cli_path(home):
    """The pinned CLI executable inside one side-car home."""
    return sidecar.cli_path(home)


def available(home=None) -> bool:
    """Whether the side-car backend can run a turn right now.

    This checks the side-car alone: the fixed-loop fallback is always
    there for a caller that holds one, so a False here means the next
    turn is today's behaviour, not that no turn can run.
    """
    return sidecar.available(home)


def prompt_for(context: str) -> str:
    """Build one turn's prompt: the context, the tool list and the reply shape.

    The reply shape is strict JSON (one array of tool calls), because
    the boundary parses actions out of the turn's result event; a reply
    that is not an array of known tool calls is refused at the boundary.
    The context is capped at PROMPT_CONTEXT_MAX_CHARS with a visible
    marker, and the finished prompt is held under PROMPT_MAX_CHARS: the
    CLI takes its prompt in argv, so this is what keeps the OS limit out
    of reach.
    """
    text = (context or "").strip() or "(the desk is empty)"
    if len(text) > PROMPT_CONTEXT_MAX_CHARS:
        text = text[:PROMPT_CONTEXT_MAX_CHARS] + CONTEXT_CUT_MARKER
    tool_lines = "\n".join(
        f'- {spec.name}: {spec.summary} Arguments: {", ".join(spec.args) or "none"}.'
        for spec in TOOL_SPECS
    )
    prompt = _prompt_text(text, tool_lines)
    if len(prompt) <= PROMPT_MAX_CHARS:
        return prompt
    keep = max(0, len(text) - (len(prompt) - PROMPT_MAX_CHARS))
    return _prompt_text(text[:keep] + CONTEXT_CUT_MARKER, tool_lines)


def _prompt_text(context: str, tool_lines: str) -> str:
    """The fixed prompt around one context block and the tool list."""
    return (
        "You act for a small business desk. Use the tools below to do useful, "
        "small, safe work with what the desk already knows. Read first, act "
        "only when a change is clearly worth making, and never invent a fact.\n\n"
        f"The desk's context:\n{context}\n\n"
        f"Tools:\n{tool_lines}\n\n"
        "Reply with only a JSON array of the tool calls to make, in order, "
        'each an object like {"tool": "<name>", "args": {...}}. Empty array '
        "when nothing is worth doing. No prose, no code fences."
    )


def run_turn(context: str, *, connection=None, home=None, loop=None,
             spawn=None, timeout_s: float = DEFAULT_TURN_TIMEOUT_S) -> TurnResult:
    """Run one turn: context in, the chosen backend through, actions out.

    The side-car backend runs when the pinned venv is present; otherwise
    the turn is one pass of the fixed loop handed in as `loop`. A
    side-car that fails mid-turn becomes a failed result naming the
    cause, never a raised error into the pass that asked for the turn.
    Without a side-car and without a loop there is no backend, and that
    is EngineUnavailable.
    """
    if sidecar.available(home):
        if connection is None:
            return TurnResult(backend="sidecar", ok=False, note=(
                "The side-car is installed but no connection was given, so the "
                "turn did not run."))
        try:
            events = sidecar.run(
                prompt_for(context), connection=connection, home=home,
                timeout_s=timeout_s, spawn=spawn)
        except SidecarError as exc:
            return TurnResult(backend="sidecar", ok=False,
                              note=sidecar.redact(str(exc), connection.api_key))
        actions, refused = actions_from_events(events)
        note = f"{len(actions)} action(s)"
        if refused:
            note += f"; refused: " + "; ".join(refused)
        return TurnResult(backend="sidecar", actions=actions, events=events,
                          note=sidecar.redact(note, connection.api_key),
                          refusals=refused)
    if loop is not None:
        return fallback.run(loop)
    raise EngineUnavailable(
        "No engine backend is available: the side-car is not installed and no "
        "fixed loop was given.")


def actions_from_events(events) -> tuple[tuple[Action, ...], tuple[str, ...]]:
    """Parse the event stream into tool-call actions, refusing what is not one.

    The turn's actions ride the last `result` event's text as one JSON
    array of {"tool", "args"} objects. Each call is checked against the
    vocabulary: an unknown tool, a write without its required arguments,
    an argument past its documented length, or a payload that is not an
    array is refused, and every refusal is named in the returned
    sentences so the pass can say what it did not do. At most
    MAX_ACTIONS_PER_TURN calls become actions; the rest are refused in
    one sentence.
    """
    text = _result_text(events)
    if text is None:
        return (), ("The turn's result carried no tool calls to read.",)
    calls = _parse_calls(text)
    if calls is None:
        return (), ("The turn's result was not a JSON array of tool calls.",)
    actions: list[Action] = []
    refused: list[str] = []
    for index, call in enumerate(calls):
        if len(actions) >= MAX_ACTIONS_PER_TURN:
            refused.append(
                f"refused {len(calls) - index} call(s) past the turn's limit "
                f"of {MAX_ACTIONS_PER_TURN}")
            break
        spec = tool_by_name(_call_tool(call))
        if spec is None:
            refused.append(f"refused an unknown tool call: {_call_tool(call)!r}")
            continue
        args = call.get("args") if isinstance(call, dict) else None
        if not isinstance(args, dict):
            args = {}
        missing = [key for key in spec.args if not _arg_text(args.get(key))]
        if missing:
            refused.append(
                f"refused the {spec.name} call: no {'/'.join(missing)} was given")
            continue
        overlong = [
            key for key in spec.args
            if key in ARG_MAX_CHARS and len(_arg_text(args.get(key))) > ARG_MAX_CHARS[key]
        ]
        if overlong:
            key = overlong[0]
            refused.append(
                f"refused the {spec.name} call: its {key} is longer than "
                f"{ARG_MAX_CHARS[key]} characters")
            continue
        clean = {key: _arg_text(args.get(key)) for key in spec.args if key in args}
        actions.append(Action(tool=spec.name, args=clean,
                              undo_kinds=spec.undo_kinds,
                              why=spec.summary))
    return tuple(actions), tuple(refused)


def _result_text(events) -> str | None:
    """The last result event's reply text, or None when the stream has none.

    The verified grammar's result event carries the reply text; the key
    is read tolerantly (text, result, content) so a small field rename
    reads as no reply rather than a crash.
    """
    for event in reversed(list(events)):
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        for key in ("text", "result", "content", "message"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None
    return None


def _parse_calls(text: str) -> list | None:
    """The JSON array in a result's text, or None when there is none.

    The whole text may be the array, or the array may ride inside prose
    or code fences; the first bracket to the last one is the widest
    candidate and only a parsed non-empty array of objects counts.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    candidates = [stripped]
    start, end = stripped.find("["), stripped.rfind("]")
    if 0 <= start < end:
        candidates.append(stripped[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def _call_tool(call) -> str:
    """A call's tool name, accepting the two verb spellings, '' otherwise."""
    if not isinstance(call, dict):
        return ""
    for key in ACTION_KEYS:
        value = call.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _arg_text(value) -> str:
    """One argument as the clean text a desk handler takes, '' otherwise."""
    return value.strip() if isinstance(value, str) else ""
