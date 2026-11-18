"""The digest family: what the inbox is really asking of this person.

The two cards already rank their own threads — outlook-digest picks the one
message worth opening and waiting-on-you flags inbound threads older than
the threshold — so nothing here scores a message again. What this family
adds is the coupling: which of the threads the card already names touches a
focus topic or a fact the desk already holds, and one press that turns the
thread's own lines into a draft in the user's stated tone.

No body is ever read: the draft is a skeleton from the subject, the sender
and (when the caller has one) the last line, with [date] where a person
would otherwise have to guess.
"""

from __future__ import annotations

import re
from typing import Callable

from agentdesk.insight.agenda import focus_matches, normalise, recalled, truncate
from agentdesk.insight.preferences import REPLY_LENGTHS, REPLY_TONES, defaults, prompt_lines
from agentdesk.insight.types import InsightContext, InsightReading

PRESS_LABEL = "Draft a reply"
PRESS_ROUTE = "/api/insight/draft"
PRESS_KIND = "reply-draft"

# One request, one bounded prompt: the thread's lines plus the preference
# lines that fit, and never a character more.
MAX_PROMPT = 900

_SUBJECT_LABELS = ("email", "message", "subject")

# The outlook card prints its three openers as a list marked with this meta.
# An opener is not a thread, so a reading must not draft from one.
_NON_THREAD_META = frozenset({"reply starter"})

# The two preferences that shape a draft: the tone of the opener and how much
# of it there is. Nothing else on Settings changes the skeleton's form.
DRAFT_KEYS = ("replyTone", "replyLength")


def derive(card: dict, payload: dict, context: InsightContext) -> InsightReading:
    threads = thread_facts(payload)
    if not threads:
        # Nothing on the card names a subject, so there is nothing to match
        # and nothing to draft from.
        return InsightReading(status="empty")

    plugin_id = str((card or {}).get("pluginId") or (card or {}).get("id") or "")
    chosen: tuple[dict, list[str], list[dict]] | None = None
    for thread in threads:
        topics = focus_matches(
            f"{thread['subject']} {thread['sender']}", context.preferences
        )
        facts = recalled(context, thread["subject"], limit=2)
        if topics or facts:
            chosen = (thread, topics, facts)
            break

    press = _press(chosen[0] if chosen else threads[0])
    if chosen is None:
        # The press still offers a draft from the first thread, so the tone
        # and length that shape it are receipts even without an element.
        return InsightReading(
            status="empty",
            press=press,
            used=_shaped_keys(threads[0], context.preferences),
            inputs=_inputs(context),
        )

    thread, topics, facts = chosen
    elements = [
        {
            "kind": "text",
            "label": "Reading",
            "text": _finding_text(plugin_id, thread, topics, facts),
        }
    ]
    rest = facts[1:]
    if rest:
        elements.append(
            {
                "kind": "list",
                "title": "From your notes",
                "rows": [
                    {"primary": fact["text"], "secondary": "", "meta": fact["source"]}
                    for fact in rest
                ],
            }
        )
    return InsightReading(
        elements=elements,
        press=press,
        status="ok",
        used=_shaped_keys(thread, context.preferences),
        inputs=_inputs(context),
        memory_notes=len(facts),
    )


def _shaped_keys(thread: dict, preferences: dict) -> tuple[str, ...]:
    """The draft preferences whose stored value changed this thread's skeleton.

    The counterfactual is the test: a key is a receipt only when resetting it
    to its default would build a different draft. A thread with nobody to
    address has no skeleton at all, so nothing shaped one.
    """
    facts = _facts(thread)
    if facts is None:
        return ()
    document = preferences if isinstance(preferences, dict) else {}
    base = defaults()
    skeleton = _template(facts, document)
    shaped = []
    for key in DRAFT_KEYS:
        reset = dict(document, **{key: base[key]})
        if _template(facts, reset) != skeleton:
            shaped.append(key)
    return tuple(shaped)


def _inputs(context: InsightContext) -> tuple[str, ...]:
    """The card's own threads, and memory when the bank was open to reading.

    A sealed or missing bank leaves `recall` None, so memory is not declared:
    the receipt must not claim a consultation that never happened.
    """
    return ("rows", "memory") if context.recall is not None else ("rows",)


def thread_facts(payload: dict) -> list[dict]:
    """The threads a digest card already names, in the order it names them.

    A list row is a thread: subject, sender, age. A text element whose
    label says it is the email, message or subject is the card's own pick,
    and the text element that follows it saying who it is from fills in
    that thread's sender. A card carrying neither yields no threads."""
    elements = payload.get("elements") if isinstance(payload, dict) else None
    threads: list[dict] = []
    seen: set[str] = set()
    last: dict | None = None
    for element in elements or []:
        if not isinstance(element, dict):
            continue
        kind = element.get("kind")
        if kind == "list":
            for row in element.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                if normalise(row.get("meta")) in _NON_THREAD_META:
                    continue
                thread = _thread(row.get("primary"), row.get("secondary"), row.get("meta"))
                if thread is None or normalise(thread["subject"]) in seen:
                    continue
                seen.add(normalise(thread["subject"]))
                threads.append(thread)
                last = thread
        elif kind == "text":
            label = normalise(element.get("label"))
            text = truncate(element.get("text"), 200)
            if not text:
                continue
            if any(word in label for word in _SUBJECT_LABELS):
                if normalise(text) in seen:
                    last = next(
                        (thread for thread in threads if normalise(thread["subject"]) == normalise(text)),
                        None,
                    )
                    continue
                seen.add(normalise(text))
                last = _thread(text, "", "")
                if last is not None:
                    threads.append(last)
            elif last is not None and not last["sender"] and "from" in label:
                sender, age = _sender_and_age(text)
                last["sender"] = sender
                if age and not last["age"]:
                    last["age"] = age
    return threads


def _thread(primary: object, secondary: object, meta: object) -> dict | None:
    subject = truncate(primary, 200)
    if not subject:
        return None
    sender, age = _sender_and_age(truncate(secondary, 120))
    return {
        "subject": subject,
        "sender": sender,
        "age": age or truncate(meta, 40),
    }


def _sender_and_age(value: str) -> tuple[str, str]:
    """Split a "Priya Raman · 2 h ago" line into who and how long."""
    parts = [part.strip() for part in re.split(r"\s*[·|]\s*", value or "") if part.strip()]
    if not parts:
        return "", ""
    return parts[0][:120], " · ".join(parts[1:])[:40]


def _press(thread: dict) -> dict | None:
    """The offer of a draft, carrying only the bounded facts it would send."""
    subject = truncate(thread.get("subject"), 200)
    if not subject:
        return None
    # Only what the disclosure names, so the promise stays true: the
    # subject, who it is from, and the last line. The age the card shows
    # stays on the card.
    facts = {"subject": subject}
    for key, cap in (("sender", 120), ("last", 300)):
        value = truncate(thread.get(key), cap)
        if value:
            facts[key] = value
    return {
        "label": PRESS_LABEL,
        "route": PRESS_ROUTE,
        "kind": PRESS_KIND,
        "thread": facts,
    }


def _finding_text(
    plugin_id: str, thread: dict, topics: list[str], facts: list[dict]
) -> str:
    """One sentence naming the thread, and why it concerns this person."""
    sender = thread["sender"]
    if plugin_id == "waiting-on-you":
        lead = (
            f"{sender} is waiting on {thread['subject']}"
            if sender
            else f"{thread['subject']} is still waiting on you"
        )
    else:
        lead = f"{thread['subject']}, from {sender}" if sender else thread["subject"]
    if thread["age"]:
        lead += f" ({thread['age']})"
    line = _sentence(lead)
    if topics:
        line += f" That matches your focus topic {_joined(topics)}."
    if facts:
        line += f" In your notes: {_sentence(facts[0]['text'])}"
    return line


def _sentence(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value if value[-1] in ".?!" else value + "."


def _joined(items: list[str]) -> str:
    lines = [str(item) for item in items if str(item).strip()]
    if len(lines) <= 1:
        return "".join(lines)
    if len(lines) == 2:
        return f"{lines[0]} and {lines[1]}"
    return ", ".join(lines[:-1]) + " and " + lines[-1]


def draftable(thread: object) -> bool:
    """Whether the thread carries enough to answer: someone, and something.

    A subject alone is not a draft, because there is nobody to address and
    nothing yet to answer."""
    return _facts(thread) is not None


def compose(
    thread: dict,
    preferences: dict,
    *,
    complete: Callable[[str], str] | None = None,
) -> str:
    """One reply draft from the thread's subject, sender and last line."""
    return compose_draft(thread, preferences, complete=complete)[0]


def compose_draft(
    thread: dict,
    preferences: dict,
    *,
    complete: Callable[[str], str] | None = None,
) -> tuple[str, str]:
    """The draft, and where it came from: "model", "template" or "none".

    A thread with only a subject is refused an empty draft: there is
    nobody to address and nothing to answer yet. A model that fails or
    answers nothing falls back to the same template the local path builds,
    and says so, because a draft the desk cannot stand behind is worse
    than a skeleton."""
    facts = _facts(thread)
    if facts is None:
        return "", "none"
    template = _template(facts, preferences)
    if complete is None:
        return template, "template"
    try:
        answer = complete(_prompt(facts, preferences))
    except Exception:  # noqa: BLE001 - a failed draft falls back, never crashes
        return template, "template"
    text = answer.strip() if isinstance(answer, str) else ""
    if not text:
        return template, "template"
    return text, "model"


def _facts(thread: object) -> dict | None:
    if not isinstance(thread, dict):
        return None
    facts = {
        "subject": truncate(thread.get("subject"), 200),
        "sender": truncate(thread.get("sender"), 120),
        "last": truncate(thread.get("last"), 300),
    }
    if not facts["subject"] or not (facts["sender"] or facts["last"]):
        return None
    return facts


def _tone(preferences: dict) -> str:
    value = str((preferences or {}).get("replyTone") or "direct")
    return value if value in REPLY_TONES else "direct"


def _length(preferences: dict) -> str:
    value = str((preferences or {}).get("replyLength") or "short")
    return value if value in REPLY_LENGTHS else "short"


def _given_name(sender: str) -> str:
    if not sender:
        return ""
    local = sender.split("@")[0] if "@" in sender else sender
    first = local.replace(",", " ").split()
    return first[0].strip(".,;:")[:40] if first else ""


def _template(facts: dict, preferences: dict) -> str:
    """The skeleton: the thread's own words, the user's tone, no invention."""
    tone = _tone(preferences)
    length = _length(preferences)
    topic = facts["subject"]
    opener = {
        "direct": "Thanks.",
        "warm": "Thanks for sending this over.",
        "formal": "Thank you for your message.",
    }[tone]
    if facts["last"]:
        body = f'You asked: "{facts["last"]}" I will come back to you on {topic} by [date].'
    else:
        body = {
            "direct": f"I have your note on {topic} and will come back to you by [date].",
            "warm": (
                f"I have your note on {topic} and will come back to you by [date] "
                "with the details you need."
            ),
            "formal": f"I am writing to acknowledge your message on {topic}. "
            "I will reply in full by [date].",
        }[tone]
    if length == "one-line":
        return f"{opener} {body}"
    name = _given_name(facts["sender"])
    if tone == "formal":
        greeting = f"Dear {name}," if name else "Dear colleague,"
    else:
        greeting = f"Hi {name}," if name else "Hello,"
    lines = [greeting, "", opener, body]
    if length == "paragraph":
        lines.append(
            "I would rather check the details than guess at them, "
            "so the specifics will follow in this thread."
        )
    return "\n".join(lines)


def _prompt(facts: dict, preferences: dict) -> str:
    """One prompt, at most MAX_PROMPT characters, from the same facts."""
    lines = [
        "Draft a reply to this email. Return only the reply text.",
        f"Subject: {truncate(facts['subject'], 120)}",
    ]
    if facts["sender"]:
        lines.append(f"From: {truncate(facts['sender'], 80)}")
    if facts["last"]:
        lines.append(f"Their last line: {truncate(facts['last'], 200)}")
    lines.append(f"Reply tone: {_tone(preferences)}. Length: {_length(preferences)}.")
    lines.append(
        "Do not invent deadlines, numbers or promises; write [date] where one is needed."
    )
    text = "\n".join(lines)
    for line in prompt_lines(preferences or {}):
        if line.startswith("Replies:"):
            continue  # the tone and length line above already says this
        if len(text) + len(line) + 1 > MAX_PROMPT:
            break
        text = f"{text}\n{line}"
    return text
