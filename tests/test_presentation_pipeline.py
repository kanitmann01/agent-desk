"""Plan, gather, fill: the deck comes from the mock, numbers stay sourced.

The seam is the run route. A slow call degrades that run. Worksheet brief
still uses the 10 second cap.
"""

import json
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
import pytest
from nexuusbot.assistant import audit as audit_store
from nexuusbot.llm import REQUEST_TIMEOUT_S, LlmUnavailable, chat_client
from nexuusbot.presentations.packs import load_packs
from nexuusbot.presentations.pipeline import (
    call_model,
    gather,
    guard_numbers,
    outline_from_fill,
    run_fill,
)
from nexuusbot.presentations.writer import read_parts, slide_texts
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
                assert "Q3 Review" in texts
                assert texts.count("starts from the brief") >= len(_ids)
                assert texts.count("easier to retell") >= len(_ids)
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
    """The timeout really reaches the client's socket cap (spec 018 #233
    removed the introspection and the thread-join fallback, so the client
    contract is the only clock): the client is handed the seconds and a
    client that honours them degrades the run exactly as a real socket
    timeout would."""

    def llm(prompt, timeout=30):
        time.sleep(0.2)
        if timeout < 0.15:
            raise LlmUnavailable(
                f"the endpoint did not answer within {timeout:g} seconds (timeout)")
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
        assert "0.05" in payload["cause"]
        assert payload["artifact"] is None
    finally:
        booted.close()


def test_every_client_the_desk_builds_takes_the_timeout_keyword():
    """The client contract behind the introspection's removal: the three
    factories every call-site can reach all accept the keyword (no
    TypeError, only the endpoint's own named refusal), so call_model
    never needs to guess again."""
    from nexuusbot.llm import env_chat, settings_chat

    for client in (chat_client("http://127.0.0.1:9/v1", "k", "m"),
                   settings_chat(None), env_chat()):
        with pytest.raises(LlmUnavailable):
            client("ping", timeout=0.25)


def test_call_model_hands_the_timeout_to_the_client_unchanged():
    """One call, one keyword: the seconds the run configured are the
    seconds the client sees on its socket cap."""
    from nexuusbot.presentations.pipeline import call_model

    seen = []

    def llm(prompt, timeout=30):
        seen.append(timeout)
        return "[]"

    assert call_model(llm, "hello", 45) == "[]"
    assert seen == [45]


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
    sources = [{"id": 1, "text": "220 in Q3 2026", "kind": "memory", "label": "Memory", "at": ""}]
    assert guard_numbers("revenue is 220", sources, [1]) == "revenue is 220"
    assert guard_numbers("revenue is 999", sources, [1]) == "revenue is [data needed]"
    assert guard_numbers("revenue is 220", sources, []) == "revenue is [data needed]"
    for token in ("20", "202", "6", "0.2", "22.0"):
        assert guard_numbers(f"figure {token}", sources, [1]) == "figure [data needed]"
    assert guard_numbers("figure 22.0", [{"id": 1, "text": "about 22.0"}], [1]) == "figure 22.0"
    outline = outline_from_fill(
        "review",
        {"sections": [{"id": "context"}]},
        [{"id": "context", "title": "Up 20"}],
        [{"title": "Up 20", "bullets": ["220 held"], "citations": [1]}],
        sources,
    )
    assert outline["slides"][1]["title"] == "Up [data needed]"
    assert "220" in outline["slides"][2]["bullets"][0]


def test_run_fill_answers_with_the_delivered_deck_or_a_cause():
    """The one fill entry under a fake llm, no server: a good run writes
    the deck and names its folder, a dead endpoint and a malformed fill
    come back as the degraded sentences with nothing written."""
    def runner(_argv, _timeout):
        """A renderer that never succeeds, so the test needs none installed."""
        return SimpleNamespace(returncode=1)

    with tempfile.TemporaryDirectory(prefix="agentdesk-runfill-") as root:
        empty_user = Path(root) / "templates"
        empty_user.mkdir()
        deck_dir = Path(root) / "decks"
        pack = next(item for item in load_packs(registry_root=ROOT / "registry", user_dir=empty_user)
                    if item.id == "starter")
        recipe = pack.recipe("briefing")
        planned = [{"id": "context", "title": "Context"}]

        def llm(prompt, timeout=30):
            return json.dumps({"title": "Filled", "bullets": ["Noted."], "citations": []})

        delivered, cause = run_fill(
            pack, "dark", recipe, planned, [], "the Q3 review",
            "Q3 Review", llm, 30, deck_dir, runner=runner,
        )
        assert cause == ""
        assert delivered["rendered"]["renderer"] == "none"
        assert (deck_dir / delivered["folder"] / "deck.pptx").is_file()

        def dead(prompt, timeout=30):
            raise LlmUnavailable("the endpoint did not answer")

        delivered, cause = run_fill(
            pack, "dark", recipe, planned, [], "the Q3 review",
            "Q3 Review", dead, 30, deck_dir, runner=runner,
        )
        assert delivered is None
        assert cause == "the endpoint did not answer"

        def malformed(prompt, timeout=30):
            return "not json"

        delivered, cause = run_fill(
            pack, "dark", recipe, planned, [], "the Q3 review",
            "Q3 Review", malformed, 30, deck_dir, runner=runner,
        )
        assert delivered is None
        assert cause == "The presentation could not be filled, so no deck was written."


def test_a_real_type_error_is_not_tried_twice():
    calls = []

    def llm(prompt, timeout=30):
        calls.append(timeout)
        raise TypeError("bad prompt")

    try:
        call_model(llm, "hello", 5)
    except TypeError as exc:
        assert "bad prompt" in str(exc)
    else:
        raise AssertionError("expected TypeError")
    assert calls == [5]


def test_a_workbook_note_uses_the_file_name_and_keeps_line_breaks():
    sources = gather(
        [],
        {"configured": True, "path": "/Users/someone/Book.xlsx", "polledAt": "2026-11-20T00:00:00Z"},
        None,
        {"excel-report"},
    )
    assert "/Users/" not in sources[0]["text"]
    assert "Book.xlsx" in sources[0]["text"]
    outline = outline_from_fill(
        "review",
        {"sections": [{"id": "context"}]},
        [{"id": "context", "title": "Context"}],
        [{"title": "Context", "bullets": ["Noted"], "citations": [1]}],
        sources,
    )
    from nexuusbot.presentations.ooxml import build_shell
    from nexuusbot.presentations.writer import write_deck
    recipe = json.loads((ROOT / "registry/plugins/presentation-starter/recipes/briefing.json").read_text())
    # One section is enough for the notes part; the recipe still names the layouts.
    blob = write_deck(build_shell(), recipe, {
        "title": "review",
        "slides": [outline["slides"][2]],
    })
    notes = read_parts(blob)["ppt/notesSlides/notesSlide1.xml"].decode("utf-8")
    assert notes.count("<a:p>") >= 2
    assert "/Users/" not in notes


def test_an_unticked_form_source_stays_off_and_the_watch_file_is_read():
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
    root = Path(booted.server.plugins.data_dir) / "competitor-watch"
    root.mkdir(parents=True, exist_ok=True)
    (root / "http-state.json").write_text(json.dumps({
        "https://example.com/page": {
            "value": "the page changed",
            "checkedAt": "2026-11-20T12:00:00Z",
        },
    }), encoding="utf-8")
    try:
        auth = booted.exchange()
        booted.post_json("/memory/add", {"text": "revenue is the topic"}, auth)
        body = urllib.parse.urlencode({
            "agent": "presentation",
            "brief": "revenue review",
            "template": "starter",
            "variant": "dark",
            "recipe": "briefing",
            "sources_form": "1",
            "use_watch": "1",
        }).encode("utf-8")
        status, headers, _page = booted.request(
            "POST", "/agents/run",
            {**auth, "Content-Type": "application/x-www-form-urlencoded"},
            body,
        )
        assert status == 303
        row = booted.server.agents.conn.execute(
            "SELECT artifact FROM agent_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        artifact = json.loads(row[0])
        kinds = [row["kind"] for row in artifact["sources"]]
        assert kinds == ["competitor-watch"]
        fill = next(prompt for prompt in seen if "Presentation fill" in prompt)
        assert "revenue is the topic" not in fill
        assert "the page changed" in fill
        assert 'name="sources_form"' in booted.request("GET", "/agents", auth)[2].decode("utf-8")
    finally:
        booted.close()


def test_a_presentation_timeout_outside_the_range_is_refused():
    booted = server_harness.Booted()
    try:
        auth = booted.exchange()
        for raw in ("4", "301", "soon"):
            status, _h, body = booted.post_json(
                "/settings/endpoint/save",
                {"presentationTimeout": raw},
                auth,
            )
            assert status == 400, body
            assert "5 to 300" in body.decode("utf-8")
        status, _h, body = booted.post_json(
            "/settings/endpoint/save",
            {"presentationTimeout": "45"},
            auth,
        )
        assert status == 200
        assert booted.server.settings.get("presentation_timeout_s") == "45"
    finally:
        booted.close()


def test_a_write_failure_does_not_blame_the_endpoint():
    def llm(prompt, timeout=30):
        if "Presentation plan" in prompt:
            return json.dumps({"sections": [
                {"id": "context", "title": "Context"},
                {"id": "findings", "title": "Findings"},
                {"id": "next", "title": "What we do next"},
            ]})
        return json.dumps({"title": "Noted", "bullets": ["No figure was supplied."], "citations": []})

    booted = server_harness.Booted(llm=llm)
    booted.server.llm_endpoint = "http://127.0.0.1:9/v1"
    import nexuusbot.presentations.deliver as deliver

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    original = deliver.write_deck
    deliver.write_deck = boom
    try:
        auth = booted.exchange()
        status, _h, body = _run(booted, auth, "briefing")
        payload = json.loads(body)
        assert payload["status"] == "degraded"
        assert payload["cause"] == "The deck could not be written."
        assert "not answering" not in payload["cause"]
        assert "disk full" not in payload["cause"]
    finally:
        deliver.write_deck = original
        booted.close()


def test_the_fill_cause_reads_the_step_off_the_exception():
    from nexuusbot.llm import LlmUnavailable
    from nexuusbot.presentations.pipeline import fill_cause

    assert fill_cause(LlmUnavailable("the endpoint is not answering")) == \
        "the endpoint is not answering"
    assert fill_cause(ValueError("malformed plan")) == \
        "The presentation plan could not be read, so no deck was written."
    assert fill_cause(ValueError("malformed fill")) == \
        "The presentation could not be filled, so no deck was written."
    assert fill_cause(OSError("disk full")) == "The deck could not be written."


def test_a_missing_shell_variant_degrades_instead_of_raising(tmp_path):
    # run_fill sits under both callers' None guards, but its own contract
    # is "a written deck or a cause": a bad variant is a cause, never an
    # AttributeError past the ladder.
    from nexuusbot.presentations.pipeline import run_fill

    def llm(prompt, timeout=30):
        return json.dumps({"title": "Noted", "bullets": ["No figure."], "citations": []})

    pack = SimpleNamespace(shell_path=lambda variant: None)
    delivered, cause = run_fill(pack, "no-such-variant", {}, [], [], "brief",
                               "Title", llm, 30.0, tmp_path)
    assert delivered is None
    assert cause == "The deck could not be written."
