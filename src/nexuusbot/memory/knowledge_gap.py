"""The assistant junk detector: why a text would be dropped on retain.

A verbatim port of the donor's src/knowledge-gap.ts (ticket #91): the
lead-in and self-reference strips, the knowledge-gap, inability and
session-narration predicates, and the placeholder and empty checks.
`junk_reason` names why a text is junk (the hygiene sweep's vocabulary
in a later ticket); `is_assistant_knowledge_gap` is the retain filter,
and it is deliberately the whole junk test, because every sentence must
be assistant junk before a candidate drops: a disclaimer mixed with any
other sentence stays, someone else's negative stays, and a dated
first-person experience stays.
"""

import re

# The donor's JUNK_REASONS.
JUNK_REASONS = ("knowledge-gap", "inability", "session-narration", "unknown", "empty")

_PLACEHOLDERS = frozenset(
    {"unknown", "n/a", "na", "none", "null", "undefined", "tbd", "unk"}
)


def junk_reason(text: str) -> str | None:
    """Why retain() would drop this text, or None when it is a real fact."""
    placeholder = placeholder_reason(text)
    if placeholder:
        return placeholder
    sentences = sentences_of(normalize(text))
    if not sentences:
        return "empty"
    reasons: list[str] = []
    for sentence in sentences:
        reason = sentence_reason(sentence)
        if reason is None:
            return None
        reasons.append(reason)
    if "inability" in reasons:
        return "inability"
    if "knowledge-gap" in reasons:
        return "knowledge-gap"
    if "session-narration" in reasons:
        return "session-narration"
    return None


def is_assistant_knowledge_gap(text: str) -> bool:
    """True when retain() should drop a fact. remember() does not call
    this: a sentence about someone else stays, including "Maya prefers
    morning meetings" and "Maya visited Wikipedia yesterday". A
    first-person preference or dated experience stays too."""
    return junk_reason(text) is not None


def placeholder_reason(text: str) -> str | None:
    """Classify a text as empty or a bare placeholder, else None.

    "empty" covers whitespace and anything left with fewer than two
    alphanumerics ("..."); "unknown" covers the literal fillers (unknown,
    n/a, none, tbd, null ...), matched after lowercasing and dropping the
    trailing sentence punctuation, so "TBD." is still a filler.
    """
    trimmed = text.strip()
    if not trimmed:
        return "empty"
    letters = re.sub(r"[^a-z0-9]", "", trimmed, flags=re.IGNORECASE)
    if len(letters) < 2:
        return "empty"
    token = re.sub(r"[.!?]+$", "", trimmed.lower()).strip()
    if token in _PLACEHOLDERS:
        return "unknown"
    return None


def sentence_reason(sentence: str) -> str | None:
    """The junk reason for one sentence, or None when it reads as fact.

    The order is the precedence: inability, then knowledge-gap, then
    session-narration, because an inability predicate also satisfies the gap
    test. A session narrative counts only when it names no past event: "I
    opened the article yesterday" describes the world, so it stays.
    """
    predicate = assistant_predicate(sentence)
    if predicate is None:
        return None
    if is_inability(predicate):
        return "inability"
    if is_gap_predicate(predicate):
        return "knowledge-gap"
    if not names_past_event(predicate) and is_session_predicate(predicate):
        return "session-narration"
    return None


def normalize(text: str) -> str:
    """Fold case, contractions and whitespace into the form predicates match.

    Curly quotes become straight, "can't"/"won't" become "cannot"/"will not",
    the other "n't" forms lose the contraction, and runs of whitespace become
    one space. The predicate regexes are written against this form, so a
    contraction this function leaves alone will not match them.
    """
    text = text.lower()
    text = re.sub(r"[\u2018\u2019\u201a\u0060]", "'", text)
    text = re.sub(r"\bcan't\b", "cannot", text)
    text = re.sub(r"\bwon't\b", "will not", text)
    text = re.sub(
        r"\b(do|does|is|are|was|were|have|has|did|would|could|should)n't\b",
        r"\1 not",
        text,
    )
    text = re.sub(r"\bi'm\b", "i am", text)
    return " ".join(text.split())


def sentences_of(text: str) -> list[str]:
    """Split text on runs of . ! ? into non-empty fragments.

    Surrounding quote characters are stripped from each fragment. The split is
    punctuation-blind, so an abbreviation yields two fragments ("Dr" and
    "Smith went home"); that is harmless because each fragment is judged on its
    own, and the reason returned for a multi-sentence text is a precedence
    choice rather than a per-sentence verdict.
    """
    parts = [part.strip("\"'").strip() for part in re.split(r"[.!?]+", text)]
    return [part for part in parts if part]


_LEAD = re.compile(
    "^(?:(?:unfortunately|sorry|actually|currently|well|right now|at this time"
    "|as of now|note that|please note|based on (?:the |this )?(?:conversation"
    "|chat|context)|from (?:the |this )?(?:conversation|chat)"
    "|in this (?:conversation|chat)|as an ai|as a language model"
    "|as an assistant|as the assistant|as the model)[,:]?\\s+)+"
)

_SELF = re.compile(
    "^(?:the language model|this language model|the assistant|this assistant"
    "|an assistant|the model|this model|the ai|this ai|an ai|assistant|model"
    "|i am|i)\\b[:,]?\\s+"
)

_HEDGE = "(?:really |actually |currently |yet |still )?"
_ADJECTIVE = (
    "(?:specific|any|some|much|enough|further|more|additional|particular"
    "|relevant|real|available|prior|previous|stored|recorded|personal"
    "|detailed|concrete|direct|useful|reliable|special|the|a|an)"
)
_NOUN = "(?:information|info|knowledge|details|data|records?|idea|clue)"
_KNOWLEDGE = f"(?:{_ADJECTIVE}\\s+)*{_NOUN}"


def assistant_predicate(sentence: str) -> str | None:
    """The predicate of an assistant self-statement, or None if it is not one.

    Strips the conversational lead-ins ("unfortunately", "based on this
    conversation") and then the self-reference subject ("I", "the assistant",
    "the model"), plus any filler adverbs between them. Returns None when no
    subject matches, when nothing follows it, or when the remainder carries a
    contrast ("but", "however") or a semicolon: such a sentence says something
    else as well, and dropping it would discard that.
    """
    rest = _LEAD.sub("", sentence).strip()
    subject = _SELF.match(rest)
    if not subject:
        return None
    predicate = rest[subject.end():].strip()
    predicate = re.sub(
        "^(?:really |actually |currently |still |just |simply |honestly "
        "|then |also |only )+",
        "",
        predicate,
    ).strip()
    if predicate == "":
        return None
    if ";" in predicate or re.search(
        r"\b(?:but|however|although|though|except|whereas)\b", predicate
    ):
        return None
    return predicate


_MONTH = (
    "(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    "|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?"
    "|dec(?:ember)?)"
)


def names_past_event(predicate: str) -> bool:
    """A dated or relative occurrence is a world event, not this chat's
    tool use."""
    return bool(
        re.search(r"\b(?:yesterday|tomorrow|tonight)\b", predicate)
        or re.search(
            "\\b(?:last|next|this past)\\s+(?:week|month|year|night|morning"
            "|afternoon|evening|monday|tuesday|wednesday|thursday|friday"
            "|saturday|sunday)\\b",
            predicate,
        )
        or re.search(r"\bago\b", predicate)
        or re.search(
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            predicate,
        )
        or re.search(rf"\bin\s+{_MONTH}\b", predicate)
        or re.search(rf"\b{_MONTH}\s+\d{{1,2}}\b", predicate)
        or re.search(r"\b\d{4}-\d{2}-\d{2}\b", predicate)
        or re.search(r"\b(?:19|20)\d{2}\b", predicate)
        or re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", predicate)
    )


_SESSION_PREFIX = (
    "(?:(?:has |have |had |is |was |were |am |did |does |do )"
    "?(?:tried to |attempted to |proceeded to )?)"
)

_SESSION_TARGET = (
    "\\b(?:pages?|tabs?|links?|urls?|browsers?|websites?|wikipedia|wiki"
    "|search(?:es|ed|ing)?|articles?|results?|queries|query|prompts?"
    "|dialogs?|pop-?ups?|visits?|buttons?|google)\\b"
)


def is_session_predicate(predicate: str) -> bool:
    """True when the predicate narrates the assistant's own tool use.

    Redirecting, looking up, searching and clicking/pressing count on the verb
    alone. Opening, visiting, navigating, browsing, loading and the
    approve/deny/refuse/stop family need a session object too (page, tab, link,
    query, search ...), which is what separates "I opened the article" from a
    claim about the world.
    """
    if re.search(rf"^{_SESSION_PREFIX}re-?direct(?:s|ed|ing)?\b", predicate):
        return True
    if re.search(
        rf"^{_SESSION_PREFIX}(?:look(?:s|ed|ing)? up|look(?:s|ed|ing)?\s+\S+"
        rf"\s+up|search(?:es|ed|ing)?|googled)\b",
        predicate,
    ):
        return True
    if re.search(
        rf"^{_SESSION_PREFIX}(?:click(?:s|ed|ing)?|tap(?:s|ped|ping)?"
        rf"|press(?:es|ed|ing)?|typed|typing|types)\b",
        predicate,
    ):
        return True
    aimed = bool(
        re.search(
            rf"^{_SESSION_PREFIX}(?:open(?:s|ed|ing)?|visit(?:s|ed|ing)?"
            rf"|navigat(?:e|es|ed|ing)|brows(?:e|es|ed|ing)|load(?:s|ed|ing)?"
            rf"|went to|go(?:es)? to)\b",
            predicate,
        )
        or re.search(
            rf"^{_SESSION_PREFIX}(?:approv(?:e|es|ed|ing)"
            rf"|den(?:y|ies|ied|ying)|stop(?:s|ped|ping)?"
            rf"|refus(?:e|es|ed|ing)|declin(?:e|es|ed|ing)|cancels?"
            rf"|cancelled|canceled|canceling|cancelling"
            rf"|block(?:s|ed|ing)?)\b",
            predicate,
        )
    )
    return aimed and bool(re.search(_SESSION_TARGET, predicate))


def is_gap_predicate(predicate: str) -> bool:
    """True when the predicate admits not knowing something.

    Includes the unsure and unfamiliar forms and plain inability, plus the
    explicit not-know / no-knowledge / never-heard-of / cannot-find shapes. The
    noun may carry any run of filler adjectives, so "no specific stored
    information" matches where "no information" does.
    """
    if is_unsure(predicate) or is_unfamiliar(predicate) or is_inability(predicate):
        return True
    patterns = [
        rf"^(?:do|does) not {_HEDGE}(?:know|recognize)\b",
        rf"^(?:cannot|could not) {_HEDGE}(?:recall|recognize|identify)\b",
        rf"^(?:do|does) not {_HEDGE}have\s+{_KNOWLEDGE}\b",
        rf"^(?:have|has) no\s+{_KNOWLEDGE}\b",
        r"^(?:have|has) never heard of\b",
        r"^never heard of\b",
        rf"^lacks?\s+{_KNOWLEDGE}\b",
        (
            rf"^(?:cannot|could not) (?:find|locate|access|provide|give"
            rf"|offer|retrieve)\s+(?:you |me )?(?:any |specific |much "
            rf"|enough )?{_KNOWLEDGE}\b"
        ),
    ]
    return any(re.search(pattern, predicate) for pattern in patterns)


_INFORM_VERB = (
    "(?:find|locate|access|provide|give|offer|retrieve|share|answer|disclose"
    "|tell|reveal|discuss|say|talk)"
)
_INFO_WORD = r"\b(?:information|info|knowledge|details|data|answers?|questions?)\b"
_RESTRICTION = r"\bdue to (?:a |the )?(?:restrictions?|polic(?:y|ies)|guidelines|safety)\b"


def is_inability(predicate: str) -> bool:
    """True when the predicate declines on grounds of access or policy.

    A refusal verb alone is not enough: unable/cannot/not-allowed/denied must
    be aimed at information or a question ("cannot share the details"), or the
    predicate must cite a restriction or guideline. "I cannot do that" is an
    ordinary statement, not a knowledge gap.
    """
    about_info = bool(re.search(_INFO_WORD, predicate))
    restricted = bool(re.search(_RESTRICTION, predicate))
    inform_verb = bool(re.search(rf"\b{_INFORM_VERB}\b", predicate))
    if re.search(
        rf"^(?:am |is |was |were )?(?:unable|not able) to {_INFORM_VERB}\b",
        predicate,
    ) and (about_info or restricted):
        return True
    if re.search(
        rf"^(?:cannot|could not|will not) {_INFORM_VERB}\b", predicate
    ) and (about_info or restricted):
        return True
    if re.search(
        r"^(?:am |is |was |were )?not (?:allowed|permitted)\b", predicate
    ) and (about_info or (restricted and inform_verb)):
        return True
    if re.search(
        r"^(?:am |is |was |were |has been |have been )?denied\b", predicate
    ) and (about_info or re.search(r"\b(?:access|permission|restrictions?)\b", predicate)):
        return True
    return bool(
        restricted
        and re.search(
            r"\b(?:unable|not able|cannot|could not|will not|not allowed"
            r"|not permitted|denied|restricted)\b",
            predicate,
        )
        and (about_info or inform_verb)
    )


def is_unsure(predicate: str) -> bool:
    """True when the predicate doubts an identity rather than a plan.

    Both word orders are accepted ("am not sure", "unsure"), and the tail
    decides: "not sure who that is" is a gap, "not sure we should ship it" is
    not, because the doubt is about a course of action.
    """
    sure = re.search(rf"^(?:am not|is not|not) {_HEDGE}(?:sure|certain)\b\s*(.*)$", predicate)
    if sure:
        return identity_tail(sure.group(1) or "")
    unsure = re.search(r"^(?:am |is )?unsure\b\s*(.*)$", predicate)
    if not unsure:
        return False
    return identity_tail(unsure.group(1) or "")


def is_unfamiliar(predicate: str) -> bool:
    """True when the predicate disclaims familiarity or awareness.

    Unlike is_unsure, the tail is never inspected: unfamiliarity is already a
    gap about the thing named, and the four phrasings ("not familiar",
    "not aware", "unfamiliar", "unaware") cover both word orders.
    """
    return bool(
        re.search(r"^(?:am not|is not|not) familiar\b", predicate)
        or re.search(r"^(?:am not|is not|not) aware\b", predicate)
        or re.search(r"^(?:am|is) (?:unfamiliar|unaware)\b", predicate)
        or re.search(r"^(?:unfamiliar|unaware)\b", predicate)
    )


def identity_tail(tail: str) -> bool:
    """True when what follows an unsure predicate names a person or thing.

    An empty tail counts ("I am not sure."), as do the who/what/which/whom
    forms and "about|of" plus a pronoun or person. Any other tail (a plan, a
    time, an action) is not an identity question and returns False.
    """
    rest = tail.strip()
    if rest == "":
        return True
    return bool(
        re.search(r"^(?:who|what|which|whom)\b", rest)
        or re.search(
            r"^about (?:that|this|it|them|him|her|who|anyone|anybody|someone"
            r"|somebody|a person|any person)\b",
            rest,
        )
        or re.search(
            r"^of (?:that|this|it|who|anyone|anybody|someone|somebody"
            r"|a person|any person)\b",
            rest,
        )
        or re.search(r"^(?:if|whether) (?:that|this|it|who)\b", rest)
    )
