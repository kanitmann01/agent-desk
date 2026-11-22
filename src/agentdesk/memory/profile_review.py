"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, agent/background_review.py and tools/memory_tool.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The profile review's pure core (spec 016 section 6.5): the prompt the
endpoint is sent, the shape of what it sees, and the gate every reply
must pass before a word of it is stored. Hermes reviews a whole
conversation fork in the background; here the review is one loop step
that sends the last TAIL activity rows plus the current learned lines
to the company endpoint, and applies only what survives:

- an op must be an add or a patch; remove is refused outright (Hermes
  gates unattended removals behind its write-approval flow; this step
  has no approval flow, so it accepts none at all);
- every op must name activity ids from the window it was prompted with
  (grounded, the way Hermes' review is grounded in the conversation);
- the text passes the strict injection scan;
- the write fits the learned profile's budget, else the op is dropped
  and the prompt's merge instruction is the model's way out.

This module never opens preferences.json: the stated preferences are
not an input here and cannot be an output, which a test pins by
grepping this file's source. The module has no store of its own; the
caller hands in the learned profile store and a ledger callable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from agentdesk.memory.profile import OverBudget
from agentdesk.safety.threat_patterns import first_threat_message

# Hermes' memory.nudge_interval (10) and _digest_history(tail=24).
NUDGE = 10
TAIL = 24

# The grounding paragraph from Hermes' _MEMORY_ROUTING_BLOCK (word for
# word except the two em dashes, which carry over as ":" and ";"), then
# the ops contract the step actually applies.
PROMPT = (
    "Save only facts GROUNDED in this conversation: a user message or "
    "tool result you can point to. Never infer the user's traits, skill "
    "level, role, mood or preferences from topic, tone or tools used, "
    "and never turn a one-off request into a standing preference (in "
    "either store) unless the user marked it general ('always', 'from "
    "now on', 'remember') or stated a standing like/dislike ('I hate "
    "X', 'stop doing Y'). If unsure, leave it out; a wrong fact misleads "
    "every future session.\n\n"
    "Below is the recent activity on this desk and the short list of "
    "facts about who this user is and how they work that you maintain. "
    "Only add or patch lines. Each op must name the activity ids it is "
    "grounded in. Return strict JSON "
    '{"ops":[{"op":"add","text":"...","from":[id,...]},'
    '{"op":"patch","id":"p-...","text":"...","from":[id,...]}]} '
    'or {"ops":[]}. If the list is over budget, patch to merge lines '
    "instead of adding. Never remove."
)


def due(activity_max_id: int, last_seen_id: int) -> bool:
    """Whether NUDGE or more activity rows arrived since the last review."""
    return activity_max_id - last_seen_id >= NUDGE


def build_input(activity: list[dict], doc: dict) -> dict:
    """What the endpoint sees: the last TAIL rows (id, kind, text cut at
    300 characters, mirroring Hermes' digest truncation) plus the
    current learned entries as {id, text}. Nothing else crosses the
    wire: not the fact store, not mail, not the stated preferences."""
    rows = [{"id": row.get("id"), "kind": row.get("kind"),
             "text": str(row.get("text") or "")[:300]}
            for row in (activity or [])[-TAIL:]]
    learned = [{"id": entry.get("id"), "text": entry.get("text")}
               for entry in (doc or {}).get("entries", [])
               if isinstance(entry, dict)]
    return {"activity": rows, "learned": learned}


@dataclass(frozen=True)
class ApplyResult:
    """What one reply yielded: how many ops were applied and why the
    rest were dropped, reason -> count. The reasons are the step's own
    vocabulary: ungrounded, unknown-id, threat, over-budget, bad-op."""

    applied: int
    dropped: dict[str, int] = field(default_factory=dict)


def apply(reply: str, store, record: Callable[[bytes, bytes, str], str],
          allowed_ids: set[int]) -> ApplyResult:
    """The reply gate. Parse the JSON, then apply the ops that survive
    every check, one ledger record per applied op; return the counts.

    A reply that is not the expected JSON (or carries no ops list)
    applies nothing: the caller still advances its last-seen latch, so
    a bad reply never loops the step. A raise from `record` is the
    caller's problem; the store write has already happened, exactly
    like the learn-topics step's failed-record guard.
    """
    try:
        payload = json.loads(reply)
    except ValueError:
        return ApplyResult(applied=0)
    if not isinstance(payload, dict) or not isinstance(payload.get("ops"), list):
        return ApplyResult(applied=0)
    applied = 0
    dropped: dict[str, int] = {}
    for op in payload["ops"]:
        reason = _apply_one(op, store, record, allowed_ids)
        if reason is None:
            applied += 1
        else:
            dropped[reason] = dropped.get(reason, 0) + 1
    return ApplyResult(applied=applied, dropped=dropped)


def _apply_one(op, store, record, allowed_ids: set[int]) -> str | None:
    """One op through the gate: None when it was applied, else the drop
    reason. The checks run cheapest-first; the budget is the store's own
    refusal (OverBudget), carrying the current entries for a merge."""
    if not isinstance(op, dict) or op.get("op") not in ("add", "patch"):
        return "bad-op"
    text = str(op.get("text") or "").strip()
    if not text:
        return "bad-op"
    entry_id = op.get("id")
    if op["op"] == "patch" and (
            not isinstance(entry_id, str) or not _known(store, entry_id)):
        return "unknown-id"
    grounded = _grounded_ids(op.get("from"), allowed_ids)
    if grounded is None:
        return "ungrounded"
    if first_threat_message(text, "strict") is not None:
        return "threat"
    provenance = {"activity": sorted(grounded)}
    before = store.raw()
    try:
        if op["op"] == "add":
            store.add_entry(text, provenance, by="review")
        else:
            store.patch_entry(entry_id, text, provenance)
    except OverBudget:
        return "over-budget"
    except LookupError:
        # A removal landed between the check above and the locked write;
        # patch_entry re-checks under the lock, and the same drop reason
        # applies rather than failing the whole step.
        return "unknown-id"
    if op["op"] == "add":
        note = (f"Learned a line about you from activity "
                f"{', '.join(str(i) for i in sorted(grounded))}.")
    else:
        note = (f"Merged learned line {entry_id} with activity "
                f"{', '.join(str(i) for i in sorted(grounded))}.")
    record(before, store.raw(), note)
    return None


def _known(store, entry_id: str) -> bool:
    """Whether the patch names a line the store actually holds."""
    return any(entry.get("id") == entry_id
               for entry in store.document().get("entries", []))


def _grounded_ids(from_value, allowed_ids: set[int]) -> set[int] | None:
    """The cited ids as a set, or None when the op is not grounded: the
    `from` list must be present, every element an id (an integer, or a
    JSON string that names one; booleans and fractions refuse the whole
    op), and every id from the window the reply was prompted with."""
    if not isinstance(from_value, list) or not from_value:
        return None
    cited: set[int] = set()
    for value in from_value:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            cited.add(value)
        elif isinstance(value, str):
            try:
                cited.add(int(value.strip()))
            except ValueError:
                return None
        else:
            return None
    if not cited or not cited <= set(allowed_ids):
        return None
    return cited
