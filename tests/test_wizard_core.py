"""The wizard engine (ticket #11), tested through its pinned contract.

Plain English in, at most five multiple-choice questions back, a Class D
draft out that passes the shared validator. The hostile-endpoint tests
prove the two honest escalations and that no draft the validator ever
sees carries shell, network, or out-of-vocabulary permissions.
"""

import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agentdesk.validator.core import validate_plugin as real_validate_plugin
from agentdesk.validator.lint import KNOWN_DATA_SOURCE_TYPES
from agentdesk.wizard import (
    DEFAULT_QUESTIONS,
    MAX_QUESTIONS,
    MAX_REPAIRS,
    VOCABULARY,
    WIZARD_STATES,
    WizardCompiler,
    WizardError,
    WizardStore,
    safe_slug,
)
from agentdesk.wizard import core as wizard_core

CANONICAL_DESCRIPTION = "Watch my sales workbook and show the 24-hour change."
CANONICAL_ANSWERS = {
    "source": "An Excel workbook",
    "file": "reports/*.xlsx",
    "display": "The 24-hour change",
}
CANONICAL_GLOB = "${workspace}/reports/*.xlsx"
FROZEN_NOW = 1731340800.0

FIXTURE_DIR = TESTS_DIR / "fixtures" / "validator" / "valid-manifest"
FIXTURE_MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
FIXTURE_UI = json.loads((FIXTURE_DIR / "widget.ui.json").read_text(encoding="utf-8"))

# The style prompt asks for buildability, the repair prompt for a
# corrected manifest: the fakes branch on those phrases.
STYLE_MARKER = "buildable"
REPAIR_MARKER = "corrected manifest"


def frozen_clock() -> float:
    return FROZEN_NOW


def make_store() -> WizardStore:
    return WizardStore(sqlite3.connect(":memory:"), clock=frozen_clock)


def canonical_session() -> object:
    return make_store().create(CANONICAL_DESCRIPTION)


# ---- pinned constants ----------------------------------------------------


def test_pinned_constants_hold_and_match_the_validator_vocabulary():
    assert WIZARD_STATES == ("questions", "building", "preview", "approved", "escalated")
    # The wizard drafts a subset: it composes a watched file glob for
    # every kind it knows, so the glob-less pipeline kinds the validator
    # accepts since #64 (mail-digest, research-brief) stay
    # registry-authored until the wizard learns to draft them. The pin
    # that matters: nothing the wizard drafts can fail the validator's
    # type check.
    assert set(VOCABULARY) <= set(KNOWN_DATA_SOURCE_TYPES)
    assert MAX_QUESTIONS == 5
    assert MAX_REPAIRS == 3
    assert len(DEFAULT_QUESTIONS) == 3


def test_safe_slug_makes_filesystem_safe_id_fragments():
    assert safe_slug("Watch My Sales Workbook!") == "watch-my-sales-workbook"
    assert safe_slug("Spreadsheets & Reports (2024)") == "spreadsheets-reports-2024"
    assert len(safe_slug("a" * 100)) == 40
    assert safe_slug("...---...") == "widget"
    assert safe_slug("") == "widget"


# ---- questions -----------------------------------------------------------


def test_questions_without_llm_are_three_choice_questions_with_defaults():
    questions = WizardCompiler(None).questions_for(CANONICAL_DESCRIPTION)

    assert len(questions) == 3
    for question in questions:
        assert set(question) == {"id", "question", "options", "default"}
        assert len(question["options"]) >= 2
        assert question["default"] in question["options"]


def test_questions_with_llm_parse_fenced_json_and_repair_bad_defaults():
    fenced = """Here you go:

```json
[
  {"id": "file", "question": "Which workbook should it watch?",
   "options": ["reports/*.xlsx", "data/*.json"], "default": "reports/*.xlsx"},
  {"id": "cadence", "question": "How often should it refresh?",
   "options": ["Every 15 minutes", "Hourly", "Daily"], "default": "Hourly"},
  {"id": "display", "question": "What should it show?",
   "options": ["Latest value", "Daily summary"], "default": "mystery"}
]
```

Hope that helps."""
    questions = WizardCompiler(lambda prompt: fenced).questions_for(CANONICAL_DESCRIPTION)

    assert [question["id"] for question in questions] == ["file", "cadence", "display"]
    assert questions[0]["default"] == "reports/*.xlsx"
    assert questions[1]["default"] == "Hourly"
    # A default outside the options falls back to the first option.
    assert questions[2]["default"] == "Latest value"


def test_questions_garbage_reply_falls_back_to_defaults():
    questions = WizardCompiler(
        lambda prompt: "A widget sounds nice, maybe with a chart?"
    ).questions_for(CANONICAL_DESCRIPTION)

    assert questions == copy.deepcopy(list(DEFAULT_QUESTIONS))


def test_questions_are_capped_at_five():
    seven = [
        {"id": f"q{i}", "question": f"Question {i}?", "options": ["a", "b"], "default": "a"}
        for i in range(7)
    ]
    questions = WizardCompiler(lambda prompt: json.dumps(seven)).questions_for(
        CANONICAL_DESCRIPTION
    )

    assert len(questions) == MAX_QUESTIONS
    assert [question["id"] for question in questions] == [f"q{i}" for i in range(5)]


# ---- building without an endpoint -----------------------------------------


def test_build_without_llm_compiles_a_draft_that_passes_the_shared_validator(tmp_path):
    session = canonical_session()
    draft = WizardCompiler(None).build(session, CANONICAL_ANSWERS)

    manifest = draft["manifest"]
    assert draft["attempts"] == 1 and session.attempts == 1
    assert session.draft == draft
    assert manifest["schemaVersion"] == 1
    assert manifest["class"] == FIXTURE_MANIFEST["class"]
    assert manifest["version"] == "0.1.0"
    assert manifest["publisher"] == "agent-desk-wizard"
    assert manifest["id"].startswith("wizard-")
    assert set(manifest) <= set(FIXTURE_MANIFEST)
    assert manifest["permissions"]["filesystem"]["read"] == [CANONICAL_GLOB]
    assert manifest["permissions"]["network"] == {"allow": []}
    assert manifest["permissions"]["llm"] == {"allow": False}
    assert manifest["permissions"]["shell"] == "none"

    widget = manifest["contributes"]["widgets"][0]
    fixture_widget = FIXTURE_MANIFEST["contributes"]["widgets"][0]
    assert set(widget) == set(fixture_widget)
    assert widget["dataSource"]["type"] == "excel-watch"
    assert widget["dataSource"]["file"] == CANONICAL_GLOB
    assert widget["dataSource"]["deltaWindow"] == "24h"
    assert widget["render"] == {"type": "ui-schema", "file": "widget.ui.json"}

    ui_schema = draft["ui_schema"]
    assert set(ui_schema) == set(FIXTURE_UI)
    assert ui_schema["elements"][1]["binding"] == "delta24h"

    # The same bytes, written the fixture way, pass the shared validator.
    plugin_dir = tmp_path / "draft"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (plugin_dir / "widget.ui.json").write_text(
        json.dumps(ui_schema, indent=2), encoding="utf-8"
    )
    verdict = real_validate_plugin(plugin_dir)
    assert verdict.ok, verdict.as_dict()


# ---- building with a hostile endpoint --------------------------------------


BROKEN_MANIFEST = {
    "schemaVersion": 1,
    "id": "wizard-deploy",
    "name": "Deploy watch",
    "version": "not-a-semver",
    "publisher": "someone-else",
    "class": "declarative",
    "engines": {},
    "license": "MIT",
    "permissions": {"shell": "powershell", "network": {"allow": ["https://*"]}},
    "activationEvents": ["onWidget:deploy"],
    "contributes": {
        "widgets": [
            {
                "id": "deploy",
                "size": "2x1",
                "dataSource": {"type": "excel-watch", "file": CANONICAL_GLOB},
                "render": {"type": "ui-schema", "file": "missing.ui.json"},
            }
        ]
    },
}

GOOD_MANIFEST = {
    "schemaVersion": 1,
    "id": "wizard-sales-watch",
    "name": "Sales pulse",
    "version": "0.1.0",
    "publisher": "someone-else",
    "class": "declarative",
    "license": "MIT",
    "activationEvents": ["onWidget:sales-watch", "onSchedule:*/15 * * * *"],
    "contributes": {
        "widgets": [
            {
                "id": "sales-watch",
                "size": "2x1",
                "dataSource": {
                    "type": "excel-watch",
                    "file": CANONICAL_GLOB,
                    "deltaWindow": "24h",
                },
                "render": {"type": "ui-schema", "file": "widget.ui.json"},
            }
        ]
    },
}


def test_build_repairs_one_bad_suggestion_and_then_succeeds():
    def fixing_llm(prompt):
        if REPAIR_MARKER in prompt:
            return json.dumps({"manifest": GOOD_MANIFEST})
        return json.dumps(
            {
                "buildable": True,
                "title": "Sales pulse",
                "description": "The 24-hour sales delta",
                "manifest": {
                    "schemaVersion": 1,
                    "id": "wizard-x",
                    "name": "Sales pulse",
                    "version": "beta",
                    "publisher": "someone-else",
                    "class": "declarative",
                    "license": "MIT",
                    "permissions": {"shell": "bash"},
                    "contributes": {"widgets": []},
                },
            }
        )

    session = canonical_session()
    draft = WizardCompiler(fixing_llm).build(session, CANONICAL_ANSWERS)

    assert draft["attempts"] == 2 and session.attempts == 2
    assert draft["manifest"]["version"] == "0.1.0"
    assert draft["manifest"]["name"] == "Sales pulse"
    assert draft["manifest"]["permissions"]["shell"] == "none"


def test_build_counts_attempts_and_escalates_at_the_repair_cap(monkeypatch):
    validated = []

    def counting_validate(path):
        path = Path(path)
        validated.append(path)
        written = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        # Every draft the validator sees stays on the safe floor, even
        # while the endpoint keeps trying to grant itself a shell.
        assert written["permissions"]["shell"] == "none"
        assert written["permissions"]["network"]["allow"] == []
        return real_validate_plugin(path)

    monkeypatch.setattr(wizard_core, "validate_plugin", counting_validate)

    def hostile_llm(prompt):
        if REPAIR_MARKER in prompt:
            return json.dumps({"manifest": BROKEN_MANIFEST})
        return json.dumps(
            {
                "buildable": True,
                "title": "Deploy watch",
                "description": "Watches deploys",
                "manifest": BROKEN_MANIFEST,
            }
        )

    session = canonical_session()
    with pytest.raises(WizardError) as raised:
        WizardCompiler(hostile_llm).build(session, CANONICAL_ANSWERS)

    error = raised.value
    assert error.code == "wizard:repair-cap"
    assert error.status == 409
    assert session.attempts == MAX_REPAIRS == 3
    assert len(validated) == 3
    payload = error.feature_request
    assert payload["description"] == CANONICAL_DESCRIPTION
    assert payload["answers"] == CANONICAL_ANSWERS
    assert payload["kind"] == "feature_request"
    assert payload["reason"]


def test_build_escalates_unbuildable_before_any_validation(monkeypatch):
    calls = []

    def counting_validate(path):
        calls.append(path)
        return real_validate_plugin(path)

    monkeypatch.setattr(wizard_core, "validate_plugin", counting_validate)

    def refusing_llm(prompt):
        assert STYLE_MARKER in prompt
        return json.dumps(
            {
                "buildable": False,
                "reason": "the ask needs a nightly batch trigger, not file watching",
            }
        )

    description = "Every morning, kick off the warehouse nightly batch before standup."
    session = make_store().create(description)
    with pytest.raises(WizardError) as raised:
        WizardCompiler(refusing_llm).build(session, {})

    error = raised.value
    assert error.code == "wizard:unbuildable"
    assert error.status == 422
    assert calls == []
    assert error.feature_request["description"] == description
    assert error.feature_request["kind"] == "feature_request"
    assert "batch trigger" in error.feature_request["reason"]


def test_build_escalates_without_llm_on_mail_and_script_asks():
    description = "Email me a summary every Friday and run the cleanup script after."
    session = make_store().create(description)

    with pytest.raises(WizardError) as raised:
        WizardCompiler(None).build(session, {})

    error = raised.value
    assert error.code == "wizard:unbuildable"
    assert error.status == 422
    assert error.feature_request["description"] == description
    assert error.feature_request["reason"]


def test_build_uses_llm_copy_but_never_its_permissions():
    smuggled = json.dumps(
        {
            "buildable": True,
            "title": "Sales pulse",
            "description": "The 24-hour sales delta at a glance",
            "permissions": {"shell": "powershell"},
            "contributes": {"widgets": []},
        }
    )
    session = canonical_session()
    draft = WizardCompiler(lambda prompt: smuggled).build(session, CANONICAL_ANSWERS)

    assert draft["attempts"] == 1
    assert draft["manifest"]["name"] == "Sales pulse"
    assert draft["ui_schema"]["title"] == "Sales pulse"
    assert draft["manifest"]["permissions"]["shell"] == "none"
    assert draft["manifest"]["permissions"]["network"] == {"allow": []}
    assert draft["manifest"]["contributes"]["widgets"][0]["dataSource"]["type"] == "excel-watch"


def test_sanitize_manifest_strips_permissions_and_foreign_structure():
    skeleton = WizardCompiler(None).build(canonical_session(), CANONICAL_ANSWERS)["manifest"]
    suggestion = {
        "schemaVersion": 3,
        "id": "../../etc",
        "publisher": "not-the-wizard",
        "class": "imperative",
        "version": "9.9.9",
        "name": "Hijacked",
        "license": "Proprietary",
        "permissions": {
            "shell": "powershell",
            "network": {"allow": ["https://*"]},
            "filesystem": {"read": ["C:/**"], "write": ["C:/**"]},
            "llm": {"allow": True, "maxTokensPerDay": 1000000000},
        },
        "optionalPermissions": {"network": {"allow": ["https://*"], "userPrompt": "why"}},
        "mysteryKey": {"deep": True},
        "engines": {"dashboardHost": ">=2.0.0"},
        "activationEvents": "not-a-list",
        "contributes": {
            "widgets": [
                {
                    "dataSource": {"type": "http-post", "file": "x"},
                    "render": {"type": "ui-schema", "file": "widget.ui.json"},
                },
                "not-a-widget",
                {
                    "dataSource": {"type": "json-watch", "file": "${workspace}/data/*.json"},
                    "render": {"type": "ui-schema", "file": "widget.ui.json"},
                },
            ]
        },
    }

    floored = wizard_core._sanitize_manifest(suggestion, skeleton)

    assert floored["schemaVersion"] == 1
    assert floored["class"] == "declarative"
    assert floored["id"] == skeleton["id"]
    assert floored["publisher"] == skeleton["publisher"]
    assert floored["permissions"] == skeleton["permissions"]
    assert floored["permissions"]["shell"] == "none"
    assert floored["permissions"]["network"] == {"allow": []}
    assert "optionalPermissions" not in floored
    assert "mysteryKey" not in floored
    assert floored["license"] == "MIT"
    assert floored["name"] == "Hijacked"
    assert floored["version"] == "9.9.9"
    assert floored["engines"] == {"dashboardHost": ">=2.0.0"}
    assert floored["activationEvents"] == list(skeleton["activationEvents"])
    assert [widget["dataSource"]["type"] for widget in floored["contributes"]["widgets"]] == [
        "json-watch"
    ]


# ---- the session store ------------------------------------------------------


def test_store_round_trips_a_session_verbatim():
    store = make_store()
    session = store.create(CANONICAL_DESCRIPTION)

    assert session.state == "questions"
    assert session.description == CANONICAL_DESCRIPTION
    assert session.created_ts == FROZEN_NOW
    assert session.attempts == 0
    assert session.draft is None

    session.answers = {"source": "An Excel workbook"}
    session.attempts = 2
    session.draft = {"manifest": {"id": "wizard-x"}, "ui_schema": {}, "attempts": 2}
    store.save(session)

    loaded = store.get(session.id)
    assert loaded == session
    payload = loaded.to_json()
    assert payload["description"] == CANONICAL_DESCRIPTION
    assert payload["state"] == "questions"
    assert payload["answers"] == {"source": "An Excel workbook"}
    assert payload["draft"]["manifest"] == {"id": "wizard-x"}
    assert payload["featureRequest"] is None
    assert payload["createdTs"] == FROZEN_NOW


def test_store_unknown_id_raises_a_404_wizard_error():
    with pytest.raises(WizardError) as raised:
        make_store().get("wiz-missing")
    assert raised.value.code == "wizard:unknown"
    assert raised.value.status == 404


def test_store_rejects_an_empty_description():
    with pytest.raises(ValueError):
        make_store().create("")
    with pytest.raises(ValueError):
        make_store().create("   ")
    with pytest.raises(ValueError):
        make_store().create(None)
