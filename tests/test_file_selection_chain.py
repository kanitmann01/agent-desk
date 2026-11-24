"""The whole chain over the real server (T6): wizard walk to live card.

The five tickets before this one each stop at their own seam. This test
drives the real walk end to end at the harness seam, exactly as a no-JS
browser would: start, describe, answer, approve as a form post, the
approved screen, then the instance chain against the plugin the wizard
installed (create, pick with the fake picker, preview, confirm with a
row selection), and finally the dashboard card contract for the
confirmed instance. Every step must answer as designed: pages and
redirects for form posts, JSON envelopes for API calls, raw JSON
nowhere in the walk.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from tests import excel_fixtures

CANONICAL = "Watch this workbook and show me the 24-hour change"
NOW = datetime(2026, 11, 17, 9, 0, 0).astimezone()

# The whole wizard path in one post: a workbook, its latest figure as a big
# number, read when the desk is opened. A tile read live is what this chain
# is about; the scheduled and change modes are covered by their own suite.
WORKBOOK_ANSWERS = {
    "source": "An Excel workbook",
    "show": "The latest figure",
    "look": "A big number",
    "update": "When I open the desk",
}

# The tracked selection, zero-based data rows: Atlas ERP and Care plans.
TRACKED_ROWS = [0, 2]
TRACKED_SUM = "186500"  # 164000 + 22500, the fixture's Revenue column


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start.timestamp()

    def __call__(self) -> float:
        return self.now


def make_runtime(tmp_path):
    from agentdesk.plugins.runtime import PluginRuntime

    return PluginRuntime(
        plugins_dir=tmp_path / "plugins",
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        now="2026-11-17T09:00:00",
    )


def post_form(booted, path, fields, headers):
    """A browser-shaped POST: form-urlencoded fields, no JavaScript."""
    data = urlencode(fields).encode("utf-8")
    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    merged.update(headers)
    return booted.request("POST", path, merged, data)


@pytest.fixture()
def walk(tmp_path, monkeypatch):
    """The real walk's environment: the deterministic wizard path (no
    endpoint anywhere), a plugin runtime rooted in the boot's temp
    folder, and a fake picker that opens the fixture workbook."""
    for name in ("AGENTDESK_LLM_BASE", "AGENTDESK_LLM_KEY", "AGENTDESK_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    from agentdesk.wizard.core import WizardStore

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    book = workspace / "chain.xlsx"
    book.write_bytes(excel_fixtures.base_workbook())

    clock = FakeClock(NOW)
    booted = server_harness.Booted(
        plugins=make_runtime(tmp_path),
        wizard_store=WizardStore(sqlite3.connect(":memory:", check_same_thread=False), clock),
        inbox_store=server_harness._inert_inbox(),
        pick_workbook=lambda: str(book),
    )
    try:
        booted.workbook = book
        yield booted
    finally:
        booted.close()


def _content_type(headers):
    return headers.get("Content-Type", "")


def test_the_whole_chain_wizard_to_live_card(walk):
    """The chain: (a) start page, (b) describe -> 303, (c) questions,
    (d) answer -> 303, (e) preview, (f) approve form -> 303, (g) the
    approved screen with the setup call to action, (h) the instance
    chain to a fresh card reading only the selected rows, (i) every
    step answered in its designed shape."""
    auth = walk.exchange()
    plugins_runtime = walk.server.plugins

    # (a) The dashboard button: an empty start asks for the words, on a
    # page, not a JSON document.
    status, headers, body = post_form(walk, "/wizard/start", {}, auth)
    assert status == 200
    assert "text/html" in _content_type(headers)
    start_page = body.decode("utf-8")
    assert 'action="/wizard/new/answer"' in start_page

    # (b) The words make the session: the describe form answers 303.
    status, headers, body = post_form(walk, "/wizard/new/answer",
                                     {"description": CANONICAL}, auth)
    assert status == 303
    assert b'{' not in body  # a redirect, never a JSON document
    location = headers["Location"]
    assert location.startswith("/wizard/wiz-")
    sid = location.rsplit("/", 1)[-1]

    # (c) The session page renders the standard questions.
    status, headers, body = walk.request("GET", f"/wizard/{sid}", auth)
    assert status == 200
    assert "text/html" in _content_type(headers)
    questions_page = body.decode("utf-8")
    assert "What should this tile watch?" in questions_page
    assert f'action="/wizard/{sid}/answer"' in questions_page

    # (d) The whole path answered at once: a workbook, its first figure, a big
    # number, and a tile read when the desk is opened. The post answers 303
    # back to the session page, now in preview.
    status, headers, body = walk.post_json(
        f"/wizard/{sid}/answer", {"answers": WORKBOOK_ANSWERS}, auth)
    assert status == 303
    assert headers["Location"] == f"/wizard/{sid}"
    session = walk.server.wizard_store.get(sid)
    assert session.state == "preview"
    manifest = session.draft["manifest"]
    assert manifest["config"] == {"kinds": ["workbook"]}
    assert manifest["permissions"]["filesystem"]["read"] == []  # no fabricated glob
    assert manifest["activationEvents"] == [
        f"onWidget:{manifest['contributes']['widgets'][0]['id']}"]

    # (e) The preview screen carries the approve form and the summary
    # that names the setup handoff instead of a glob.
    status, headers, body = walk.request("GET", f"/wizard/{sid}", auth)
    assert status == 200
    assert "text/html" in _content_type(headers)
    preview_page = body.decode("utf-8")
    assert f'action="/wizard/{sid}/approve"' in preview_page
    assert "a workbook you pick in setup" in preview_page
    assert "reports/*.xlsx" not in preview_page

    # (f) Add widget: the form post answers 303 to the session page.
    status, headers, body = post_form(walk, f"/wizard/{sid}/approve", {}, auth)
    assert status == 303
    assert headers["Location"] == f"/wizard/{sid}"
    assert b"{" not in body  # no response document parks the browser

    # (g) The approved screen: what was installed, the pilot line, the
    # summary, and the setup call to action. No raw JSON anywhere.
    status, headers, body = walk.request("GET", f"/wizard/{sid}", auth)
    assert status == 200
    assert "text/html" in _content_type(headers)
    approved_page = body.decode("utf-8")
    records = plugins_runtime.list_records()
    assert len(records) == 1
    plugin_id = records[0]["id"]
    assert plugin_id.startswith("wizard-")
    assert records[0]["state"] == "enabled"
    assert plugin_id in approved_page
    assert records[0]["active_version"] in approved_page
    assert "Added" in approved_page
    assert "in pilot mode" in approved_page
    assert "a workbook you pick in setup" in approved_page
    assert "Set up its data" in approved_page
    assert f'href="/marketplace/plugin/{plugin_id}/manage"' in approved_page
    assert '"status":' not in approved_page  # no raw JSON on the page
    assert '"install"' not in approved_page

    # (g, continued) The CTA is followable: the detail payload the manage
    # view renders from resolves the wizard-installed plugin id. A wizard
    # install is in no catalog, so resolution falls back to the installed
    # record; the Discover listing itself stays catalog-only.
    status, headers, body = walk.request(
        "GET", f"/api/marketplace/plugin/{plugin_id}", auth)
    assert status == 200, body
    assert "application/json" in _content_type(headers)
    detail_payload = json.loads(body)
    assert detail_payload["plugin"]["id"] == plugin_id
    assert detail_payload["plugin"]["name"]
    assert detail_payload["installed"]["id"] == plugin_id
    assert detail_payload["installed"]["enabled"] is True

    # (h) The instance chain against the wizard-installed plugin id.
    # The manage surface's listing answers the same plugin (no
    # alias/wizard-id mismatch): config-backed, its own setup.
    status, headers, body = walk.request(
        "GET", f"/api/plugins/{plugin_id}/instances", auth)
    assert status == 200
    assert "application/json" in _content_type(headers)
    listing = json.loads(body)
    assert listing["pluginId"] == plugin_id
    assert listing["configBacked"] is True
    assert listing["aliasOf"] is None
    assert listing["setupPluginId"] == plugin_id
    assert listing["instances"] == []

    # The dashboard shows the setup card for the plugin itself.
    status, headers, body = walk.request("GET", "/api/dashboard", auth)
    assert status == 200
    assert "application/json" in _content_type(headers)
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == plugin_id)
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["pluginId"] == plugin_id
    assert card["payload"]["setup"]["step"] == "source"
    assert card["payload"]["elements"] == []

    # Create: the JSON envelope names the instance.
    status, headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances", {"name": "Pipeline"}, auth)
    assert status == 200
    assert "application/json" in _content_type(headers)
    created = json.loads(body)["instance"]
    assert created["instanceId"] == "pipeline"
    assert created["confirmedAt"] is None

    # Pick: the fake picker opens the fixture workbook server-side;
    # the preview is the real file's headers and first rows.
    status, headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances/pipeline/pick",
        {"name": "Pipeline"}, auth)
    assert status == 200
    assert "application/json" in _content_type(headers)
    opened = json.loads(body)
    assert opened["step"] == "columns"
    preview = opened["preview"]
    assert preview["headers"] == ["Product line", "Units", "Revenue"]
    assert [row[0] for row in preview["rows"]] == [
        "Atlas ERP modules", "Field services", "Care plans"]
    assert "chain.xlsx" in opened["instance"]["source"]["path"]

    # Preview: the same grid again over the GET endpoint.
    status, headers, body = walk.request(
        "GET", f"/api/plugins/{plugin_id}/instances/pipeline/preview", auth)
    assert status == 200
    assert "application/json" in _content_type(headers)
    assert json.loads(body)["preview"]["headers"] == ["Product line", "Units", "Revenue"]

    # Confirm: the row selection rides tracking.rows and sticks.
    status, headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances/pipeline/confirm",
        {"name": "Pipeline", "headerRow": 1,
         "tracking": {"labelColumn": "Product line", "valueColumn": "Revenue",
                      "aggregate": "sum", "rows": TRACKED_ROWS}}, auth)
    assert status == 200
    assert "application/json" in _content_type(headers)
    saved = json.loads(body)
    assert saved["step"] == "done"
    assert saved["instance"]["tracking"]["rows"] == TRACKED_ROWS
    assert saved["instance"]["confirmedAt"]

    # The card is fresh and reads exactly the selected rows' values:
    # 164000 + 22500, never the untouched Field services row. It draws the
    # face the manager chose (a big number), not the classic tracker face.
    status, headers, body = walk.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    card = next(item for item in cards if item["id"] == f"{plugin_id}~pipeline")
    assert card["freshness"] == "fresh"
    assert card["title"] == "Pipeline"
    assert card["payload"]["face"] == "ui-schema"
    metrics = {element["label"]: element["value"]
               for element in card["payload"]["elements"]
               if element["kind"] == "metric"}
    assert metrics["The latest figure"] == TRACKED_SUM
    # The chosen face names the workbook in its own text element, not in the
    # classic card's "Workbook" line, so the reading is still traceable.
    assert card["payload"]["tracker"]["file"] == "chain.xlsx"

    # (h, continued) The existing error gates stay intact on the same
    # walk: a stale row selection is refused with the mismatched-file
    # code and the instance stays unconfirmed.
    status, headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances", {"name": "Spare"}, auth)
    assert status == 200
    status, headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances/spare/pick", {"name": "Spare"}, auth)
    assert status == 200
    status, headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances/spare/confirm",
        {"tracking": {"labelColumn": "Product line", "valueColumn": "Revenue",
                      "aggregate": "sum", "rows": [9]}}, auth)
    assert status == 400
    assert "application/json" in _content_type(headers)
    refusal = json.loads(body)
    assert refusal["error"] == "config:not-granted"
    assert refusal["message"]
    status, _headers, body = walk.request("GET", "/api/dashboard", auth)
    cards = json.loads(body)["plugins"]["cards"]
    spare = next(item for item in cards if item["id"] == f"{plugin_id}~spare")
    assert spare["freshness"] == "setup"

    # The manage listing now shows both instances, pipeline confirmed.
    status, _headers, body = walk.request(
        "GET", f"/api/plugins/{plugin_id}/instances", auth)
    listing = json.loads(body)
    assert len(listing["instances"]) == 2
    by_id = {item["instanceId"]: item for item in listing["instances"]}
    assert by_id["pipeline"]["confirmedAt"]
    assert by_id["spare"]["confirmedAt"] is None

    # The auto-created main instance (the dashboard sheet's
    # pick-without-create path) answers under the plugin id in the
    # layout and on the dashboard, exactly like the pre-pick card: a
    # pick that never reaches confirm must not orphan the setup card.
    status, _headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances/main/pick",
        {"name": "Main"}, auth)
    assert status == 200, body
    status, _headers, body = walk.request("GET", "/api/layout", auth)
    assert status == 200
    keys = [entry["key"] for entry in json.loads(body)["cards"]]
    status, _headers, body = walk.request("GET", "/api/dashboard", auth)
    assert status == 200
    cards = json.loads(body)["plugins"]["cards"]
    family = [c for c in cards
              if c["id"] == plugin_id or c["id"].startswith(f"{plugin_id}~")]
    assert len(family) == 3  # pipeline fresh, spare setup, main setup
    assert all(c["id"] in keys for c in family), ([c["id"] for c in family], keys)
    main_card = next(c for c in family if c["instanceId"] == "main")
    assert main_card["id"] == plugin_id
    assert main_card["freshness"] == "setup"


def test_the_chain_walk_never_serves_json_to_a_form_or_html_to_an_api(walk):
    """The client-kind rule holds across the whole chain: the wizard's
    form posts answer with pages or redirects only, and the instance
    endpoints answer JSON only, even when the session has moved on."""
    auth = walk.exchange()
    status, headers, body = post_form(walk, "/wizard/new/answer",
                                     {"description": CANONICAL}, auth)
    assert status == 303
    sid = headers["Location"].rsplit("/", 1)[-1]
    walk.post_json(f"/wizard/{sid}/answer", {"answers": WORKBOOK_ANSWERS}, auth)
    # The session screen is a page even mid-walk (no JSON on GET): the
    # preview state renders the approve form, not a document.
    status, headers, body = walk.request("GET", f"/wizard/{sid}", auth)
    assert status == 200
    assert "text/html" in _content_type(headers)
    assert f'action="/wizard/{sid}/approve"' in body.decode("utf-8")

    # The approve form post never gets JSON, before or after install.
    status, headers, body = post_form(walk, f"/wizard/{sid}/approve", {}, auth)
    assert status == 303
    assert "application/json" not in _content_type(headers)
    status, headers, body = post_form(walk, f"/wizard/{sid}/approve", {}, auth)
    assert status == 303  # the refusal is the redirect back, not a document
    assert "application/json" not in _content_type(headers)
    assert len(walk.server.plugins.list_records()) == 1

    # The API stays JSON on every verb the chain uses, even for a body
    # the endpoint refuses: the envelope names the cause, no HTML page.
    plugin_id = walk.server.plugins.list_records()[0]["id"]
    status, headers, body = walk.post_json(
        f"/api/plugins/{plugin_id}/instances", {}, auth)
    assert status == 400
    assert "application/json" in _content_type(headers)
    assert json.loads(body)["error"]
    status, headers, body = walk.request(
        "GET", f"/api/plugins/{plugin_id}/instances", auth)
    assert status == 200
    assert "application/json" in _content_type(headers)
    assert "text/html" not in _content_type(headers)
