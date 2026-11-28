"""The one path that may spend a model call from a reading.

A reading is local and free; a draft is not. So the transport is separate:
it validates the request, states exactly what would be sent, and only then
delegates the composition. Nothing here writes memory, and the disclosure
it returns is the sentence the user sees before pressing.

The request has one shape, and this module owns it: a reply draft posts
{"kind": "reply-draft", "thread": {"subject", "sender", "last"}, "stage":
true}, an explanation posts {"kind": "explain-range", "text"}, and a
counter-evidence check posts {"kind": "check-counter", "text"}. The
digest family's press payload is that request with a label and a route
added, so a client posts what the card carried, unchanged. A form cannot
nest, so press_to_fields and press_from_form are the one flat spelling a
no-JS form may use, and it exists only between the two of them.

A reply draft also resolves the thread it answers and may stage it as one
inbox card. Resolution reads headers only, because headers are all the mail
view keeps: there is no message body here that an answer could leak.
"""

from __future__ import annotations

from email.utils import parseaddr
from typing import Any, Callable

from nexuusbot.insight import digest
from nexuusbot.insight.agenda import normalise
from nexuusbot.insight.types import InsightError
from nexuusbot.llm import LlmUnavailable
from nexuusbot.mail import watcher as mail_watcher
from nexuusbot.mail.core import reply_recipients, reply_subject

KINDS = ("reply-draft", "explain-range", "check-counter")

# The desk will not hand back a skeleton dressed as a draft: when the model
# path is off the route refuses, and the refusal repeats what would have
# travelled so the promise and the refusal are the same sentence.
MODEL_OFF = (
    "Nothing was drafted: model calls are off on this desk, so there is no "
    "model to write with. Turn the model on in Settings, then ask again."
)

# The draft never quotes a body, because none was read. Saying so on the
# draft keeps the skeleton from being mistaken for a finished reply.
SKELETON_NOTE = (
    "A skeleton from the thread's subject and greeting; no message body was read."
)

DISCLOSURE = (
    "Sends: the thread's subject, who it is from, and its last line.",
    "Does not send: the rest of the thread, the workbook, the calendar, or any memory.",
)

# An explanation of a finding sends the finding itself, which the card
# already shows. The rows behind it never travel: the reading was computed
# here, and only its conclusion is worth a model call.
EXPLAIN_DISCLOSURE = (
    "Sends: the one sentence this card already shows, with its column names, "
    "its numbers and the chart the desk chose.",
    "Does not send: the workbook, its rows, the calendar, or any memory.",
)

MODEL_OFF_EXPLAIN = (
    "Nothing was explained: model calls are off on this desk, so there is no "
    "model to explain with. Turn the model on in Settings, then ask again."
)

# A counter-evidence check sends the stored answer and the falsification
# criterion the card printed beside it. The desk's sources stay local: the
# model is testing one conclusion, not rereading the desk.
COUNTER_DISCLOSURE = (
    "Sends: the stored answer summary and the desk's falsification criterion.",
    "Does not send: your workbook, your mail, your calendar, or any memory.",
)

MODEL_OFF_COUNTER = (
    "Nothing was checked: model calls are off on this desk, so there is no "
    "model to check with. Turn the model on in Settings, then ask again."
)

COUNTER_PROMPT = (
    "Test one research conclusion for its blind spot. Name the strongest "
    "opposing evidence, or the one assumption that would most weaken it, in "
    "at most three sentences. Do not invent a study, a date or a number."
    "\n\nConclusion: "
)

MAX_FINDING = 400

EXPLAIN_PROMPT = (
    "Explain one pattern a spreadsheet showed its owner, in at most three "
    "sentences. Say what it means and what to check next. Do not invent a "
    "cause, a date or a number.\n\nPattern: "
)

# Why the thread behind a press cannot be looked up, each in the two halves
# every refusal here uses: what did not happen, then the one thing that fixes
# it. The folder states are the mail view's own, so the sentence cannot drift
# from the page that shows the same folder.
MAIL_CAUSES = {
    "off": (
        "mail digest is off on this desk",
        "Turn it on in Settings, then ask again.",
    ),
    mail_watcher.STATE_UNCONFIGURED: (
        "no mail folder has been chosen yet",
        "Choose the folder in Settings, then ask again.",
    ),
    mail_watcher.STATE_ERROR: (
        "the mail folder could not be read just now",
        "Check the folder in Settings, then ask again.",
    ),
}

INBOX_OFF = (
    "Nothing was staged: the inbox is not available on this desk, so there is "
    "nowhere to put the card."
)

# The two retired spellings, each named so a caller hears which convention
# ended rather than a generic 400. Both keep the house voice: what did not
# happen, then the one thing that fixes it.
FLAT_THREAD = (
    "Nothing was drafted: the thread a press answers travels nested under "
    '"thread", so the flat "subject", "sender" and "last" fields are no '
    "longer read. Post the press the card carried, which already nests them."
)

STAGE_SPELLING = (
    'Nothing was drafted: stage is asked as a boolean, so "stage": true, '
    "not a word or a number. Post the press again with the boolean."
)


def draft_reply(
    server: Any,
    body: object,
    *,
    preferences: dict,
    complete: Callable[[str], str] | None = None,
) -> dict:
    """Compose one draft (a reply, or an explanation), or say why not.

    A reply body carries the thread it answers nested under "thread",
    exactly as a card's press payload does, so one shape is the whole
    request: the thread is the draft's source, its sender resolves the
    message against the mail view when there is one to find, and "stage":
    true asks for the draft to be put in the inbox as one card. A body
    using the retired flat spellings is refused by name rather than half
    answered.
    """
    if not isinstance(body, dict):
        raise InsightError("insight:bad-request", "Expected a JSON object.")
    kind = body.get("kind")
    if kind not in KINDS:
        raise InsightError("insight:unknown-kind", f"{kind} is not something the desk drafts.")
    if kind == "explain-range":
        return _explain(body, complete)
    if kind == "check-counter":
        return _counter(body, complete)
    _refuse_retired_shape(body)
    facts = body.get("thread") if isinstance(body.get("thread"), dict) else {}
    subject = str(facts.get("subject") or "").strip()
    if not subject:
        raise InsightError("insight:bad-request", "A draft needs the thread it answers.")
    if len(subject) > 200:
        raise InsightError("insight:bad-request", "That subject is too long to draft from.")
    sender = str(facts.get("sender") or "").strip()
    stage = _stage_flag(body)
    if stage and not sender:
        # Staging without a thread would be half a card: one with no message
        # to write into, which acceptance could only refuse later.
        raise InsightError("insight:thread-missing", _say(_unstageable(subject)), 404)
    thread: dict | None = None
    root = ""
    if sender:
        thread, root = _resolve(server, subject, sender)
    if complete is None and digest.draftable(facts):
        raise InsightError("insight:model-off", _say(MODEL_OFF), 409)
    text, source = digest.compose_draft(facts, preferences, complete=complete)
    if not text.strip():
        answer = {
            "status": "empty",
            "text": "",
            "source": "none",
            "disclosure": list(DISCLOSURE),
            "note": "No draft yet.",
        }
    else:
        answer = {
            "status": "draft",
            "text": text,
            "source": source,
            "disclosure": list(DISCLOSURE),
            "note": SKELETON_NOTE if source == "template" else "",
        }
    if thread is not None:
        answer["thread"] = thread
    if stage:
        # A press that stages may carry the text the page showed, edited or
        # not; the composed draft is the fallback, never the other way round,
        # so an empty composition stages nothing at all.
        draft = text.strip()
        supplied = str(body.get("text") or "").strip()
        if draft and supplied:
            draft = supplied
        staged, card_id = (False, None)
        if thread is not None and draft:
            answer["text"] = draft
            staged, card_id = _stage(server, thread, root, draft, source)
        answer["staged"] = staged
        answer["cardId"] = card_id
    return answer


def _refuse_retired_shape(body: dict) -> None:
    """Name the retired spellings of a reply request rather than half answer.

    The thread nests under "thread" and stage is a boolean; a caller using
    the flat fields or a word for stage is told which convention ended,
    because silently drafting from half a request is exactly how the two
    shapes drifted apart.
    """
    if any(key in body for key in ("subject", "sender", "last")):
        raise InsightError("insight:flat-thread", _say(FLAT_THREAD), 400)
    stage = body.get("stage")
    if stage is not None and not isinstance(stage, bool):
        raise InsightError("insight:stage-spelling", _say(STAGE_SPELLING), 400)


def _stage_flag(body: dict) -> bool:
    """Whether the press asked for its draft to be staged as a card.

    Every spelling but a boolean was refused before this runs, so the flag
    is read as one and there are no words to interpret here.
    """
    return body.get("stage") is True


# The keys of the thread a press names, and the one other field a reply
# request may carry besides them. press_to_fields and press_from_form are
# the pair that spells these the one way a form can carry them.
_THREAD_KEYS = ("subject", "sender", "last")
_TOP_KEYS = ("kind", "text")


def press_to_fields(press: dict) -> dict[str, str]:
    """One press payload as the flat fields a no-JS form carries.

    A form cannot nest, so the thread's facts ride as the fields this pair
    names, and the label and the route stay behind: what travels is the
    request, not the offer of it.
    """
    fields: dict[str, str] = {}
    for key in _TOP_KEYS:
        value = str(press.get(key) or "").strip()
        if value:
            fields[key] = value
    thread = press.get("thread") if isinstance(press.get("thread"), dict) else {}
    for key in _THREAD_KEYS:
        value = str(thread.get(key) or "").strip()
        if value:
            fields[key] = value
    return fields


def press_from_form(fields: dict) -> dict:
    """The request the route parses, rebuilt from a no-JS form's fields.

    press_to_fields' other half: the thread's facts nest again and the
    stage field becomes the boolean the request carries, so the route reads
    one shape whether the press arrived as JSON or as a form.
    """
    request: dict = {"kind": str(fields.get("kind") or "").strip()}
    thread = {}
    for key in _THREAD_KEYS:
        value = str(fields.get(key) or "").strip()
        if value:
            thread[key] = value
    if thread:
        request["thread"] = thread
    text = str(fields.get("text") or "").strip()
    if text:
        request["text"] = text
    if str(fields.get("stage") or "").strip() not in ("", "0", "false", "False"):
        request["stage"] = True
    return request


def _resolve(server: Any, subject: str, sender: str) -> tuple[dict, str]:
    """The one message a draft answers, or the refusal that names why not.

    Returns the thread the answer publishes beside the thread's root
    subject: the answer names the subject a reply carries, while the card
    records the root, and the two are not the same word.
    """
    mail = getattr(server, "mail", None)
    view = mail.view() if mail is not None else {}
    state = str(view.get("state") or "")
    if mail is None or state != mail_watcher.STATE_WATCHING:
        cause, fix = MAIL_CAUSES.get(state, MAIL_CAUSES["off"])
        raise InsightError(
            "insight:mail-off",
            _say(f"Nothing was drafted: {cause}, so the thread could not be looked up. {fix}"),
            503,
        )
    messages = view.get("messages") or []
    matches = [message for message in messages if _same_thread(message, subject, sender)]
    if not matches:
        raise InsightError("insight:thread-missing", _say(_missing_thread(subject)), 404)
    if len(matches) > 1:
        raise InsightError(
            "insight:thread-ambiguous", _say(_ambiguous_thread(subject, matches)), 409
        )
    message = matches[0]
    try:
        recipients = reply_recipients(message, self_address=mail.self_address)
    except ValueError:
        raise InsightError(
            "insight:thread-unreplyable", _say(_unreplyable(subject)), 409
        ) from None
    root = message.thread or message.subject
    return (
        {"id": message.id, "to": _addresses(recipients), "subject": reply_subject(root)},
        root,
    )


def _same_thread(message: Any, subject: str, sender: str) -> bool:
    """Whether a message header is the thread a press names, exactly.

    A press may name the thread itself ("Budget") or the subject a reply
    carries ("Re: Budget"), because the pressed page echoes back the subject
    the desk gave it; both are that thread. Nothing looser matches, so a
    near miss refuses rather than answering the wrong conversation.
    """
    wanted = normalise(subject)
    named = {
        normalise(message.subject),
        normalise(message.thread),
        normalise(reply_subject(message.thread or message.subject)),
    }
    return wanted in named and _same_sender(message.sender, sender)


def _same_sender(header: str, sender: str) -> bool:
    """Whether a From header names the sender a press names, case aside.

    A press carries the header, the display name, or the address; each is
    compared whole against the header's own parts, so half a name never
    resolves to somebody else's thread.
    """
    name, address = parseaddr(str(header or ""))
    return normalise(sender) in {normalise(header), normalise(name), normalise(address)}


def _addresses(recipients: str) -> list[str]:
    """The recipients as the list an answer carries, one address per entry."""
    return [part.strip() for part in recipients.split(",") if part.strip()]


def _stage(
    server: Any, thread: dict, root: str, draft: str, source: str
) -> tuple[bool, str | None]:
    """One drafted reply in the inbox, or the card that is already there.

    The card carries the same meta a hand-typed reply carries, so the
    existing acceptance path writes it without knowing who typed it. Nothing
    here writes an .eml: accepting the card stays the only writer.
    """
    inbox = getattr(server, "inbox", None)
    if inbox is None:
        raise InsightError("insight:inbox-off", _say(INBOX_OFF), 503)
    for card in inbox.waiting(include_snoozed=True):
        meta = card.meta if isinstance(card.meta, dict) else {}
        draft_info = meta.get("mailDraft")
        if not isinstance(draft_info, dict):
            continue
        if str(draft_info.get("messageId") or "") != thread["id"]:
            continue
        # The same words for the same thread are the same card: pressing
        # twice must not leave the user with two of everything.
        if card.draft.strip() == draft:
            return False, card.id
    card = inbox.add(
        kind="suggestion",
        origin=_origin(source),
        title=f"Drafted reply: {thread['subject']}",
        body=f"To: {', '.join(thread['to'])}",
        action_label="Write to outbox",
        draft=draft,
        meta={
            "mailDraft": {
                "messageId": thread["id"],
                "to": ", ".join(thread["to"]),
                "subject": thread["subject"],
                "thread": root,
            }
        },
    )
    return True, card.id


def _origin(source: str) -> str:
    """The card's origin: which of the two drafts this is, then what accepting does."""
    label = "Drafted by the model" if source == "model" else "Skeleton, not a model draft"
    return (
        f"{label}. Accepting writes the .eml to the local outbox folder; "
        "sending it stays yours."
    )


def _sender_label(header: str) -> str:
    """Who a message is from, as a name when it has one, else its address."""
    name, address = parseaddr(str(header or ""))
    return name.strip() or address.strip() or str(header or "").strip()


def _senders(messages: list) -> str:
    """The senders of some messages, named so the user can tell them apart.

    One correspondent writing twice under the same subject is the usual
    ambiguity, so a repeated name is said once: the subject already
    distinguishes the thread, and a name twice would only look like a bug.
    """
    labels: list[str] = []
    for message in messages:
        label = _sender_label(message.sender)
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return "no sender shown"
    if len(labels) > 3:
        labels = labels[:3] + [f"{len(labels) - 3} more"]
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" and {labels[-1]}"


def _missing_thread(subject: str) -> str:
    """The refusal when the folder holds no message of that subject from
    that sender: what did not happen, and why. _say appends the
    disclosure of what would have travelled, keeping the refusal and the
    promise one sentence."""
    return (
        f'Nothing was drafted: the mail folder has no message with the subject '
        f'"{subject}" from that sender, so there is no thread to answer.'
    )


def _unstageable(subject: str) -> str:
    """The refusal when staging was asked for without a sender to resolve
    the thread by: there is nothing to look up, so nothing to put a card
    on."""
    return (
        f'Nothing was staged: the request does not say who the thread '
        f'"{subject}" is from, so there is no thread to put a card on.'
    )


def _ambiguous_thread(subject: str, messages: list) -> str:
    """The refusal when more than one message answers the same name, with
    the senders named (_senders) so the user can see the choice the desk
    refused to make for them."""
    return (
        f'Nothing was drafted: more than one message has the subject "{subject}" '
        f"({_senders(messages)}), so the desk cannot tell which thread to answer."
    )


def _unreplyable(subject: str) -> str:
    """The refusal when every address on the thread is this desk's own:
    a reply would go nowhere, so none is drafted."""
    return (
        f'Nothing was drafted: every address on "{subject}" belongs to this '
        f"desk, so there is nobody to reply to."
    )


def _say(sentence: str, disclosure: tuple[str, ...] = DISCLOSURE) -> str:
    """A refusal's message: the sentence, then what would have been sent."""
    return " ".join((sentence,) + disclosure)


def _explain(body: dict, complete: Callable[[str], str] | None) -> dict:
    """One finding explained, or the reason it was not."""
    text = str(body.get("text") or "").strip()
    if not text:
        raise InsightError("insight:bad-request", "An explanation needs the finding it explains.")
    if len(text) > MAX_FINDING:
        raise InsightError("insight:bad-request", "That finding is too long to explain.")
    if complete is None:
        raise InsightError("insight:model-off", _say(MODEL_OFF_EXPLAIN, EXPLAIN_DISCLOSURE), 409)
    cause = ""
    try:
        answer = complete(EXPLAIN_PROMPT + text)
    except Exception as exc:  # noqa: BLE001 - a failed explanation is a sentence, not a crash
        answer = ""
        # The adapter's pinned cause (a timeout, a rejected key, a
        # redirect) names the recovery; anything else keeps the generic
        # line, because a bare crash's text names nothing.
        cause = str(exc) if isinstance(exc, LlmUnavailable) else ""
    explanation = answer.strip() if isinstance(answer, str) else ""
    if not explanation:
        note = "The model did not answer, so nothing is explained."
        if cause:
            note = f"The model did not answer ({cause}), so nothing is explained."
        return {
            "status": "empty",
            "text": "",
            "source": "none",
            "disclosure": list(EXPLAIN_DISCLOSURE),
            "note": note,
        }
    return {
        "status": "draft",
        "text": explanation,
        "source": "model",
        "disclosure": list(EXPLAIN_DISCLOSURE),
        "note": "",
    }


def _counter(body: dict, complete: Callable[[str], str] | None) -> dict:
    """One conclusion checked against counter-evidence, or the reason not.

    The text is the press's own bounded payload: the answer's summary and
    the falsification criterion the card printed, nothing else, so the
    model argues against exactly what the user read."""
    text = str(body.get("text") or "").strip()
    if not text:
        raise InsightError(
            "insight:bad-request", "A check needs the answer and criterion it tests."
        )
    if len(text) > MAX_FINDING:
        raise InsightError("insight:bad-request", "That text is too long to check.")
    if complete is None:
        raise InsightError(
            "insight:model-off", _say(MODEL_OFF_COUNTER, COUNTER_DISCLOSURE), 409
        )
    cause = ""
    try:
        answer = complete(COUNTER_PROMPT + text)
    except Exception as exc:  # noqa: BLE001 - a failed check is a sentence, not a crash
        answer = ""
        # The adapter's pinned cause (a timeout, a rejected key, a
        # redirect) names the recovery; anything else keeps the generic
        # line, because a bare crash's text names nothing.
        cause = str(exc) if isinstance(exc, LlmUnavailable) else ""
    counter = answer.strip() if isinstance(answer, str) else ""
    if not counter:
        note = "The model did not answer, so nothing is checked."
        if cause:
            note = f"The model did not answer ({cause}), so nothing is checked."
        return {
            "status": "empty",
            "text": "",
            "source": "none",
            "disclosure": list(COUNTER_DISCLOSURE),
            "note": note,
        }
    return {
        "status": "draft",
        "text": counter,
        "source": "model",
        "disclosure": list(COUNTER_DISCLOSURE),
        "note": "",
    }
