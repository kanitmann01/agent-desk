"""The English-to-plugin wizard engine (ticket #11).

A manager describes what she wants in plain English; this module turns
that into a Class D declarative plugin draft. Three guardrails keep the
engine honest:

- Vocabulary confinement. Every source, show, look, and update choice the
  wizard offers comes from ``nexuusbot.wizard.vocabulary``, and a draft can
  only use those members. Permissions are fixed by the composer: a workbook
  ask reads nothing at build time (the file is picked per instance in
  setup), any other file kind reads the one chosen glob, a web ask reads no
  files and declares its one URL host as an optional permission the consent
  flow shows, and no draft gets shell, base network, or llm. The endpoint
  (when configured) may name one plain-language label per field and write
  the human-readable copy; the composer, not the endpoint, decides what the
  manifest says.
- One gate. Drafts are judged by the same ``validate_plugin`` every
  other plugin passes: the wizard never vouches for its own output.
- Bounded effort, honest escalation. At most MAX_REPAIRS validator
  attempts; when the ask exceeds the vocabulary, or the repair budget
  runs out, the wizard raises WizardError carrying a feature_request
  payload instead of shipping a broken draft or silently narrowing the
  ask.

The llm is a prompt-to-text callable (``nexuusbot.llm.chat`` bound to
config) or None when no endpoint is configured. Every endpoint failure
degrades to the deterministic path, so the wizard works offline: the
deterministic path alone must produce a valid plugin.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from nexuusbot.validator.core import validate_plugin
from nexuusbot.validator.model import Verdict
from nexuusbot.validator.schema import ALLOWED_LICENSES, REQUIRED_KEY_TYPES
from nexuusbot.wizard import vocabulary as vocab

# The pinned public contract.
WIZARD_STATES = ("questions", "building", "preview", "approved", "escalated")
# Every source the composer can build. It is the vocabulary table's own list,
# so a source the questions offer is always one the composer can install.
VOCABULARY = tuple(source for _, source in vocab.SOURCE_CHOICES)
MAX_QUESTIONS = 5
MAX_REPAIRS = 3

STATE_QUESTIONS = "questions"
STATE_BUILDING = "building"
STATE_PREVIEW = "preview"
STATE_APPROVED = "approved"
STATE_ESCALATED = "escalated"

# Draft identity, fixed so a wizard draft is always recognizable and its
# permission surface is exactly the one glob the manager chose.
PUBLISHER = "agent-desk-wizard"
PLUGIN_VERSION = "0.1.0"
LICENSE_ID = "MIT"
DASHBOARD_ENGINE = ">=1.0.0 <2.0.0"
WIDGET_SIZE = "2x1"
WIDGET_RENDER_FILE = "widget.ui.json"
WORKSPACE_PREFIX = "${workspace}/"
PLUGIN_DATA_GLOB = "${pluginData}"
SHELL_NONE = "none"
FEATURE_REQUEST_KIND = "feature_request"
WIZARD_ID_PREFIX = "wiz-"

# Copy limits: endpoint prose goes into a manifest name and a widget
# title, so it is bounded like any other name, never a free-text dump.
TITLE_LIMIT = 80
BLURB_LIMIT = 200
REASON_LIMIT = 300
SLUG_LIMIT = 40
DEFAULT_TITLE = "Wizard widget"

GLOB_PATTERN = re.compile(
    r"[A-Za-z0-9_.\-*/\\]*[A-Za-z0-9_]\.(?:xlsx|xlsm|csv|json|ics|md)\b"
)
URL_PATTERN = re.compile(r"https?://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._\-/%]*)?")
# The deterministic fallback when no URL was named anywhere: the same
# neutral host the registry's own network plugin uses in its examples.
DEFAULT_HTTP_URL = vocab.WEB_DETAIL_DEFAULT
# json-watch always needs a selector; the deterministic composer's
# default addresses the value key a hand-maintained metric file carries.
DEFAULT_JSON_SELECTOR = "$.value"

# Asks the declarative vocabulary cannot honor. Each rule carries the
# plain-language label the escalation uses, so the refusal names what the
# manager asked for instead of talking in failure codes. Reading mail is a
# source now, so only writing mail is refused.
UNBUILDABLE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(send|sends|sending|draft|drafts|drafting|reply|replies|"
                   r"forward|forwards|forwarding|compose|composes|composing)\b"
                   r".{0,24}\b(e-?mails?|mails?|messages?)\b", re.IGNORECASE),
        "sending mail",
    ),
    (re.compile(r"\bscripts?\b", re.IGNORECASE), "running scripts"),
    (re.compile(r"\bexecut(e|es|ed|ing|ion|able)\b", re.IGNORECASE), "executing code"),
    (
        re.compile(
            r"\brun(s|ning)?\b.{0,24}\b(code|program|command|script|batch|job|process)s?\b",
            re.IGNORECASE,
        ),
        "executing code",
    ),
    (
        re.compile(r"\bcommand[- ]line\b|\bpowershell\b|\bshell\b", re.IGNORECASE),
        "command-line control",
    ),
    (
        re.compile(
            r"\b(open|launch)(s|es|ing|ed)?\b.{0,24}\b(app|application|program|exe)s?\b",
            re.IGNORECASE,
        ),
        "opening apps",
    ),
    (re.compile(r"\bcode\b", re.IGNORECASE), "executing code"),
)

# The deterministic question set, asked one at a time. It is the offline
# fallback for every endpoint failure and the only path when no AI is saved.
# Each question's options are computed from the answers already given, so the
# sets below are the source question and its default only; the rest are built
# by ``questions_for_answers``.
SOURCE_QUESTION = {
    "id": vocab.QUESTION_SOURCE,
    "question": "What should this tile watch?",
    "options": list(vocab.SOURCE_LABELS),
    "default": "An Excel workbook",
}

AUTOFILL_PROMPT = """A manager wants a dashboard tile and described it like this:
"{description}"

Fill in the four choices below for her, using only these options.

Source: {sources}
{followups}
Reply with JSON only, one object:
{{"source": "<one of the source options>",
  "detail": "<the address or file pattern, or an empty string>",
  "show": "<one of the show options for that source>",
  "look": "<one of the look options for that source and show>",
  "update": "<one of the update options for that source>",
  "reasons": {{"source": "<short sentence>", "show": "<short sentence>",
               "look": "<short sentence>", "update": "<short sentence>"}}}}

If you cannot tell, use an empty string for that field rather than guessing.
Never invent an option that is not listed."""

AUTOFILL_VOCABULARY = """
Shows and looks, per source:
{shows}

Update options, per source:
{updates}"""

STYLE_PROMPT = """A manager wants a dashboard tile and described it like this:
"{description}"

Her chosen answers:
{answers}

Give the tile a short name and one sentence describing what it shows. Do not
describe permissions or how it is built.

Reply with JSON only, one object:
{{"title": "...", "description": "..."}}"""

REPAIR_PROMPT = """The plugin validator rejected this draft manifest.

Validator failures:
{failures}

Draft manifest:
{manifest}

The data source type, the permissions and the activation events cannot change:
filesystem read of the chosen glob, network allow [] unless this is a web
source, llm allow false, shell "none". Return the same manifest with the
failures fixed.

Reply with JSON only, one object: {{"manifest": {{...the corrected manifest...}}}}"""

STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS wizard_sessions (
  id TEXT PRIMARY KEY,
  document TEXT NOT NULL
);
"""

# What a suggested manifest may carry at all: the required manifest keys
# only, so optionalPermissions (a consent grant) can never ride in.
_CARRIED_KEYS = frozenset(REQUIRED_KEY_TYPES)


def safe_slug(text: str) -> str:
    """A filesystem-safe slug from free text: lowercase, every
    non-alphanumeric run becomes one dash, capped at SLUG_LIMIT
    characters. Runs collapse and edge dashes go so the result is always
    a validator-safe id fragment; an empty result falls back to
    "widget" because ids and widget ids become directory names."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    slug = slug[:SLUG_LIMIT].rstrip("-")
    return slug or "widget"


class WizardError(Exception):
    """A named wizard refusal: ``code`` is the stable vocabulary,
    ``status`` the HTTP status, and ``feature_request`` (when present)
    the honest escalation payload an inbox card can be built from."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 409,
        feature_request: dict | None = None,
    ) -> None:
        """Keep the named code, the HTTP status and any escalation payload."""
        super().__init__(message)
        self.code = code
        self.status = status
        self.feature_request = feature_request


@dataclass
class WizardSession:
    """One build conversation, queryable end to end. The full original
    description stays verbatim: an escalation that paraphrases the ask
    would hand the inbox a rumor instead of a request."""

    id: str
    state: str = STATE_QUESTIONS
    description: str = ""
    questions: list[dict] = field(default_factory=list)
    answers: dict = field(default_factory=dict)
    attempts: int = 0
    draft: dict | None = None
    feature_request: dict | None = None
    created_ts: float = 0.0
    # True when the description filled at least one choice in, so the page can
    # say so instead of presenting the fill as the manager's own answers.
    autofilled: bool = False
    # The one-line why per filled field, for the fill screen. Copy only.
    reasons: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject a state outside WIZARD_STATES."""
        if self.state not in WIZARD_STATES:
            raise ValueError(f"unknown wizard state: {self.state!r}")

    def to_json(self) -> dict:
        """The API payload: everything queryable, original text included."""
        return {
            "id": self.id,
            "state": self.state,
            "description": self.description,
            "questions": copy.deepcopy(self.questions),
            "answers": dict(self.answers),
            "autofilled": self.autofilled,
            "reasons": dict(self.reasons),
            "attempts": self.attempts,
            "draft": copy.deepcopy(self.draft),
            "featureRequest": copy.deepcopy(self.feature_request),
            "createdTs": self.created_ts,
        }


class WizardStore:
    """Sessions in SQLite: one row per conversation, the whole session
    in the document column, so the API never reassembles one."""

    def __init__(
        self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time
    ) -> None:
        """Adopt the connection and create the session table if it is absent.

        The clock supplies the creation timestamp of every new session.
        """
        self.conn = conn
        self.clock = clock
        conn.executescript(STORE_SCHEMA)
        conn.commit()

    def create(self, description: str) -> WizardSession:
        """Start a session in the questions state and persist it.

        The description is stored verbatim, because an escalation hands it on
        unchanged; a blank or non-text one raises ValueError.
        """
        if not isinstance(description, str) or not description.strip():
            raise ValueError("a wizard session needs a plain-English description")
        session = WizardSession(
            id=f"{WIZARD_ID_PREFIX}{uuid.uuid4().hex[:12]}",
            state=STATE_QUESTIONS,
            description=description,
            created_ts=self.clock(),
        )
        self._write(session)
        return session

    def get(self, session_id: str) -> WizardSession:
        """Read one session by id, or raise WizardError wizard:unknown with 404."""
        row = self.conn.execute(
            "SELECT document FROM wizard_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise WizardError("wizard:unknown", f"no wizard session {session_id}", 404)
        return _session_from_document(json.loads(row[0]))

    def save(self, session: WizardSession) -> None:
        """Persist the session's current fields over its stored document."""
        self._write(session)

    def _write(self, session: WizardSession) -> None:
        """Replace the session's row with its whole serialized document."""
        document = json.dumps(
            {
                "id": session.id,
                "state": session.state,
                "description": session.description,
                "questions": session.questions,
                "answers": session.answers,
                "autofilled": session.autofilled,
                "reasons": session.reasons,
                "attempts": session.attempts,
                "draft": session.draft,
                "feature_request": session.feature_request,
                "created_ts": session.created_ts,
            },
            ensure_ascii=False,
        )
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO wizard_sessions (id, document) VALUES (?, ?)",
                (session.id, document),
            )


def _session_from_document(document: dict) -> WizardSession:
    """Rebuild a session from its stored document.

    Every absent key falls back to the dataclass default, so a document written
    by an earlier build still loads; the state is checked by WizardSession
    itself.
    """
    return WizardSession(
        id=str(document.get("id", "")),
        state=str(document.get("state", STATE_QUESTIONS)),
        description=str(document.get("description", "")),
        questions=list(document.get("questions") or []),
        answers=dict(document.get("answers") or {}),
        attempts=int(document.get("attempts") or 0),
        draft=document.get("draft"),
        feature_request=document.get("feature_request"),
        created_ts=float(document.get("created_ts") or 0.0),
        autofilled=bool(document.get("autofilled") or False),
        reasons=dict(document.get("reasons") or {}),
    )


# ---- reply parsing -----------------------------------------------------


def _load_json_reply(reply: object) -> object:
    """Parse an endpoint reply as JSON, tolerating a fenced code block
    and prose around the payload; raise ValueError when there is none."""
    if not isinstance(reply, str):
        raise ValueError("the endpoint reply is not text")
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", reply, re.DOTALL)
    payload = fence.group(1) if fence else reply.strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = payload.find(opener), payload.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(payload[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in the endpoint reply")


# ---- escalation payload ------------------------------------------------


def _feature_request(description: str, answers: dict) -> Callable[[str], dict]:
    """Build the escalation payloads for one build run: the full original
    ask travels with every refusal, verbatim."""

    def make(reason: str) -> dict:
        """Build the escalation payload for one refusal.

        The description and the answers travel verbatim; the reason is cut at
        REASON_LIMIT characters.
        """
        return {
            "description": description,
            "answers": dict(answers),
            "reason": reason[:REASON_LIMIT],
            "kind": FEATURE_REQUEST_KIND,
        }

    return make


def _unbuildable_reason(description: str) -> str:
    """The plain-language label for the first out-of-vocabulary demand in
    the description, or "" when the ask stays inside the vocabulary."""
    for pattern, label in UNBUILDABLE_RULES:
        if pattern.search(description):
            return label
    return ""


# ---- deterministic compiling helpers -----------------------------------


def _short_text(text: object, limit: int) -> str:
    """Collapse whitespace and cut at a word edge; empty in, empty out."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned or len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit].rsplit(" ", 1)[0]
    return ((cut or cleaned[:limit]).rstrip(",;:")) + "..."


def _clean_glob(candidate: object) -> str:
    """A workspace-relative glob, or "" when the candidate is not one:
    absolute paths, escapes and whitespace would quietly widen the read."""
    if not isinstance(candidate, str):
        return ""
    glob = candidate.strip().replace("\\", "/")
    if glob.startswith(WORKSPACE_PREFIX):
        glob = glob[len(WORKSPACE_PREFIX) :]
    glob = glob.lstrip("/")
    if not glob or ".." in glob or any(char in glob for char in " \t\n\r"):
        return ""
    return glob


def _glob_in_text(description: str) -> str:
    """Return the first file glob written in the description, or no match.

    The match is raw: _clean_glob still decides whether it may be watched.
    """
    match = GLOB_PATTERN.search(description)
    return match.group(0) if match else ""


def _file_glob(description: str, answers: dict, source_type: str) -> str:
    """Return the workspace-relative glob to watch for one source type.

    The chosen detail is tried first, then a glob written in the description,
    and both must survive _clean_glob; when neither does, the source type's
    first offered pattern applies.
    """
    for candidate in (answers.get(vocab.QUESTION_DETAIL), _glob_in_text(description)):
        glob = _clean_glob(candidate)
        if glob:
            return glob
    return vocab.DEFAULT_FILE_DETAIL[source_type]


def _http_url(description: str, answers: dict) -> str:
    """The absolute http(s) URL an http-get build watches.

    The first URL written in the answers or the description wins; with no
    URL anywhere the neutral default applies, so the wizard's own web
    option always finishes a valid plugin instead of dead-ending.
    """
    texts = [str(value) for value in answers.values() if isinstance(value, str)]
    for text in texts + [description]:
        match = URL_PATTERN.search(text)
        if match:
            return match.group(0).rstrip("/.,;:!?")
    return DEFAULT_HTTP_URL


def _http_host(url: str) -> str:
    """The allowlist host of a URL: the one host the source may fetch."""
    return (urlsplit(url).hostname or "").lower() or "example.com"


@dataclass
class Choice:
    """One answered field of the wizard, once its label is resolved.

    An unanswered field is None on the Choice's owner, never a default filled
    in behind the manager's back: the whole point of the executive path is
    that the tile is what was chosen.
    """

    source_type: str
    detail: str = ""
    show: str = ""
    look: str = ""
    update_mode: str = ""
    update_value: str = ""


def resolve_choice(answers: dict) -> Choice | None:
    """Resolve the answers into a Choice, or None while any field is open.

    A label outside the legal set for its field leaves that field open, which
    is how a dropped autofill and a manager's skip are both handled: the
    question stays on the page. ``detail`` is only required for a web source,
    because a file pattern has a usable default.
    """
    source_type = vocab.source_for_label(answers.get(vocab.QUESTION_SOURCE))
    if not source_type:
        return None
    show = vocab.show_for_label(answers.get(vocab.QUESTION_SHOW), source_type)
    if not show:
        return None
    look = vocab.look_for_label(answers.get(vocab.QUESTION_LOOK), source_type, show)
    if not look:
        return None
    update_mode, update_value = vocab.update_for_label(
        answers.get(vocab.QUESTION_UPDATE), source_type)
    if not update_mode:
        return None
    detail = str(answers.get(vocab.QUESTION_DETAIL) or "").strip()
    if source_type == "http-get" and not detail:
        return None
    return Choice(source_type, detail, show, look, update_mode, update_value)


def questions_for_answers(answers: dict) -> list[dict]:
    """The questions still open on the path these answers have chosen.

    Each question's options depend on the answers before it, so the set is
    computed rather than fixed: the source list, then the one detail that
    source needs, then the shows it can bind, then the looks that fit that
    show, then the update choices it admits. A step with a single legal
    answer is folded into the next one instead of being asked.

    A question already answered comes back with that answer selected, so the
    page shows the manager the choice that is actually in force (an autofill's
    included) rather than the first option.
    """
    def with_default(question: dict) -> dict:
        """Return the question with its chosen answer, or its first option."""
        chosen = answers.get(question["id"])
        if isinstance(chosen, str) and chosen in question["options"]:
            return {**question, "default": chosen}
        return question

    open_questions = [with_default(dict(SOURCE_QUESTION))]
    source_type = vocab.source_for_label(answers.get(vocab.QUESTION_SOURCE))
    if not source_type:
        return open_questions

    if source_type in vocab.FILE_DETAIL:
        open_questions.append(with_default({
            "id": vocab.QUESTION_DETAIL,
            "question": "Which file should it read?",
            "options": list(vocab.FILE_DETAIL[source_type]),
            "default": vocab.DEFAULT_FILE_DETAIL[source_type],
        }))
    elif source_type == "http-get":
        open_questions.append({
            "id": vocab.QUESTION_DETAIL,
            "question": "Which web address should it read?",
            "options": [],
            "default": str(answers.get(vocab.QUESTION_DETAIL) or ""),
        })

    shows = vocab.shows_for(source_type)
    if shows:
        open_questions.append(with_default({
            "id": vocab.QUESTION_SHOW,
            "question": "What should the tile show?",
            "options": [vocab.SHOW_LABELS[show] for show in shows],
            "default": vocab.SHOW_LABELS[shows[0]],
        }))

    show = vocab.show_for_label(answers.get(vocab.QUESTION_SHOW), source_type)
    looks = vocab.looks_for(source_type, show) if show else ()
    if len(looks) > 1:
        open_questions.append(with_default({
            "id": vocab.QUESTION_LOOK,
            "question": "How should it look?",
            "options": [vocab.LOOK_LABELS[look] for look in looks],
            "default": vocab.LOOK_LABELS[looks[0]],
        }))

    open_questions.append(with_default({
        "id": vocab.QUESTION_UPDATE,
        "question": "When should it update?",
        "options": list(vocab.update_choices(source_type)),
        "default": vocab.UPDATE_VIEW_LABEL,
    }))
    return open_questions


# The first question on a fresh description: the compatibility name the server
# and the tests import. It is the same list ``questions_for_answers`` returns.
DEFAULT_QUESTIONS: list[dict] = questions_for_answers({})


def _activation_events(slug: str, choice: Choice) -> list[str]:
    """The one widget event plus the one update event the choice names.

    The change topic is derived from the source, so a manager never picks an
    event name and a model can never introduce one.
    """
    events = [f"onWidget:{slug}"]
    if choice.update_mode == vocab.UPDATE_CLOCK:
        events.append(f"onSchedule:{choice.update_value}")
    elif choice.update_mode == vocab.UPDATE_HOOK:
        events.append(f"onHook:{choice.update_value}")
    return events


def _autofill_followups() -> str:
    """The autofill prompt's vocabulary: shows, looks, and update choices."""
    shows = []
    for _, source_type in vocab.SOURCE_CHOICES:
        for show in vocab.shows_for(source_type):
            looks = vocab.looks_for(source_type, show)
            shows.append(
                f"- {source_type} / {vocab.SHOW_LABELS[show]}: "
                + ", ".join(vocab.LOOK_LABELS[look] for look in looks))
    updates = [f"- {source_type}: " + ", ".join(vocab.update_choices(source_type))
               for _, source_type in vocab.SOURCE_CHOICES]
    return AUTOFILL_VOCABULARY.format(shows="\n".join(shows),
                                      updates="\n".join(updates))


def _checked_autofill(data: dict) -> dict:
    """Keep only the autofilled fields whose labels are legal for their field.

    A rejected field is omitted, never defaulted, so the caller can tell the
    manager which choices are still theirs to make. The reasons come back
    under their own key, beside the answers rather than inside them.
    """
    checked: dict = {}
    source_type = vocab.source_for_label(data.get("source"))
    if not source_type:
        return checked
    checked["source"] = data["source"].strip()

    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        checked["detail"] = detail.strip()

    show = vocab.show_for_label(data.get("show"), source_type)
    if show:
        checked["show"] = vocab.SHOW_LABELS[show]
        look = vocab.look_for_label(data.get("look"), source_type, show)
        if look:
            checked["look"] = vocab.LOOK_LABELS[look]

    update_mode, _ = vocab.update_for_label(data.get("update"), source_type)
    if update_mode:
        checked["update"] = data["update"].strip()
    return checked


def checked_reasons(data: dict, checked: dict) -> dict:
    """The short reasons for the fields that survived, keyed by field.

    They are copy for the fill screen, never answers: storing them as
    answers would put prose where the composer expects a label.
    """
    reasons = data.get("reasons") if isinstance(data, dict) else None
    if not isinstance(reasons, dict):
        return {}
    return {
        key: _short_text(value, BLURB_LIMIT)
        for key, value in reasons.items()
        if key in checked and _short_text(value, BLURB_LIMIT)
    }


def merge_answers(earlier: dict, filled: dict) -> dict:
    """The filled choices laid over the answers already given.

    A field the manager already answered wins, so an autofill can never
    overwrite a correction they made.
    """
    merged = dict(earlier or {})
    for key, value in (filled or {}).items():
        merged.setdefault(key, value)
    return normalize_answers(merged)


def normalize_answers(answers: dict) -> dict:
    """Drop choices that the chosen source does not offer.

    Changing the source makes the old show, look, detail and update choices
    meaningless: a mail list's look is not a workbook's. Keeping only the
    legal fields is what makes the questions re-ask exactly what the new
    source needs, instead of silently building a stale combination.
    """
    answers = dict(answers or {})
    source_type = vocab.source_for_label(answers.get(vocab.QUESTION_SOURCE))
    if not source_type:
        return answers
    kept = {vocab.QUESTION_SOURCE: answers[vocab.QUESTION_SOURCE]}

    detail = answers.get(vocab.QUESTION_DETAIL)
    if isinstance(detail, str) and detail.strip():
        kept[vocab.QUESTION_DETAIL] = detail.strip()

    show = vocab.show_for_label(answers.get(vocab.QUESTION_SHOW), source_type)
    if show:
        kept[vocab.QUESTION_SHOW] = vocab.SHOW_LABELS[show]
        look = vocab.look_for_label(answers.get(vocab.QUESTION_LOOK), source_type, show)
        if look:
            kept[vocab.QUESTION_LOOK] = vocab.LOOK_LABELS[look]

    update_mode, _ = vocab.update_for_label(answers.get(vocab.QUESTION_UPDATE), source_type)
    if update_mode:
        kept[vocab.QUESTION_UPDATE] = answers[vocab.QUESTION_UPDATE].strip()
    return kept


def _human_copy(description: str, style: dict) -> tuple[str, str]:
    """Widget title and blurb: the endpoint's copy when usable, else the
    manager's own words, else a neutral default."""
    title = (
        _short_text(style.get("title"), TITLE_LIMIT)
        or _short_text(description, TITLE_LIMIT)
        or DEFAULT_TITLE
    )
    blurb = _short_text(style.get("description"), BLURB_LIMIT)
    return title, blurb


def _sanitize_manifest(raw: object, skeleton: dict) -> dict:
    """The safety floor between the endpoint and the validator.

    A suggested manifest may restructure anything inside the vocabulary,
    but it can never add keys outside the manifest schema, grant
    permissions, widen the filesystem read, use a data source outside
    VOCABULARY, or touch identity (schemaVersion, class, id, publisher).
    Whatever it omits falls back to the deterministic skeleton, and the
    validator, not the suggestion, has the final word on what survives.
    A config-backed skeleton keeps that shape on the suggestion too:
    its config kinds are pinned and its widgets stay file-less; an
    http-get skeleton keeps its network allowance pinned the same way.
    """
    floored: dict = {}
    if isinstance(raw, dict):
        for key in _CARRIED_KEYS:
            if key in raw:
                floored[key] = copy.deepcopy(raw[key])

    # Identity and permissions are never negotiable. A config-backed
    # skeleton pins its config kinds too, so the suggestion can shape
    # the copy but never unmake the setup-state install (T2); an
    # http-get skeleton pins its network allowance the same way, so a
    # suggestion can neither widen it nor strand the source's fetch.
    floored["schemaVersion"] = 1
    floored["class"] = "declarative"
    floored["publisher"] = PUBLISHER
    floored["id"] = skeleton["id"]
    floored["permissions"] = copy.deepcopy(skeleton["permissions"])
    if "config" in skeleton:
        floored["config"] = copy.deepcopy(skeleton["config"])
    if "optionalPermissions" in skeleton:
        floored["optionalPermissions"] = copy.deepcopy(
            skeleton["optionalPermissions"])

    if not isinstance(floored.get("license"), str) or floored["license"] not in ALLOWED_LICENSES:
        floored["license"] = LICENSE_ID
    if not isinstance(floored.get("name"), str) or not floored["name"].strip():
        floored["name"] = skeleton["name"]
    if not isinstance(floored.get("version"), str) or not floored["version"].strip():
        floored["version"] = skeleton["version"]
    if not isinstance(floored.get("engines"), dict):
        floored["engines"] = copy.deepcopy(skeleton["engines"])
    # Activation events are the manager's update choice, decided by the
    # composer: a suggestion may not add, drop, or retime one.
    floored["activationEvents"] = list(skeleton["activationEvents"])

    contributes = floored.get("contributes")
    if not isinstance(contributes, dict):
        floored["contributes"] = copy.deepcopy(skeleton["contributes"])
    else:
        widgets = contributes.get("widgets")
        if isinstance(widgets, list):
            fileless = "config" in floored
            kept: list = []
            for widget in widgets:
                if not (isinstance(widget, dict)
                        and isinstance(widget.get("dataSource"), dict)
                        and widget["dataSource"].get("type") in VOCABULARY):
                    continue
                if fileless:
                    # The config kind and a watched file cannot coexist:
                    # the floor strips the file the suggestion named.
                    widget["dataSource"].pop("file", None)
                kept.append(widget)
            contributes["widgets"] = kept
    return floored


class WizardCompiler:
    """English in, validated Class D draft out. The endpoint is a
    copywriter with no authority over permissions, data sources or
    identity; the validator is the only judge of the result."""

    def __init__(self, llm: Callable[[str], str] | None) -> None:
        """Hold the prompt-to-text callable; None keeps every step offline."""
        self.llm = llm

    # -- questions and autofill -------------------------------------------

    def questions_for(self, description: str, answers: dict | None = None) -> list[dict]:
        """The questions still open for this description and these answers.

        The path is fixed and its options come from the vocabulary tables, so
        the list is never invented: the endpoint's only job is to preselect
        the choices, which is what ``autofill`` does. A question whose path
        has one legal answer is skipped rather than asked.
        """
        return questions_for_answers(answers or {})

    def autofill(self, description: str) -> dict:
        """Preselect the fields from the description; empty when unusable.

        The reply may only name plain-language labels from the vocabulary.
        Anything else is dropped, and the field it would have filled is left
        open for the manager. With no endpoint, this returns nothing at all,
        which is how the caller knows not to claim any fill happened.
        """
        return self._autofill_reply(description)[0]

    def autofill_with_reasons(self, description: str) -> tuple[dict, dict]:
        """The same fill, plus one short reason per field for the fill screen."""
        return self._autofill_reply(description)

    def _autofill_reply(self, description: str) -> tuple[dict, dict]:
        """One endpoint round trip, parsed and checked against the vocabulary."""
        if self.llm is None:
            return {}, {}
        try:
            reply = self.llm(AUTOFILL_PROMPT.format(
                description=description, sources=", ".join(vocab.SOURCE_LABELS),
                followups=_autofill_followups()))
            data = _load_json_reply(reply)
        except Exception:
            return {}, {}
        if not isinstance(data, dict):
            return {}, {}
        checked = _checked_autofill(data)
        return checked, checked_reasons(data, checked)

    # -- building ---------------------------------------------------------

    def build(self, session: WizardSession, answers: dict) -> dict:
        """Compile, validate, repair, and either return a validated draft
        ({"manifest", "ui_schema", "attempts"}) or escalate. Every
        validator attempt is counted in session.attempts; a passing draft
        is also stored on the session. State transitions stay with the
        caller: this engine refuses, it does not run the conversation."""
        answers = dict(answers or {})
        escalate = _feature_request(session.description, answers)

        label = _unbuildable_reason(session.description)
        if label:
            raise WizardError(
                "wizard:unbuildable",
                f"this tile cannot be built from what the desk can read: it needs {label}",
                422,
                escalate(
                    f"the ask needs {label}, which the plugin vocabulary "
                    f"({', '.join(VOCABULARY)}) cannot express"
                ),
            )

        choice = resolve_choice(answers)
        if choice is None:
            raise WizardError(
                "wizard:unanswered",
                "the choices are not complete yet, so there is nothing to build",
                400,
                escalate("the wizard was asked to build before its choices were complete"),
            )

        style = self._consult_style(session.description, answers) or {}
        skeleton, ui_schema = self._compose(description=session.description,
                                            answers=answers, choice=choice, style=style)
        manifest = skeleton

        failures: tuple = ()
        for attempt in range(1, MAX_REPAIRS + 1):
            session.attempts = attempt
            verdict = self._validate(manifest, ui_schema)
            if verdict.ok:
                draft = {"manifest": manifest, "ui_schema": ui_schema, "attempts": attempt}
                session.draft = copy.deepcopy(draft)
                return draft
            failures = verdict.failures
            if self.llm is None:
                # No endpoint: there is nothing to repair with, so one
                # honest attempt is all the budget buys.
                break
            suggestion = self._repair(manifest, failures)
            if isinstance(suggestion, dict):
                manifest = _sanitize_manifest(suggestion, skeleton)

        codes = ", ".join(sorted({failure.code for failure in failures})) or "unknown"
        raise WizardError(
            "wizard:repair-cap",
            f"the draft still fails validation after {session.attempts} "
            f"attempt(s): {codes}",
            409,
            escalate(
                f"after {session.attempts} repair attempt(s) the draft still failed "
                f"validation ({codes}); the ask needs changes outside the wizard's reach"
            ),
        )

    # -- steps -------------------------------------------------------------

    def _consult_style(self, description: str, answers: dict) -> dict | None:
        """One endpoint round trip for the tile's name and one-line blurb.

        The endpoint writes copy and nothing else: it cannot set
        buildability, a source, a permission, or an activation event. Any
        failure returns None, which means the deterministic copy decides.
        """
        if self.llm is None:
            return None
        try:
            reply = self.llm(
                STYLE_PROMPT.format(
                    description=description,
                    answers=json.dumps(answers, ensure_ascii=False),
                )
            )
            data = _load_json_reply(reply)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        style: dict = {}
        if isinstance(data.get("title"), str) and data["title"].strip():
            style["title"] = data["title"].strip()
        if isinstance(data.get("description"), str) and data["description"].strip():
            style["description"] = data["description"].strip()
        return style

    def _compose(self, *, description: str, answers: dict, choice: Choice,
                 style: dict) -> tuple[dict, dict]:
        """The Class D draft for one answered choice: one widget, one element.

        Permissions follow the source and nothing else. A workbook ask composes
        the config-backed shape the bundled tracker uses (T2): no fabricated
        glob, no watched file, and the file is picked per instance in setup. A
        web ask composes the file-less shape the registry's network plugin
        uses, with the URL and its one host as an optional permission the
        consent flow shows. Every file source keeps the watched-glob shape.
        """
        slug = safe_slug(description)
        source_type = choice.source_type
        config_backed = source_type == "excel-watch"
        network_backed = source_type == "http-get"
        data_source: dict = {"type": source_type}
        read_globs: list[str] = []

        if network_backed:
            url = choice.detail or _http_url(description, answers)
            data_source["url"] = url
            data_source["allow"] = [_http_host(url)]
        elif source_type in vocab.FILE_DETAIL:
            glob_full = WORKSPACE_PREFIX + _file_glob(description, answers, source_type)
            data_source["file"] = glob_full
            read_globs = [glob_full]
            if source_type == "json-watch":
                data_source["selector"] = DEFAULT_JSON_SELECTOR

        manifest = {
            "schemaVersion": 1,
            "id": f"wizard-{slug}",
            "name": _human_copy(description, style)[0],
            "version": PLUGIN_VERSION,
            "publisher": PUBLISHER,
            "class": "declarative",
            "engines": {"dashboardHost": DASHBOARD_ENGINE},
            "license": LICENSE_ID,
            "permissions": {
                "filesystem": {"read": read_globs, "write": [PLUGIN_DATA_GLOB]},
                "network": {"allow": []},
                "llm": {"allow": False},
                "shell": SHELL_NONE,
            },
            "activationEvents": _activation_events(slug, choice),
            "contributes": {
                "widgets": [
                    {
                        "id": slug,
                        "size": WIDGET_SIZE,
                        "dataSource": data_source,
                        "render": {"type": "ui-schema", "file": WIDGET_RENDER_FILE},
                    }
                ]
            },
        }
        if config_backed:
            manifest["config"] = {"kinds": ["workbook"]}
        if network_backed:
            manifest["optionalPermissions"] = {
                "network": {
                    "allow": data_source["allow"],
                    "userPrompt": (
                        f"Allow this tile to read {data_source['url']} "
                        "on its schedule?"),
                },
            }

        title, blurb = _human_copy(description, style)
        element = vocab.element_for(source_type, choice.show, choice.look)
        elements = [element] if element else []
        if blurb:
            elements.insert(0, {"type": "text", "text": blurb})
        ui_schema = {"type": "card", "title": title, "elements": elements}
        return manifest, ui_schema

    def _repair(self, manifest: dict, failures: tuple) -> dict | None:
        """Feed the failure codes and messages back to the endpoint for a
        corrected manifest; None on any failure, which leaves the draft
        unchanged for the next attempt."""
        failure_lines = "\n".join(f"- {failure.code}: {failure.message}" for failure in failures)
        try:
            reply = self.llm(
                REPAIR_PROMPT.format(
                    failures=failure_lines,
                    manifest=json.dumps(manifest, indent=2, ensure_ascii=False),
                    vocabulary=", ".join(VOCABULARY),
                )
            )
            data = _load_json_reply(reply)
        except Exception:
            return None
        if isinstance(data, dict) and isinstance(data.get("manifest"), dict):
            return data["manifest"]
        return data if isinstance(data, dict) else None

    def _validate(self, manifest: dict, ui_schema: dict) -> Verdict:
        """Write the draft to a throwaway directory and run the shared
        validator: the same gate every plugin passes, no exceptions for
        wizard output."""
        with tempfile.TemporaryDirectory(prefix="agentdesk-wizard-") as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (root / WIDGET_RENDER_FILE).write_text(
                json.dumps(ui_schema, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return validate_plugin(root)
