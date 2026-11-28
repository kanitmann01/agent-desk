"""The tracker setup over the real HTTP server: open, suggest, confirm."""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from server_harness import Booted
from tests import excel_fixtures

_PICKER_UNAVAILABLE = (
    "The file dialog could not open on this computer. "
    "Type the file's path, or upload the file instead."
)


@contextmanager
def _booted_excel_report(tmp_path, pick=None, extra_plugins=()):
    """The excel-report desk on a real port, with a picker injected.

    pick is the picker's body: it receives the fixture workbook and
    answers what the dialog would answer - a path, None, or a ConfigError.
    The default opens the fixture workbook. Yields (server, book).
    """
    from nexuusbot.plugins.runtime import PluginRuntime

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "q4.xlsx"
    book.write_bytes(excel_fixtures.make_xlsx([
        ["Region", "Booked"],
        ["East", 10],
        ["West", 5],
    ]))
    root = Path(__file__).resolve().parents[1]
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=workspace,
    )
    runtime.install(root / "registry" / "plugins" / "excel-report", source="dir")
    for name in extra_plugins:
        runtime.install(root / "tests" / "fixtures" / "plugins" / name, source="dir")
    server = Booted(
        plugins=runtime,
        pick_workbook=(lambda: str(book)) if pick is None else (lambda: pick(book)),
        llm=lambda _prompt: '{"labelColumn": "Region", "valueColumn": "Booked", "aggregate": "sum"}',
        llm_endpoint="http://llm.test/v1",
    )
    try:
        yield server, book
    finally:
        server.close()


@pytest.fixture
def booted(tmp_path):
    with _booted_excel_report(tmp_path) as pair:
        yield pair


def _refuse_to_open(_book):
    from nexuusbot.plugins.config import ConfigError

    raise ConfigError("config:picker-unavailable", _PICKER_UNAVAILABLE)


@pytest.fixture
def booted_unavailable(tmp_path):
    with _booted_excel_report(tmp_path, pick=_refuse_to_open) as pair:
        yield pair


@pytest.fixture
def booted_cancelled(tmp_path):
    with _booted_excel_report(tmp_path, pick=lambda _book: None) as pair:
        yield pair


def test_open_suggest_and_confirm_lands_on_the_tracker(booted):
    server, _book = booted
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/pick",
        {"name": "Workbook tracker"}, auth)
    assert status == 200, body
    opened = json.loads(body)
    assert opened["preview"]["headers"] == ["Region", "Booked"]

    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/suggest", {}, auth)
    assert status == 200, body
    suggested = json.loads(body)
    assert "up to 5 rows" in suggested["disclosure"]
    assert suggested["proposal"]["valueColumn"] == "Booked"
    assert "q4.xlsx" not in json.dumps(suggested)

    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/confirm",
        {"tracking": suggested["proposal"], "suggested": True}, auth)
    assert status == 200, body

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["title"] == "Workbook tracker" or item["id"].startswith("excel-report"))
    assert card["freshness"] == "fresh"
    metrics = {element["label"]: element["value"] for element in card["payload"]["elements"] if element["kind"] == "metric"}
    assert metrics["Value"] == "15"


def test_a_picker_that_cannot_open_answers_503(booted_unavailable):
    server, _book = booted_unavailable
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/pick",
        {"name": "Workbook tracker"}, auth)
    assert status == 503, body
    assert json.loads(body) == {
        "error": "config:picker-unavailable",
        "message": _PICKER_UNAVAILABLE,
    }

    status, _headers, body = server.request(
        "GET", "/api/plugins/excel-report/instances", auth)
    assert status == 200
    listed = json.loads(body)["instances"]
    main = next(item for item in listed if item["instanceId"] == "main")
    assert main["source"] is None


def test_a_cancelled_dialog_still_answers_400_config_cancelled(booted_cancelled):
    server, _book = booted_cancelled
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/pick",
        {"name": "Workbook tracker"}, auth)
    assert status == 400, body
    assert json.loads(body) == {
        "error": "config:cancelled",
        "message": "No file was opened.",
    }


def test_a_typed_path_stages_and_previews(booted):
    server, book = booted
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/stage",
        {"path": str(book)}, auth)
    assert status == 200, body
    staged = json.loads(body)
    assert staged["step"] == "columns"
    assert staged["preview"]["headers"] == ["Region", "Booked"]
    assert staged["instance"]["source"]["path"] == str(book.resolve())


def test_an_uploaded_file_is_copied_accepted_and_previewed(booted, tmp_path):
    server, book = booted
    auth = server.exchange()
    raw = book.read_bytes()
    status, _headers, body = server.request(
        "POST",
        "/api/plugins/excel-report/instances/main/upload/q4.xlsx",
        {**auth, "Content-Type": "application/octet-stream",
         "Content-Length": str(len(raw))},
        raw)
    assert status == 200, body
    opened = json.loads(body)
    assert opened["step"] == "columns"
    assert opened["preview"]["headers"] == ["Region", "Booked"]
    stored = Path(opened["instance"]["source"]["path"]).resolve()
    assert stored.read_bytes() == raw
    assert stored.is_relative_to((tmp_path / "data").resolve())
    assert not stored.is_relative_to((tmp_path / "workspace").resolve())

    # Accepted on the user's behalf: confirm needs no /outside call.
    status, _headers, body = server.post_json(
        "/api/plugins/excel-report/instances/main/confirm",
        {"tracking": {"labelColumn": "Region", "valueColumn": "Booked",
                      "aggregate": "sum"}}, auth)
    assert status == 200, body


def test_an_upload_over_the_cap_is_413_and_the_server_survives(booted):
    server, _book = booted
    auth = server.exchange()
    raw = b"x" * (5 * 1024 * 1024)
    status, _headers, body = server.request(
        "POST",
        "/api/plugins/excel-report/instances/main/upload/q4.xlsx",
        {**auth, "Content-Type": "application/octet-stream",
         "Content-Length": str(len(raw))},
        raw)
    assert status == 413, body
    assert json.loads(body) == {
        "error": "config:too-large",
        "message": "The file is larger than 4 MB. Save a smaller copy, "
                   "or type the file's path instead.",
    }

    status, _headers, _body = server.request("GET", "/api/dashboard", auth)
    assert status == 200


def test_an_upload_of_another_kind_is_refused(booted):
    server, _book = booted
    auth = server.exchange()
    raw = b"region,booked\nEast,10\n"
    status, _headers, body = server.request(
        "POST",
        "/api/plugins/excel-report/instances/main/upload/notes.txt",
        {**auth, "Content-Type": "application/octet-stream",
         "Content-Length": str(len(raw))},
        raw)
    assert status == 400, body
    assert json.loads(body) == {
        "error": "config:unsupported",
        "message": "Open an .xlsx, .xlsm, .csv, or .json file.",
    }


def test_an_upload_name_cannot_escape_the_instance_folder(booted, tmp_path):
    server, book = booted
    auth = server.exchange()
    raw = book.read_bytes()
    status, _headers, body = server.request(
        "POST",
        "/api/plugins/excel-report/instances/main/upload/..%2Fescape.xlsx",
        {**auth, "Content-Type": "application/octet-stream",
         "Content-Length": str(len(raw))},
        raw)
    assert status == 400, body
    assert json.loads(body) == {
        "error": "config:unsafe-name",
        "message": "That file name cannot be stored. Rename the file and try again.",
    }
    assert list(tmp_path.rglob("escape.xlsx")) == []


def test_an_empty_upload_is_refused(booted):
    server, _book = booted
    auth = server.exchange()
    status, _headers, body = server.request(
        "POST",
        "/api/plugins/excel-report/instances/main/upload/q4.xlsx",
        {**auth, "Content-Type": "application/octet-stream", "Content-Length": "0"},
        b"")
    assert status == 400, body
    assert json.loads(body) == {
        "error": "config:empty-upload",
        "message": "The upload carried no bytes. Choose the file again.",
    }


@pytest.fixture
def booted_pack(tmp_path):
    """The tracker desk with a second config-backed plugin that is not
    the historical tracker: the qbr-pack fixture under tests/fixtures."""
    with _booted_excel_report(tmp_path, extra_plugins=("qbr-pack",)) as pair:
        yield pair


def test_a_config_backed_plugin_that_is_not_the_tracker_shows_its_setup_card(booted_pack):
    """The dashboard expands the fixture plugin into its own wireframe
    card with a Set up entry, exactly like the tracker's."""
    server, _book = booted_pack
    auth = server.exchange()
    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack")
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["pluginId"] == "qbr-pack"
    assert card["payload"]["setup"]["step"] == "source"
    assert card["payload"]["elements"] == []


def test_the_whole_chain_serves_the_fixture_plugin_over_http(booted_pack):
    """Create, pick, stage, preview, confirm over real HTTP for a plugin
    that is not the tracker, then the dashboard reads exactly the
    confirmed file, and the seventh instance hits the cap."""
    server, _book = booted_pack
    auth = server.exchange()

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances", {"name": "Pipeline"}, auth)
    assert status == 200, body
    status, _headers, body = server.request(
        "GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["step"] == "source"

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/pick",
        {"name": "Pipeline"}, auth)
    assert status == 200, body
    opened = json.loads(body)
    assert opened["preview"]["headers"] == ["Region", "Booked"]

    status, _headers, body = server.request(
        "GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["payload"]["setup"]["step"] == "columns"

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/confirm",
        {"tracking": {"labelColumn": "Region", "valueColumn": "Booked",
                      "aggregate": "sum"}}, auth)
    assert status == 200, body

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "fresh"
    metrics = {element["label"]: element["value"]
               for element in card["payload"]["elements"]
               if element["kind"] == "metric"}
    assert metrics["Value"] == "15"

    for index in range(1, 6):
        status, _headers, _body = server.post_json(
            "/api/plugins/qbr-pack/instances", {"name": f"Extra {index}"}, auth)
        assert status == 200, _body
    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances", {"name": "One too many"}, auth)
    assert status == 400, body
    assert json.loads(body)["error"] == "config:cap"


def test_confirm_carries_the_selected_rows_and_the_card_reads_only_them(booted_pack):
    """T4: the confirm body's tracking.rows (ordered zero-based data rows)
    reach the stored config over the real endpoint, and the dashboard card
    then reads exactly the selected rows' values."""
    server, _book = booted_pack
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/pick", {"name": "Pipeline"}, auth)
    assert status == 200, body

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/confirm",
        {"tracking": {"labelColumn": "Region", "valueColumn": "Booked",
                      "aggregate": "sum", "rows": [0]}}, auth)
    assert status == 200, body
    saved = json.loads(body)
    assert saved["instance"]["tracking"]["rows"] == [0]

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "fresh"
    metrics = {element["label"]: element["value"]
               for element in card["payload"]["elements"]
               if element["kind"] == "metric"}
    assert metrics["Value"] == "10"


def test_a_stale_row_selection_is_refused_over_http(booted_pack):
    """T4: rows past the staged file's data rows keep the existing
    stale-config refusal shape over HTTP: 400 with the mismatched-file
    code, and the instance stays unconfirmed."""
    server, _book = booted_pack
    auth = server.exchange()
    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/pick", {"name": "Pipeline"}, auth)
    assert status == 200, body

    status, _headers, body = server.post_json(
        "/api/plugins/qbr-pack/instances/pipeline/confirm",
        {"tracking": {"labelColumn": "Region", "valueColumn": "Booked",
                      "aggregate": "sum", "rows": [9]}}, auth)
    assert status == 400, body
    assert json.loads(body)["error"] == "config:not-granted"

    status, _headers, body = server.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == "qbr-pack~pipeline")
    assert card["freshness"] == "setup"
