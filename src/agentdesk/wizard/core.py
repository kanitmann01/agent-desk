"""The English-to-plugin wizard engine (ticket #11).

A manager describes what she wants in plain English; this module turns
that into a Class D declarative plugin draft. Three guardrails keep the
engine honest:

- Vocabulary confinement. A draft can only watch the four data sources
  in VOCABULARY, and its permissions are fixed by the one chosen file
  glob: no shell, no network, no llm. The endpoint (when configured) may
  shape the human-readable copy and suggest structure inside the
  vocabulary; the sanitizer strips everything else before the validator
  ever sees it.
- One gate. Drafts are judged by the same ``validate_plugin`` every
  other plugin passes: the wizard never vouches for its own output.
- Bounded effort, honest escalation. At most MAX_REPAIRS validator
  attempts; when the ask exceeds the vocabulary, or the repair budget
  runs out, the wizard raises WizardError carrying a feature_request
  payload instead of shipping a broken draft or silently narrowing the
  ask.

The llm is a prompt-to-text callable (``agentdesk.llm.chat`` bound to
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

from agentdesk.validator.core import validate_plugin
from agentdesk.validator.model import Verdict
from agentdesk.validator.schema import ALLOWED_LICENSES, REQUIRED_KEY_TYPES

# The pinned public contract.
WIZARD_STATES = ("questions", "building", "preview", "approved", "escalated")
VOCABULARY = ("excel-watch", "json-watch", "http-get", "calendar-read")
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

DEFAULT_SCHEDULE = "*/15 * * * *"
DEFAULT_SOURCE_TYPE = "excel-watch"

# Answers are option labels, not ids, so matching is by phrase.
SOURCE_ANSWER_ALIASES = (
    ("excel-watch", ("excel", "workbook", "xlsx", "spreadsheet", "sheet")),
    ("json-watch", ("json",)),
    ("calendar-read", ("calendar", "appointment", "meeting")),
    ("http-get", ("http", "web", "url", "endpoint", "page")),
)
SOURCE_TEXT_HINTS = (
    ("excel-watch", ("excel", "workbook", "xlsx", "spreadsheet", "worksheet")),
    ("json-watch", ("json",)),
    ("calendar-read", ("calendar", "appointment", "ics")),
    ("http-get", ("http", "url", "endpoint", "website", "web page", "api")),
)
DEFAULT_FILE_GLOBS = {
    "excel-watch": "reports/*.xlsx",
    "json-watch": "data/*.json",
    "http-get": "cache/*.json",
    "calendar-read": "calendar/*.ics",
}
CADENCE_CRON = (
    (("every 5 minutes", "5 minutes"), "*/5 * * * *"),
    (("every 15 minutes", "15 minutes", "quarter hour"), "*/15 * * * *"),
    (("hourly", "every hour"), "0 * * * *"),
    (("daily", "every day", "each morning", "every morning"), "0 8 * * *"),
)
DAY_WINDOW_PATTERN = re.compile(r"\b24[ -]?h(our)?s?\b", re.IGNORECASE)
GLOB_PATTERN = re.compile(
    r"[A-Za-z0-9_.\-*/\\]*[A-Za-z0-9_]\.(?:xlsx|xlsm|csv|json|ics)\b"
)

# Asks the declarative vocabulary cannot honor. Each rule carries the
# plain-language label the escalation uses, so the refusal names what the
# manager asked for instead of talking in failure codes.
UNBUILDABLE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(e-?mail|mail)s?\b", re.IGNORECASE), "sending mail"),
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

# The deterministic question set: stable, offline, and the fallback for
# every endpoint failure, so the wizard never blocks on the llm.
DEFAULT_QUESTIONS = (
    {
        "id": "source",
        "question": "What should the widget watch?",
        "options": ["An Excel workbook", "A JSON file", "A web page (HTTP GET)", "My calendar"],
        "default": "An Excel workbook",
    },
    {
        "id": "file",
        "question": "Which files should it read?",
        "options": ["reports/*.xlsx", "data/*.json", "cache/*.json", "calendar/*.ics"],
        "default": "reports/*.xlsx",
    },
    {
        "id": "display",
        "question": "What should the widget show?",
        "options": ["The 24-hour change", "The latest value", "A short summary line"],
        "default": "The latest value",
    },
)

QUESTION_PROMPT = """A manager wants a dashboard widget and described the idea like this:
"{description}"

Ask her at most {max} multiple-choice questions so the wizard can build the
widget. The only data source types that exist are: {vocabulary}. Ask about the
workbook or file to watch, the refresh cadence, what the widget should show,
and a threshold if one matters. Never ask for typed technical input: every
question offers ready options and one default.

Reply with JSON only, an array of objects:
[{{"id": "...", "question": "...", "options": ["...", "..."], "default": "..."}}]"""

STYLE_PROMPT = """A manager wants a dashboard widget and described the idea like this:
"{description}"

Her chosen answers:
{answers}

Draft a declarative plugin manifest for her. The only data source types that
exist are: {vocabulary}. Hard rules you cannot change: schemaVersion is 1,
class is "declarative", version is a semver string like 0.1.0, permissions are
fixed (filesystem read only of the chosen "${{workspace}}/..." glob, network
allow [], llm allow false, shell "none"), contributes.widgets[0] carries a
dataSource and a render of type "ui-schema" pointing at "widget.ui.json", and
activationEvents lists an onWidget and an onSchedule entry.

If the ask cannot be met by watching files (for example sending mail, running
scripts, executing code, or opening apps), set "buildable" to false and explain
in plain language.

Reply with JSON only, one object:
{{"buildable": true, "reason": "", "title": "...", "description": "...",
"manifest": {{}}}}"""

REPAIR_PROMPT = """The plugin validator rejected this draft manifest.

Validator failures:
{failures}

Draft manifest:
{manifest}

The only data source types that exist are: {vocabulary}. Permissions can never
change: filesystem read of the chosen glob, network allow [], llm allow false,
shell "none". Return the same manifest with the failures fixed.

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

    def __post_init__(self) -> None:
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
        self.conn = conn
        self.clock = clock
        conn.executescript(STORE_SCHEMA)
        conn.commit()

    def create(self, description: str) -> WizardSession:
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
        row = self.conn.execute(
            "SELECT document FROM wizard_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise WizardError("wizard:unknown", f"no wizard session {session_id}", 404)
        return _session_from_document(json.loads(row[0]))

    def save(self, session: WizardSession) -> None:
        self._write(session)

    def _write(self, session: WizardSession) -> None:
        document = json.dumps(
            {
                "id": session.id,
                "state": session.state,
                "description": session.description,
                "questions": session.questions,
                "answers": session.answers,
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


def _parse_questions(reply: object) -> list[dict]:
    """Validate endpoint questions into the pinned shape, dropping every
    one that would need typed input, and capping at MAX_QUESTIONS."""
    data = _load_json_reply(reply)
    if isinstance(data, dict):
        data = data.get("questions")
    if not isinstance(data, list):
        return []
    questions: list[dict] = []
    seen_ids: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        qid, text = item.get("id"), item.get("question")
        options = item.get("options")
        if not (isinstance(qid, str) and qid.strip()):
            continue
        if not (isinstance(text, str) and text.strip()):
            continue
        if not isinstance(options, list):
            continue
        options = [option for option in options if isinstance(option, str) and option.strip()]
        if len(options) < 2:
            continue
        default = item.get("default")
        if not (isinstance(default, str) and default in options):
            default = options[0]
        if qid in seen_ids:
            continue
        seen_ids.add(qid)
        questions.append(
            {"id": qid, "question": text.strip(), "options": options, "default": default}
        )
        if len(questions) == MAX_QUESTIONS:
            break
    return questions


# ---- escalation payload ------------------------------------------------


def _feature_request(description: str, answers: dict) -> Callable[[str], dict]:
    """Build the escalation payloads for one build run: the full original
    ask travels with every refusal, verbatim."""

    def make(reason: str) -> dict:
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


def _source_type(description: str, answers: dict) -> str:
    """One of VOCABULARY: the chosen answer first, then the manager's own
    words, then the workbook default."""
    named = str(answers.get("source") or "").lower()
    if named:
        for source_type, aliases in SOURCE_ANSWER_ALIASES:
            if any(alias in named for alias in aliases):
                return source_type
    haystack = description.lower()
    for source_type, hints in SOURCE_TEXT_HINTS:
        if any(hint in haystack for hint in hints):
            return source_type
    return DEFAULT_SOURCE_TYPE


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
    match = GLOB_PATTERN.search(description)
    return match.group(0) if match else ""


def _file_glob(description: str, answers: dict, source_type: str) -> str:
    for candidate in (answers.get("file"), _glob_in_text(description)):
        glob = _clean_glob(candidate)
        if glob:
            return glob
    return DEFAULT_FILE_GLOBS[source_type]


def _cadence(answers: dict) -> str:
    joined = " ".join(str(value).lower() for value in answers.values() if isinstance(value, str))
    for phrases, cron in CADENCE_CRON:
        if any(phrase in joined for phrase in phrases):
            return cron
    return DEFAULT_SCHEDULE


def _mentions_day_window(description: str, answers: dict) -> bool:
    haystack = description + " " + " ".join(
        str(value) for value in answers.values() if isinstance(value, str)
    )
    return bool(DAY_WINDOW_PATTERN.search(haystack))


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
    """
    floored: dict = {}
    if isinstance(raw, dict):
        for key in _CARRIED_KEYS:
            if key in raw:
                floored[key] = copy.deepcopy(raw[key])

    # Identity and permissions are never negotiable.
    floored["schemaVersion"] = 1
    floored["class"] = "declarative"
    floored["publisher"] = PUBLISHER
    floored["id"] = skeleton["id"]
    floored["permissions"] = copy.deepcopy(skeleton["permissions"])

    if not isinstance(floored.get("license"), str) or floored["license"] not in ALLOWED_LICENSES:
        floored["license"] = LICENSE_ID
    if not isinstance(floored.get("name"), str) or not floored["name"].strip():
        floored["name"] = skeleton["name"]
    if not isinstance(floored.get("version"), str) or not floored["version"].strip():
        floored["version"] = skeleton["version"]
    if not isinstance(floored.get("engines"), dict):
        floored["engines"] = copy.deepcopy(skeleton["engines"])
    if not isinstance(floored.get("activationEvents"), list):
        floored["activationEvents"] = list(skeleton["activationEvents"])

    contributes = floored.get("contributes")
    if not isinstance(contributes, dict):
        floored["contributes"] = copy.deepcopy(skeleton["contributes"])
    else:
        widgets = contributes.get("widgets")
        if isinstance(widgets, list):
            contributes["widgets"] = [
                widget
                for widget in widgets
                if isinstance(widget, dict)
                and isinstance(widget.get("dataSource"), dict)
                and widget["dataSource"].get("type") in VOCABULARY
            ]
    return floored


class WizardCompiler:
    """English in, validated Class D draft out. The endpoint is a
    copywriter with no authority over permissions, data sources or
    identity; the validator is the only judge of the result."""

    def __init__(self, llm: Callable[[str], str] | None) -> None:
        self.llm = llm

    # -- questions --------------------------------------------------------

    def questions_for(self, description: str) -> list[dict]:
        """Up to MAX_QUESTIONS multiple-choice questions, each with a
        default. The endpoint's suggestion is used only when it parses,
        holds the pinned shape, and needs no typed input; anything else
        falls back to DEFAULT_QUESTIONS."""
        if self.llm is not None:
            try:
                reply = self.llm(
                    QUESTION_PROMPT.format(
                        description=description,
                        max=MAX_QUESTIONS,
                        vocabulary=", ".join(VOCABULARY),
                    )
                )
                questions = _parse_questions(reply)
            except Exception:
                questions = []
            if questions:
                return questions
        return copy.deepcopy(list(DEFAULT_QUESTIONS))

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
                f"this widget cannot be built from watched files alone: it needs {label}",
                422,
                escalate(
                    f"the ask needs {label}, which the declarative widget "
                    f"vocabulary ({', '.join(VOCABULARY)}) cannot express"
                ),
            )

        style = self._consult_style(session.description, answers) or {}
        if style.get("buildable") is False:
            reason = style.get("reason") or (
                "the assistant says the ask is outside the declarative widget vocabulary"
            )
            raise WizardError(
                "wizard:unbuildable",
                f"this widget cannot be built from watched files alone: {reason}",
                422,
                escalate(reason),
            )

        skeleton, ui_schema = self._compose(session.description, answers, style)
        manifest = skeleton
        if isinstance(style.get("manifest"), dict):
            manifest = _sanitize_manifest(style["manifest"], skeleton)

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
        """One endpoint round trip: buildability, human copy, and an
        optional manifest suggestion. Any failure (endpoint down, reply
        not JSON, reply not an object) returns None, which means the
        deterministic path decides."""
        if self.llm is None:
            return None
        try:
            reply = self.llm(
                STYLE_PROMPT.format(
                    description=description,
                    answers=json.dumps(answers, ensure_ascii=False),
                    vocabulary=", ".join(VOCABULARY),
                )
            )
            data = _load_json_reply(reply)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        style: dict = {}
        if isinstance(data.get("buildable"), bool):
            style["buildable"] = data["buildable"]
        if isinstance(data.get("reason"), str) and data["reason"].strip():
            style["reason"] = data["reason"].strip()
        if isinstance(data.get("title"), str) and data["title"].strip():
            style["title"] = data["title"].strip()
        if isinstance(data.get("description"), str) and data["description"].strip():
            style["description"] = data["description"].strip()
        if isinstance(data.get("manifest"), dict):
            style["manifest"] = data["manifest"]
        return style

    def _compose(self, description: str, answers: dict, style: dict) -> tuple[dict, dict]:
        """The deterministic Class D draft: one widget, one watched glob,
        permissions that cannot widen, shaped like the repo's fixtures."""
        slug = safe_slug(description)
        source_type = _source_type(description, answers)
        glob_full = WORKSPACE_PREFIX + _file_glob(description, answers, source_type)
        cadence = _cadence(answers)
        window = (
            "24h"
            if source_type in ("excel-watch", "json-watch")
            and _mentions_day_window(description, answers)
            else ""
        )

        data_source: dict = {"type": source_type, "file": glob_full}
        if window:
            data_source["deltaWindow"] = window

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
                "filesystem": {"read": [glob_full], "write": [PLUGIN_DATA_GLOB]},
                "network": {"allow": []},
                "llm": {"allow": False},
                "shell": SHELL_NONE,
            },
            "activationEvents": [f"onWidget:{slug}", f"onSchedule:{cadence}"],
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

        title, blurb = _human_copy(description, style)
        if not blurb:
            blurb = "Change over the last 24 hours" if window else "Latest value"
        ui_schema = {
            "type": "card",
            "title": title,
            "elements": [
                {"type": "text", "text": blurb},
                {"type": "metric", "binding": "delta24h" if window else "value"},
            ],
        }
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
