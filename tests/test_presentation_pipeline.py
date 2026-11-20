"""Plan, gather, fill: the deck comes from the mock, numbers stay sourced.

The seam is the run route. A slow call degrades that run. Worksheet brief
still uses the 10 second cap.
"""

import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.assistant import audit as audit_store
from agentdesk.llm import REQUEST_TIMEOUT_S, chat_client
from agentdesk.presentations.pipeline import guard_numbers
from agentdesk.presentations.writer import slide_texts
from mock_endpoint import MockEndpointHandler

RECIPES = {
    "briefing": ["context", "findings", "next"],
    "qbr": ["snapshot", "performance", "wins", "risks", "asks"],
    "competitor-brief": ["landscape", "profile", "gaps", "implications", "moves"],
}


def _mock_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockEndpointHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _run(booted, auth, recipe):
    return booted.post_json(
        "/agents/run",
        {"agent": "presentation", "brief": "the Q3 review",
         "template": "starter", "variant": "dark", "recipe": recipe,
         "use_memory": "1"},
        auth,
    )


def test_each_recipe_downloads_a_deck_filled_from_the_mock():
    mock = _mock_server()
    try:
        port = mock.server_address[1]
        booted = server_harness.Booted(llm=chat_client(f"http://127.0.0.1:{port}/v1", "", "mock"))
        booted.server.llm_endpoint = f"http://127.0.0.1:{port}/v1"
        try:
            auth = booted.exchange()
            for recipe, _ids in RECIPES.items():
                status, _h, body = _run(booted, auth, recipe)
                payload = json.loads(body)
                assert status == 200, body
                assert payload["status"] == "ok", payload
                run_id = payload["id"]
                status, _h, blob = booted.request("GET", f"/agents/runs/{run_id}/download", auth)
                assert status == 200
                texts = " ".join(
                    " ".join(row["texts"]) for row in slide_texts(blob)
                )
                assert "From the mock" in texts
        finally:
            booted.close()
    finally:
        mock.shutdown()


def test_an_unsourced_number_never_reaches_the_deck():
    def llm(prompt, timeout=30):
        if "Presentation plan" in prompt:
            return json.dumps({"sections": [
                {"id": "context", "title": "Context"},
                {"id": "findings", "title": "Findings"},
                {"id": "next", "title": "What we do next"},
            ]})
        return json.dumps({
            "title": "Invented",
            "bullets": ["Revenue is 999."],
            "citations": [1],
        })

    booted = server_harness.Booted(llm=llm)
    booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
    try:
        auth = booted.exchange()
        booted.post_json("/memory/add", {"text": "the review is about revenue"}, auth)
        status, _h, body = _run(booted, auth, "briefing")
        payload = json.loads(body)
        assert payload["status"] == "ok"
        blob = booted.request("GET", f"/agents/runs/{payload['id']}/download", auth)[2]
        text = " ".join(" ".join(row["texts"]) + " " + row["notes"] for row in slide_texts(blob))
        assert "999" not in text
        assert "[data needed]" in text
    finally:
        booted.close()


def test_disabled_sources_are_not_read_and_the_receipt_names_what_was():
    seen = []

    def llm(prompt, timeout=30):
        seen.append(prompt)
        if "Presentation plan" in prompt:
            return json.dumps({"sections": [
                {"id": "context", "title": "Context"},
                {"id": "findings", "title": "Findings"},
                {"id": "next", "title": "What we do next"},
            ]})
        return json.dumps({"title": "Noted", "bullets": ["No figure was supplied."], "citations": []})

    booted = server_harness.Booted(llm=llm)
    booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
    booted.server.page_watch = {"text": "the page changed", "at": "2026-11-20T12:00:00Z"}
    try:
        auth = booted.exchange()
        booted.post_json("/memory/add", {"text": "revenue is the topic"}, auth)
        status, _h, body = booted.post_json(
            "/agents/run",
            {"agent": "presentation", "brief": "revenue review",
             "template": "starter", "variant": "dark", "recipe": "briefing",
             "use_memory": "0", "use_workbook": "0", "use_watch": "1"},
            auth,
        )
        payload = json.loads(body)
        assert payload["status"] == "ok", payload
        kinds = [row["kind"] for row in payload["artifact"]["sources"]]
        assert "memory" not in kinds
        assert "competitor-watch" in kinds
        assert any(row["at"] == "2026-11-20T12:00:00Z" for row in payload["artifact"]["sources"])
        fill = next(prompt for prompt in seen if "Presentation fill" in prompt)
        assert "revenue is the topic" not in fill
        assert "the page changed" in fill
        rows = [row for row in audit_store.entries(booted.server.audit_conn) if row["action"] == "agents.run"]
        assert "template starter@0.1.0" in rows[-1]["detail"]
        assert "recipe briefing" in rows[-1]["detail"]
        assert "competitor-watch" in rows[-1]["detail"]
    finally:
        booted.close()


def test_a_call_near_the_timeout_succeeds_and_past_it_degrades():
    def llm(prompt):
        time.sleep(0.2)
        if "Presentation plan" in prompt:
            return json.dumps({"sections": [
                {"id": "context", "title": "Context"},
                {"id": "findings", "title": "Findings"},
                {"id": "next", "title": "What we do next"},
            ]})
        return json.dumps({"title": "Noted", "bullets": ["No figure was supplied."], "citations": []})

    booted = server_harness.Booted(llm=llm)
    booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
    booted.server.settings.set("presentation_timeout_s", "2")
    try:
        auth = booted.exchange()
        status, _h, body = _run(booted, auth, "briefing")
        assert json.loads(body)["status"] == "ok"
        booted.server.settings.set("presentation_timeout_s", "0.05")
        status, _h, body = _run(booted, auth, "briefing")
        payload = json.loads(body)
        assert payload["status"] == "degraded"
        assert "timeout" in payload["cause"]
        assert payload["artifact"] is None
    finally:
        booted.close()


def test_worksheet_brief_stays_on_the_ten_second_cap():
    seen = []

    def llm(prompt, timeout=REQUEST_TIMEOUT_S):
        seen.append(timeout)
        return "A short briefing."

    booted = server_harness.Booted(llm=llm)
    booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
    try:
        auth = booted.exchange()
        status, _h, body = booted.post_json(
            "/agents/run",
            {"agent": "worksheet-brief", "brief": "brief me"},
            auth,
        )
        assert json.loads(body)["status"] == "ok"
        assert seen == [REQUEST_TIMEOUT_S]
        assert REQUEST_TIMEOUT_S == 10
    finally:
        booted.close()


def test_the_digit_guard_replaces_only_unsourced_numbers():
    sources = [{"id": 1, "text": "revenue is 220", "kind": "memory", "label": "Memory", "at": ""}]
    assert guard_numbers("revenue is 220", sources, [1]) == "revenue is 220"
    assert guard_numbers("revenue is 999", sources, [1]) == "revenue is [data needed]"
    assert guard_numbers("revenue is 220", sources, []) == "revenue is [data needed]"
