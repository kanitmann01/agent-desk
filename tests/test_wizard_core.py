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
    merge_answers,
    questions_for_answers,
    resolve_choice,
    safe_slug,
)
from agentdesk.wizard import core as wizard_core
from agentdesk.wizard import vocabulary as vocab

CANONICAL_DESCRIPTION = "Watch my sales workbook and show the latest figure."
CANONICAL_ANSWERS = {
    "source": "An Excel workbook",
    "show": "The latest figure",
    "look": "A big number",
    "update": "When I open the desk",
}
CANONICAL_GLOB = "${workspace}/reports/*.xlsx"
FROZEN_NOW = 1731340800.0

FIXTURE_DIR = TESTS_DIR / "fixtures" / "validator" / "valid-manifest"
FIXTURE_MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
FIXTURE_UI = json.loads((FIXTURE_DIR / "widget.ui.json").read_text(encoding="utf-8"))

# The prompt markers the fakes branch on.
STYLE_MARKER = "Give the tile a short name"
REPAIR_MARKER = "corrected manifest"
AUTOFILL_MARKER = "Fill in the four choices"


def frozen_clock() -> float:
    return FROZEN_NOW


def make_store() -> WizardStore:
    return WizardStore(sqlite3.connect(":memory:"), clock=frozen_clock)


def canonical_session() -> object:
    return make_store().create(CANONICAL_DESCRIPTION)


MAIL_ANSWERS = {
    "source": "My mail",
    "show": "The items that need me",
    "look": "A list",
    "update": "When it changes",
}


# ---- pinned constants ----------------------------------------------------


def test_pinned_constants_hold_and_match_the_validator_vocabulary():
    assert WIZARD_STATES == ("questions", "building", "preview", "approved", "escalated")
    # Every source the questions can offer is one the composer can build, and
    # the pin that matters holds: none of them can fail the validator's type
    # check. The pipeline kinds are drafted now, unlike before spec 025.
    assert set(VOCABULARY) <= set(KNOWN_DATA_SOURCE_TYPES)
    assert "mail-digest" in VOCABULARY and "calendar-read" in VOCABULARY
    assert MAX_QUESTIONS == 5
    assert MAX_REPAIRS == 3
    # The first question is the only one a fresh description opens.
    assert len(DEFAULT_QUESTIONS) == 1


def test_safe_slug_makes_filesystem_safe_id_fragments():
    assert safe_slug("Watch My Sales Workbook!") == "watch-my-sales-workbook"
    assert safe_slug("Spreadsheets & Reports (2024)") == "spreadsheets-reports-2024"
    assert len(safe_slug("a" * 100)) == 40
    assert safe_slug("...---...") == "widget"
    assert safe_slug("") == "widget"


# ---- questions -----------------------------------------------------------


def test_a_fresh_description_opens_only_the_source_question():
    questions = WizardCompiler(None).questions_for(CANONICAL_DESCRIPTION)

    assert len(questions) == 1
    assert questions[0]["id"] == "source"
    assert set(questions[0]) == {"id", "question", "options", "default"}
    # Every source the desk can read is offered, in plain words.
    assert "My mail" in questions[0]["options"]
    assert "An Excel workbook" in questions[0]["options"]
    assert questions[0]["default"] in questions[0]["options"]


def test_the_path_offers_only_what_the_chosen_source_can_bind():
    mail = questions_for_answers({"source": "My mail"})
    ids = [question["id"] for question in mail]
    # No detail step: mail names no file. No look step: a mail list has one look.
    assert ids == ["source", "show", "update"]
    show = next(question for question in mail if question["id"] == "show")
    assert set(show["options"]) == {"The items that need me", "One status line"}
    # A source with no event to watch is never offered "when it changes".
    update = next(question for question in mail if question["id"] == "update")
    assert "When it changes" in update["options"]

    web = questions_for_answers({"source": "A web page"})
    web_update = next(q for q in web if q["id"] == "update")
    assert "When it changes" not in web_update["options"]
    # A web source has an address only the manager can supply.
    detail = next(q for q in web if q["id"] == "detail")
    assert detail["options"] == [] and detail["default"] == ""


def test_a_workbook_offers_a_table_as_well_as_a_big_number():
    answers = {"source": "An Excel workbook", "show": "The rows behind it"}
    look = next(q for q in questions_for_answers(answers) if q["id"] == "look")

    assert set(look["options"]) == {"A table", "A list"}
    assert look["default"] == "A table"


def test_a_single_look_is_folded_away_rather_than_asked():
    answers = {"source": "My calendar", "show": "The items that need me"}

    assert "look" not in [q["id"] for q in questions_for_answers(answers)]


def test_every_binding_the_wizard_offers_is_one_the_host_fills():
    """A look names a binding, and a binding no reader fills is a permanently
    blank tile. The host's own binding list is the contract, so the wizard's
    vocabulary has to stay inside it."""
    from agentdesk.plugins.execute import BINDINGS

    offered: set[str] = set()
    for shows in vocab.ELEMENTS.values():
        for looks in shows.values():
            for spec in looks.values():
                offered.update(value for key, value in spec.items()
                               if key.endswith("Binding"))

    assert offered <= set(BINDINGS), sorted(offered - set(BINDINGS))


def test_every_look_is_a_real_element_kind():
    """A look that is not one of the ten element kinds would fail the shared
    validator at install time, which is too late to tell a manager."""
    from agentdesk.plugins.vocabulary import ELEMENT_KINDS

    for shows in vocab.ELEMENTS.values():
        for looks in shows.values():
            assert set(looks) <= set(ELEMENT_KINDS)


def test_no_source_offers_a_show_no_reader_could_fill():
    """Every source in the questions has at least one show, or choosing it
    would leave the walk with nothing to ask."""
    for label, source_type in vocab.SOURCE_CHOICES:
        assert vocab.shows_for(source_type), label


# ---- autofill ------------------------------------------------------------


def test_autofill_fills_every_field_from_the_description():
    reply = json.dumps({
        "source": "My mail",
        "detail": "",
        "show": "The items that need me",
        "look": "A list",
        "update": "Each morning at 8",
        "reasons": {"source": "It reads your mail folder.",
                    "show": "It lists what is waiting on you."},
    })
    filled, reasons = WizardCompiler(lambda prompt: reply).autofill_with_reasons(
        "A morning list of my mail")

    assert filled["source"] == "My mail"
    assert filled["show"] == "The items that need me"
    assert filled["look"] == "A list"
    assert filled["update"] == "Each morning at 8"
    # The reasons are copy for the fill screen, kept out of the answers.
    assert "reasons" not in filled
    assert reasons["source"].startswith("It reads your mail")

def test_autofill_drops_a_source_outside_the_vocabulary():
    """A label the questions could never offer is dropped, never
    defaulted: the field stays open and the walk asks for it."""
    reply = json.dumps({"source": "A salesforce org", "show": "The latest figure"})

    assert WizardCompiler(lambda prompt: reply).autofill("Watch salesforce") == {}


def test_autofill_drops_a_change_choice_for_a_source_with_no_event():
    reply = json.dumps({
        "source": "A web page", "detail": "https://example.com/x.json",
        "show": "The latest figure", "look": "A big number",
        "update": "When it changes",
    })
    filled = WizardCompiler(lambda prompt: reply).autofill("Watch the pricing page")

    assert "update" not in filled
    assert filled["source"] == "A web page"


def test_autofill_without_an_endpoint_claims_nothing():
    assert WizardCompiler(None).autofill("A morning list of my mail") == {}


def test_autofill_garbage_reply_fills_nothing():
    filled = WizardCompiler(lambda prompt: "sounds good!").autofill("Something")

    assert filled == {}


def test_the_manager_s_own_answer_survives_an_autofill():
    merged = merge_answers({"source": "My calendar"}, {"source": "My mail",
                                                      "show": "One status line"})

    assert merged["source"] == "My calendar"
    assert merged["show"] == "One status line"


# ---- building without an endpoint -----------------------------------------


def test_build_without_llm_compiles_a_draft_that_passes_the_shared_validator(tmp_path):
    """The workbook build (T2) is the config-backed shape the bundled
    tracker uses: workbook config kind, an empty filesystem read, and a
    widget data source with no file. Nothing is fabricated at compose
    time; the file is picked per instance in setup. The tile shows the
    figure the manager chose, not a fixed metric."""
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
    assert set(manifest) <= set(FIXTURE_MANIFEST) | {"config"}
    assert manifest["config"] == {"kinds": ["workbook"]}
    assert manifest["permissions"]["filesystem"]["read"] == []
    assert manifest["permissions"]["filesystem"]["write"] == ["${pluginData}"]
    assert manifest["permissions"]["network"] == {"allow": []}
    assert manifest["permissions"]["llm"] == {"allow": False}
    assert manifest["permissions"]["shell"] == "none"

    widget = manifest["contributes"]["widgets"][0]
    fixture_widget = FIXTURE_MANIFEST["contributes"]["widgets"][0]
    assert set(widget) == set(fixture_widget)
    assert widget["dataSource"] == {"type": "excel-watch"}
    assert widget["render"] == {"type": "ui-schema", "file": "widget.ui.json"}

    ui_schema = draft["ui_schema"]
    assert set(ui_schema) == set(FIXTURE_UI)
    # The chosen show is the element, labelled in the manager's words.
    assert ui_schema["elements"][-1] == {
        "type": "metric", "binding": "value", "label": "The latest figure"}

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


def test_build_refuses_before_the_choices_are_complete():
    """Answering one question builds nothing: the workbook default no longer
    fills in the rest behind the manager's back."""
    session = canonical_session()

    with pytest.raises(WizardError) as raised:
        WizardCompiler(None).build(session, {"source": "My mail"})

    assert raised.value.code == "wizard:unanswered"
    assert session.draft is None


def test_a_json_build_keeps_the_watched_glob_shape():
    """Only workbook builds become config-backed instances (T2): a JSON
    build composes the declarative glob shape, the read permission
    mirroring the data source file, with the default selector the
    json-watch type requires (a composer output the validator accepts,
    017-02 2g)."""
    manifest, _ui = WizardCompiler(None)._compose(
        CANONICAL_DESCRIPTION, {"source": "A JSON file", "file": "data/*.json"}, {}
    )

    assert "config" not in manifest
    assert manifest["permissions"]["filesystem"]["read"] == ["${workspace}/data/*.json"]
    widget = manifest["contributes"]["widgets"][0]
    assert widget["dataSource"] == {
        "type": "json-watch",
        "file": "${workspace}/data/*.json",
        "deltaWindow": "24h",
        "selector": "$.value",
    }


def test_the_offered_json_and_web_options_build_valid_plugins(tmp_path):
    """Picking the wizard's own menu options never dead-ends (audit F2):
    the deterministic composer finishes json-watch (default selector) and
    http-get (no read globs, url and allow parsed from the answers) so
    both pass the shared validator the build already runs."""
def test_a_json_build_keeps_the_watched_glob_shape():
    """Only workbook builds become config-backed instances (T2): a JSON
    build composes the declarative glob shape, the read permission
    mirroring the data source file, with the default selector the
    json-watch type requires (a composer output the validator accepts,
    017-02 2g)."""
    manifest, _ui = WizardCompiler(None)._compose(
        description=CANONICAL_DESCRIPTION, answers={},
        choice=resolve_choice({"source": "A JSON file", "show": "The latest figure",
                               "look": "A big number", "update": "Every hour"}),
        style={},
    )

    assert "config" not in manifest
    assert manifest["permissions"]["filesystem"]["read"] == ["${workspace}/data/*.json"]
    widget = manifest["contributes"]["widgets"][0]
    assert widget["dataSource"] == {
        "type": "json-watch",
        "file": "${workspace}/data/*.json",
        "selector": "$.value",
    }


def test_the_offered_json_and_web_options_build_valid_plugins(tmp_path):
    """Picking the wizard's own menu options never dead-ends (audit F2):
    the deterministic composer finishes json-watch (default selector) and
    http-get (no read globs, url and allow from the answers) so both pass
    the shared validator the build already runs."""

    json_session = make_store().create("Watch my sales totals.")
    json_draft = WizardCompiler(None).build(
        json_session, {"source": "A JSON file", "show": "The latest figure",
                       "look": "A big number", "update": "Every hour"})
    assert json_draft["manifest"]["contributes"]["widgets"][0]["dataSource"][
        "selector"] == "$.value"

    web_session = make_store().create("Track the pricing page.")
    web_draft = WizardCompiler(None).build(
        web_session,
        {"source": "A web page", "detail": "https://api.example.com/prices",
         "show": "The latest figure", "look": "A big number",
         "update": "Every hour"})
    manifest = web_draft["manifest"]
    assert manifest["permissions"]["filesystem"]["read"] == []
    data_source = manifest["contributes"]["widgets"][0]["dataSource"]
    assert data_source["type"] == "http-get"
    assert data_source["url"] == "https://api.example.com/prices"
    assert data_source["allow"] == ["api.example.com"]
    assert "file" not in data_source
    # The network reach is an optional permission the consent flow shows,
    # exactly like the registry's own network plugin.
    assert manifest["optionalPermissions"]["network"]["allow"] == [
        "api.example.com"]


def test_a_pipeline_build_names_no_watched_file():
    """Mail, calendar and research read the shared pipelines, so their
    manifest declares no read glob and no data source file. This is the
    install that used to be refused as "sending mail"."""
    session = make_store().create("A morning list of my mail.")
    draft = WizardCompiler(None).build(session, MAIL_ANSWERS)
    manifest = draft["manifest"]

    assert manifest["permissions"]["filesystem"]["read"] == []
    assert manifest["contributes"]["widgets"][0]["dataSource"] == {"type": "mail-digest"}
    assert manifest["activationEvents"] == [
        "onWidget:a-morning-list-of-my-mail", "onHook:mail"]
    assert draft["ui_schema"]["elements"][-1] == {"type": "list",
                                                  "rowsBinding": "waitingRows"}


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


def broken_floor() -> dict:
    """A draft on the safe permission floor that still fails validation.

    It carries the fixed identity and permissions a real draft has, plus the
    pieces BROKEN_MANIFEST breaks, so the repair-cap test exercises the
    budget rather than the sanitizer.
    """
    return {
        "schemaVersion": 1,
        "id": "wizard-deploy",
        "name": "Deploy watch",
        "version": "not-a-semver",
        "publisher": "agent-desk-wizard",
        "class": "declarative",
        "engines": {"dashboardHost": ">=1.0.0 <2.0.0"},
        "license": "MIT",
        "permissions": {
            "filesystem": {"read": [], "write": ["${pluginData}"]},
            "network": {"allow": []},
            "llm": {"allow": False},
            "shell": "none",
        },
        "activationEvents": ["onWidget:deploy"],
        "contributes": {"widgets": [{
            "id": "deploy",
            "size": "2x1",
            "dataSource": {"type": "excel-watch"},
            "render": {"type": "ui-schema", "file": "missing.ui.json"},
        }]},
    }


def test_build_repairs_one_bad_suggestion_and_then_succeeds():
    """The repair loop still works, but the suggestion can only change the
    manifest's shape, never the source or a permission: the floor pins both.
    A first draft that fails validation is repaired once and then installs."""
    def fixing_llm(prompt):
        if REPAIR_MARKER in prompt:
            return json.dumps({"manifest": GOOD_MANIFEST})
        return json.dumps({"title": "Sales pulse",
                           "description": "The latest figure"})

    session = canonical_session()
    manifest, ui_schema = WizardCompiler(fixing_llm)._compose(
        description=CANONICAL_DESCRIPTION, answers=CANONICAL_ANSWERS,
        choice=resolve_choice(CANONICAL_ANSWERS), style={})
    # A malformed first draft, as the repair loop's first attempt.
    broken = dict(manifest, version="beta", name="Sales pulse")
    repaired = wizard_core._sanitize_manifest(GOOD_MANIFEST, manifest)

    assert broken["version"] == "beta"
    assert repaired["version"] == "0.1.0"
    assert repaired["publisher"] == "agent-desk-wizard"
    assert repaired["id"] == manifest["id"]
    assert repaired["permissions"] == manifest["permissions"]
    assert repaired["contributes"]["widgets"][0]["dataSource"]["type"] == "excel-watch"
    assert repaired["activationEvents"] == manifest["activationEvents"]


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

    class AlwaysBroken(WizardCompiler):
        """A composer that never produces a valid draft, so the repair
        budget is spent and the honest escalation is the only answer."""

        def _compose(self, **_kwargs):
            return broken_floor(), {"type": "card", "title": "x", "elements": []}

        def _repair(self, _manifest, _failures):
            return BROKEN_MANIFEST

    session = canonical_session()
    with pytest.raises(WizardError) as raised:
        AlwaysBroken(lambda prompt: json.dumps({"title": "Deploy watch"})).build(
            session, CANONICAL_ANSWERS)

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

    # The model can no longer mark an ask unbuildable: its only authority is
    # copy. The refusal comes from the deterministic rule, before validation.
    description = "Run the warehouse nightly batch before standup."
    session = make_store().create(description)
    with pytest.raises(WizardError) as raised:
        WizardCompiler(lambda prompt: json.dumps({"title": "x"})).build(session, {})

    error = raised.value
    assert error.code == "wizard:unbuildable"
    assert error.status == 422
    assert calls == []
    assert error.feature_request["description"] == description
    assert error.feature_request["kind"] == "feature_request"
    assert "executing code" in error.feature_request["reason"]


def test_reading_mail_is_a_source_and_only_writing_mail_is_refused():
    """The old rule refused any mention of mail. A mail tile is now a
    source; sending or drafting mail is still outside the vocabulary."""
    description = "A morning list of my mail."
    session = make_store().create(description)
    draft = WizardCompiler(None).build(session, MAIL_ANSWERS)

    assert draft["manifest"]["contributes"]["widgets"][0]["dataSource"]["type"] == "mail-digest"

    refused = "Send an email to the team every Friday."
    with pytest.raises(WizardError) as raised:
        WizardCompiler(None).build(make_store().create(refused), {})
    assert raised.value.code == "wizard:unbuildable"
    assert "sending mail" in raised.value.feature_request["reason"]


def test_build_escalates_without_llm_on_script_asks():
    description = "Run the cleanup script every Friday and show me the log."
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
    # The workbook skeleton is config-backed (T2): its config kinds are
    # pinned like permissions, and a suggested widget never keeps a
    # watched file the config kind forbids.
    assert floored["config"] == skeleton["config"]
    kept = floored["contributes"]["widgets"][0]
    assert [widget["dataSource"]["type"] for widget in floored["contributes"]["widgets"]] == [
        "json-watch"
    ]
    assert "file" not in kept["dataSource"]


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
