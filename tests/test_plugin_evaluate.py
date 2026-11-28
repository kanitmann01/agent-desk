"""The model reviews the user's own choice; a skip never blocks confirm."""

import json
from types import SimpleNamespace

from nexuusbot.plugins.config import InstanceStore
from nexuusbot.plugins.setup_flow import evaluate
from nexuusbot.plugins.suggest import DISCLOSURE_ROWS, build_evaluation_request, evaluate_choice


def _request(rows=None):
    return {
        "job": "Track the pipeline.",
        "sheet": "Data",
        "headers": ["Deal", "Stage", "Amount"],
        "rowCount": 3,
        "choice": {"labelColumn": "Deal", "valueColumn": "Amount", "rows": [0, 1]},
        "rows": rows or [["Acme", "Won", "1200"], ["Globex", "Lost", "800"]],
    }


def test_a_model_review_is_validated_against_the_file():
    def complete(prompt):
        assert "Deal" in prompt and "Amount" in prompt
        return json.dumps({
            "verdict": "adjust",
            "message": "Stage is the better label here.",
            "recommendation": {
                "labelColumn": "Stage", "valueColumn": "Amount",
                "rows": [0, 2], "reason": "Stage groups the amounts.",
            },
        })

    result = evaluate_choice(_request(), complete)
    assert result["verdict"] == "adjust"
    assert result["message"] == "Stage is the better label here."
    assert result["recommendation"] == {
        "labelColumn": "Stage", "valueColumn": "Amount",
        "rows": [0, 2], "reason": "Stage groups the amounts.",
    }


def test_a_recommendation_naming_columns_or_rows_the_file_lacks_is_dropped():
    def complete(_prompt):
        return json.dumps({
            "verdict": "adjust",
            "message": "Try this.",
            "recommendation": {"labelColumn": "Region", "valueColumn": "Total", "rows": [0]},
        })

    result = evaluate_choice(_request(), complete)
    assert result["recommendation"] is None
    assert result["verdict"] == "adjust"


def test_no_endpoint_is_an_unchecked_verdict_not_an_error():
    result = evaluate_choice(_request(), None)
    assert result["verdict"] == "unchecked"
    assert "no AI is saved" in result["message"]
    assert result["recommendation"] is None


def test_a_failed_call_degrades_to_unchecked():
    def complete(_prompt):
        raise RuntimeError("the endpoint answered a redirect")

    result = evaluate_choice(_request(), complete)
    assert result["verdict"] == "unchecked"
    assert "redirect" in result["message"]


def test_a_request_never_carries_a_file_path():
    request, note = build_evaluation_request(
        job="Track the pipeline.", sheet="Data",
        headers=["Deal", "Amount"], rows=[["Acme", "1200"]],
        choice={"labelColumn": "Deal", "valueColumn": "Amount", "rows": [0]},
        row_count=1,
    )
    assert "path" not in json.dumps(request).lower().replace("rowcount", "")
    assert note == DISCLOSURE_ROWS


def test_the_setup_flow_evaluates_a_staged_json_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    export = workspace / "pipeline.json"
    export.write_text(json.dumps([
        {"Deal": "Acme", "Amount": 1200},
        {"Deal": "Globex", "Amount": 800},
    ]), encoding="utf-8")
    data = tmp_path / "data"
    store = InstanceStore(data, workspace)
    store.create("excel-report", "main", "Pipeline")
    store.stage_file("excel-report", "main", export)
    runtime = SimpleNamespace(data_dir=data, workspace_dir=workspace)
    seen = {}

    def complete(prompt):
        seen["prompt"] = prompt
        return json.dumps({"verdict": "ok", "message": "The pairing checks out.", "recommendation": None})

    result = evaluate(
        runtime, 6, "main",
        {"labelColumn": "Deal", "valueColumn": "Amount", "rows": [0, 1]},
        complete=complete, plugin_id="excel-report",
    )
    assert result["verdict"] == "ok"
    assert result["message"] == "The pairing checks out."
    assert result["recommendation"] is None
    assert "Acme" in seen["prompt"]
    assert str(export) not in seen["prompt"]
