"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, agent/background_review.py and tools/threat_patterns.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The refine pipeline (spec 016 section 6.6): the prompt, the input it
wraps, the strict reply parse, and the strict threat scan a refined
prompt must pass. The prompt is the Hermes skill-review prompt trimmed
to one skill and one round of feedback; the cited fragments (the
first-class style signals bullet, the pitfall rule from the lesson
layer, and the no-PR-numbers rule) are kept word for word, with the
em dashes Hermes wrote replaced by colons under this project's style
rule. The scan is the strict scope of Hermes' shared threat-pattern
library, trimmed to the patterns a 4000-character prompt can carry.
"""

import json
import re
import unicodedata

# The trimmed Hermes _SKILL_REVIEW_PROMPT: what a refined skill prompt
# should be, and the signals that say it needs to change. Kept fragments
# are word for word (spec 016 section 6.6); only the trim and the em-dash
# substitutions differ.
PROMPT = (
    "Refine one saved skill of this desk. You see the skill's current"
    " prompt and the user's feedback about how its runs landed. Rewrite"
    " the prompt so the next run already does what the user asked for.\n\n"
    "Signals to look for (any one of these warrants action):\n"
    "  - User corrected your style, tone, format, legibility, or verbosity."
    " Frustration signals like 'stop doing X', 'this is too verbose', 'don't"
    " format like this', 'why are you explaining', 'just give me the"
    " answer', 'you always do Y and I hate it', or an explicit 'remember"
    " this' are FIRST-CLASS skill signals, not just memory signals. Embed"
    " the preference in the skill so the next run starts already knowing.\n"
    "  - User corrected the workflow, the approach, or the sequence of"
    " steps. Encode the correction as an explicit step or a pitfall in the"
    " prompt.\n\n"
    "How to write it:\n"
    "  - Procedure first: the steps in the order they are done, with the"
    " concrete decision points. Lessons and pitfalls attach to the step"
    " they affect.\n"
    "  - A pitfall is a generalizable rule + one clause of WHY (the"
    " mechanism), imperative. 'Grep the test tree for the SYMBOL before"
    " widening a helper signature: hand-rolled mocks reimplement the old"
    " shape and fail on a shard you did not run.' Not a narrative of what"
    " happened this session.\n"
    "  - No PR/issue numbers, dates, ticket IDs, or quoted user text as"
    " content: the rule must stand without the incident behind it. Keep a"
    " short quote ONLY when the quote itself is the clearest statement of"
    " the rule.\n"
    "  - The same lesson learned twice is ONE rule. Strengthen or clarify"
    " the sentence that already carries it rather than appending a second"
    " copy.\n"
    "  - Fix the prompt in place when it is wrong: edit the sentence that"
    " misled, do not append 'UPDATE: actually...' underneath it.\n\n"
    "The result is one prompt, plain text, the whole instruction for the"
    " skill's next run. Reply with strict JSON only,"
    ' {"prompt": "the refined prompt"}. If the feedback gives you nothing'
    " to change, reply with the current prompt unchanged inside the same"
    " JSON shape."
)

# -- build_input and parse_reply ---------------------------------------------


def build_input(skill: dict, feedback: list[str]) -> str:
    """The endpoint call's text: the review prompt, the skill's current
    prompt, and the queued feedback. Nothing else rides along (spec 016
    section 6.7: that skill's prompt and the feedback text, never
    anything else)."""
    lines = [PROMPT, "", "The skill's current prompt:", skill.get("prompt", "")]
    lines.append("")
    lines.append("The user's feedback:")
    for item in feedback:
        lines.append(f"- {item}")
    return "\n".join(lines)


def parse_reply(text: str) -> str | None:
    """The refined prompt from the endpoint's reply, or None.

    Strict: the reply must be the JSON object {"prompt": "..."} (a single
    optional code fence around it is tolerated, nothing else is guessed
    from), the prompt must be a non-empty string. None means the caller
    keeps the queue and tries again on a later pass.
    """
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    prompt = parsed.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    return prompt


# -- the strict threat scan ---------------------------------------------------

# Hermes threat_patterns.py, the strict scope trimmed to what a bounded
# prompt can carry: classic prompt injection everywhere-patterns, the
# exfiltration shapes, hardcoded secrets, and the invisible-unicode
# check. Bounded filler between key attack words, as Hermes has it.
_FILLER = r"(?:\w{1,64}\s{1,64}){0,8}"
_SECRET_VAR = r"\$\{?\w{0,256}(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)S?\b"
_PATTERNS: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), name)
    for pattern, name in (
        (rf"ignore\s{{1,64}}{_FILLER}(previous|all|above|prior)\s{{1,64}}{_FILLER}instructions", "prompt_injection"),
        (r"system\s{1,64}prompt\s{1,64}override", "sys_prompt_override"),
        (rf"disregard\s{{1,64}}{_FILLER}(your|all|any)\s{{1,64}}{_FILLER}(instructions|rules|guidelines)", "disregard_rules"),
        (rf"curl\s{{1,64}}[^\n]{{0,2048}}{_SECRET_VAR}", "exfil_curl"),
        (rf"wget\s{{1,64}}[^\n]{{0,2048}}{_SECRET_VAR}", "exfil_wget"),
        (r"cat\s{1,64}[^\n]{0,2048}(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "read_secrets"),
        (r"(send|post|upload|transmit)\s{1,64}[^\n]{0,2048}\s{1,64}(to|at)\s{1,64}https?://", "send_to_url"),
        (rf"(include|output|print|share)\s{{1,64}}{_FILLER}(conversation|chat\s{{1,64}}history|previous\s{{1,64}}messages|full\s{{1,64}}context|entire\s{{1,64}}context)", "context_exfil"),
        (r"(?:api[_-]?key|token|secret|password)\s{0,64}[=:]\s{0,64}[\"']"
         r"[A-Za-z0-9+/=_-]{20}", "hardcoded_secret"),
    )
)

# Invisible / bidirectional unicode used in injection attacks (the Hermes
# set, the tag block included).
INVISIBLE_CHARS = frozenset(
    "\u200b\u200c\u200d\u2060\u2062\u2063\u2064\ufeff"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
) | frozenset(map(chr, range(0xE0000, 0xE0080)))


def first_threat(content: str) -> str | None:
    """The user-facing refusal for the first threat found, or None.

    The text is scanned as given after an NFKC fold (full-width variants
    cannot bypass the patterns) with whitespace runs collapsed, the same
    normalization idea as Hermes scan_for_threats at prompt scale.
    """
    if not content:
        return None
    for char in content:
        if char in INVISIBLE_CHARS:
            return (f"Blocked: content contains invisible unicode character"
                    f" U+{ord(char):04X} (possible injection).")
    folded = unicodedata.normalize("NFKC", content)
    normalised = re.sub(r"\s{2,}", lambda m: "\n" if "\n" in m.group() else " ", folded)
    for compiled, name in _PATTERNS:
        if compiled.search(normalised):
            return (f"Blocked: content matches threat pattern '{name}'."
                    " A refined prompt must not carry injection or"
                    " exfiltration payloads.")
    return None
