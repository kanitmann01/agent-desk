"""The Outlook Brief: what arrived, what matters, and how to start a reply.

Every input is a header-only Message (see mail/core.py): there is no body
field, so nothing here can quote one. The brief is three pure functions
over the same folder read the mail page uses:

  digest_rows      the active threads, newest first, with sender and age
  top_message      the one message most worth opening, with its reasons
  reply_starters   three openers built from the subject line only

The score is a small, explainable rule set rather than a model call. The
plugin manifest declares llm false and this module imports no client.
"""

import re
from dataclasses import dataclass

from nexuusbot.mail.core import Message, latest_by_thread, recent_threads

TOP_HOURS = 72  # the most-important window: long enough to survive a quiet day

_RE_PREFIX = re.compile(r"^(?:re|fw|fwd):\s*", re.IGNORECASE)

URGENT_WORDS = {
    "urgent": 5, "asap": 5, "action required": 5, "immediate": 4,
    "deadline": 4, "eod": 4, "today": 3, "approval": 4, "approve": 4,
    "sign": 3, "blocked": 4, "decision": 3, "invoice": 3, "payment": 3,
    "contract": 3, "board": 3, "customer": 2, "escalation": 4,
    "please": 2, "review": 2, "question": 2, "confirm": 2,
}

QUESTION_WORDS = ("can you", "could you", "would you", "do you", "are you",
                  "when will", "what is", "how do")


@dataclass(frozen=True)
class TopMessage:
    """The chosen message plus every reason it won, in plain words."""

    message: Message
    score: int
    why: str


def sender_name(sender: str) -> str:
    """A sender as a person reads it: display name first, address second."""
    text = (sender or "").strip()
    if "<" in text and text.endswith(">"):
        name = text.split("<", 1)[0].strip().strip('"')
        if name:
            return name
    return text or "(unknown sender)"


def age_words(seconds: float) -> str:
    """A header timestamp as age, never as an invented arrival time."""
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = int(seconds // 3600)
    if hours < 24:
        return f"{hours} h ago"
    return f"{int(seconds // 86400)} d ago"


def _subject(message: Message) -> str:
    """The subject as written, or the placeholder used when it is empty."""
    return (message.subject or "").strip() or "(no subject)"


def _display_subject(message: Message) -> str:
    """The subject a person should read: no Re: prefix, no invented text."""
    return _RE_PREFIX.sub("", _subject(message)).strip()


def _topic(message: Message) -> str:
    """The subject a starter can quote: Re: stripped, kept short."""
    text = _display_subject(message)
    return text if len(text) <= 80 else text[:77].rstrip() + "..."


def _importance_bonus(message: Message) -> int:
    """The score adjustment a message's importance header earns.

    High and urgent add 5, low subtracts 2, and normal or an unrecognised value
    changes nothing, so an unusual header never skews the ranking.
    """
    value = (message.importance or "").strip().lower()
    if value in ("high", "1", "urgent"):
        return 5
    if value in ("normal", "3", "medium"):
        return 0
    if value in ("low", "5"):
        return -2
    return 0


def score_message(message: Message, now: float,
                  self_address: str = "") -> tuple[int, list[str]]:
    """A small, explainable score and the reasons that produced it."""
    score = 0
    reasons: list[str] = []
    subject = _subject(message).lower()
    for phrase, weight in URGENT_WORDS.items():
        if phrase in subject:
            score += weight
            reasons.append(f"subject says \"{phrase}\"" if weight >= 4 else "")
            break
    if any(word in subject for word in QUESTION_WORDS) or subject.endswith("?"):
        score += 2
        reasons.append("asks for an answer")
    bonus = _importance_bonus(message)
    if bonus:
        score += bonus
        if bonus > 0:
            reasons.append("marked high importance")
    mine = self_address.lower()
    if mine and mine in (message.to or "").lower():
        score += 2
        reasons.append("addressed to you")
    age = max(0.0, now - message.date_ts) if message.date_ts else 0.0
    if message.date_ts:
        if age <= 2 * 3600:
            score += 3
            reasons.append("arrived in the last two hours")
        elif age <= 24 * 3600:
            score += 2
            reasons.append("arrived today")
        elif age <= TOP_HOURS * 3600:
            score += 1
            reasons.append("arrived in the last three days")
    sender = (message.sender or "").lower()
    if "no-reply" in sender or "noreply" in sender or "donotreply" in sender:
        score -= 4
    return score, [reason for reason in reasons if reason]


def digest_rows(messages: list[Message], now: float,
                hours: float = 24) -> list[dict]:
    """Active threads as render rows: subject, last sender, count and age."""
    latest = latest_by_thread(messages)
    rows = []
    for name in recent_threads(messages, now, hours=hours):
        last = latest[name]
        count = sum(1 for message in messages if message.thread == name)
        age = age_words(max(0.0, now - last.date_ts)) if last.date_ts else "undated"
        rows.append({
            "primary": name or "(no subject)",
            "secondary": sender_name(last.sender),
            "meta": f"{count} msg · {age}",
            "_ts": last.date_ts,
        })
    rows.sort(key=lambda row: row["_ts"], reverse=True)
    return [{"primary": row["primary"], "secondary": row["secondary"],
             "meta": row["meta"]} for row in rows]


def top_message(messages: list[Message], now: float,
                self_address: str = "") -> TopMessage | None:
    """The message most worth opening in the last three days, or None."""
    cutoff = now - TOP_HOURS * 3600
    candidates = [message for message in messages
                  if message.date_ts and message.date_ts >= cutoff]
    if not candidates:
        return None
    scored = []
    for message in candidates:
        score, reasons = score_message(message, now, self_address)
        scored.append((score, message.date_ts, reasons, message))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    score, _ts, reasons, message = scored[0]
    why = "; ".join(reasons) if reasons else "the newest message in the last three days"
    return TopMessage(message=message, score=score, why=why)


def reply_starters(top: TopMessage | None) -> list[dict]:
    """Three openers from the subject line, labelled by tone.

    These are starters, not drafts: no body was read, so the copy says
    only what the subject supports and leaves the specifics to the user.
    """
    if top is None:
        return []
    message = top.message
    topic = _topic(message)
    person = sender_name(message.sender).split()[0] if sender_name(message.sender) else "there"
    subject = _subject(message).lower()
    if subject.endswith("?") or any(word in subject for word in QUESTION_WORDS):
        direct = f"Good question. I will check the details on \"{topic}\" and come back with a clear answer."
    elif any(word in subject for word in ("urgent", "asap", "action required", "deadline", "eod")):
        direct = f"I have \"{topic}\" and I am on it. I will send the specifics shortly."
    elif any(word in subject for word in ("approval", "approve", "sign", "decision")):
        direct = f"I am reviewing \"{topic}\" now. I will confirm the decision by the end of the day."
    else:
        direct = f"Thanks {person}. I have \"{topic}\" and will review it today."
    return [
        {"primary": direct, "secondary": "Direct", "meta": "reply starter"},
        {"primary": f"Thanks {person}. Could you confirm the deadline and exactly what you need from me on \"{topic}\"?",
         "secondary": "Clarify", "meta": "reply starter"},
        {"primary": f"Noted on \"{topic}\". I will come back with next steps shortly.",
         "secondary": "Brief", "meta": "reply starter"},
    ]


def brief(messages: list[Message], now: float,
          self_address: str = "", hours: float = 24) -> dict:
    """Every binding the Outlook Brief renders, from one folder read."""
    threads = digest_rows(messages, now, hours=hours)
    top = top_message(messages, now, self_address)
    if top is None:
        top_subject = "No recent message"
        top_line = f"The folder has {len(messages)} messages, none in the last three days."
        top_why = "Nothing in this window needs a reply."
        starters: list[dict] = []
    else:
        top_subject = _display_subject(top.message)
        age = age_words(max(0.0, now - top.message.date_ts))
        top_line = f"{sender_name(top.message.sender)} · {age}"
        top_why = top.why
        starters = reply_starters(top)
    return {
        "messages": len([m for m in messages if m.date_ts and m.date_ts >= now - hours * 3600]),
        "threads": len(threads),
        "threadRows": threads,
        "topEmailSubject": top_subject,
        "topEmailLine": top_line,
        "topEmailWhy": top_why,
        "replyOptions": starters,
        "windowNote": ("From message headers only. Bodies are never read; "
                       "starters are built from the subject line."),
    }