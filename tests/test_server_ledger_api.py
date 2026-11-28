"""The action ledger over HTTP, the way the Activity page and Undo use it.

Every test boots the real server (server_harness.Booted) with a throwaway
ledger, signs in through the one-time exchange and speaks HTTP, so the
seam under test is the one the browser gets.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest

import server_harness
from nexuusbot.inbox.core import STATUS_DISMISSED, STATUS_WAITING
from nexuusbot.ledger import Ledger


@pytest.fixture
def env(tmp_path: Path):
    booted = server_harness.Booted(ledger=Ledger(tmp_path / "ledger.sqlite3"))
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture
def auth(env):
    return env.exchange()


def _seed_settings_change(env, *, why: str = "Quiet hours started, so the cap went down."):
    """Record the change the way the app does, then apply it."""
    server = env.server
    server.settings.set("daily_cap", 3)
    entry = server.ledger.record(
        actor="agent-desk",
        action="settings.set",
        subject="daily_cap",
        why=why,
        undo_kind="settings-key",
        before=json.dumps({"key": "daily_cap", "value": 3}).encode(),
        after=json.dumps({"key": "daily_cap", "value": 1}).encode(),
    )
    server.settings.set("daily_cap", 1)
    return entry


def _get_json(env, auth, path: str):
    status, _headers, body = env.request("GET", path, auth)
    assert status == 200, body
    return json.loads(body)


def _post_form(env, auth, path: str, fields: dict):
    body = "&".join(f"{key}={value}" for key, value in fields.items()).encode()
    headers = dict(auth)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    headers["Content-Length"] = str(len(body))
    return env.request("POST", path, headers, body)


def test_get_api_ledger_starts_empty(env, auth) -> None:
    assert _get_json(env, auth, "/api/ledger") == {"entries": []}


def test_undo_restores_previous_setting(env, auth) -> None:
    entry = _seed_settings_change(env)
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["undone"] == entry.id
    assert env.server.settings.get("daily_cap") == 3
    undo_entry = env.server.ledger.get(payload["entry"])
    assert undo_entry is not None
    assert undo_entry.undoes == entry.id
    assert undo_entry.undo_kind == "settings-key"
    assert undo_entry.actor == "user"
    assert env.server.ledger.get(entry.id).undone_by == undo_entry.id

    listed = _get_json(env, auth, "/api/ledger")["entries"]
    assert listed[0]["id"] == undo_entry.id
    assert listed[0]["undoes"] == entry.id
    assert listed[0]["undoable"] is True
    original = next(row for row in listed if row["id"] == entry.id)
    assert original["undoable"] is False
    assert original["undoneBy"] == undo_entry.id
    assert original["undoes"] is None


def test_undo_of_undo_redoes(env, auth) -> None:
    entry = _seed_settings_change(env)
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 200, body
    assert env.server.settings.get("daily_cap") == 3
    redo_id = json.loads(body)["entry"]
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": redo_id}, auth)
    assert status == 200, body
    assert env.server.settings.get("daily_cap") == 1
    redo = env.server.ledger.get(json.loads(body)["entry"])
    assert redo.undoes == redo_id
    assert env.server.ledger.get(redo_id).undone_by == redo.id


def test_double_undo_is_409(env, auth) -> None:
    entry = _seed_settings_change(env)
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 200, body
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 409
    assert json.loads(body) == {"error": "That change was already undone."}


def test_undo_unknown_entry_is_404(env, auth) -> None:
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": "no-such-entry"}, auth)
    assert status == 404
    assert json.loads(body) == {"error": "That change is not in the ledger."}


def test_failed_capture_leaves_state_unchanged(env, auth) -> None:
    entry = _seed_settings_change(env)
    env.server.ledger.blob_cap = 1  # capturing the current value can no longer fit
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 409
    assert "nothing was changed" in json.loads(body)["error"]
    assert env.server.settings.get("daily_cap") == 1
    assert env.server.ledger.get(entry.id).undone_by is None
    assert len(env.server.ledger.entries()) == 1


def test_activity_page_lists_ledger_with_undo(env, auth) -> None:
    status, _headers, body = env.request("GET", "/settings/activity", auth)
    assert status == 200
    assert "The desk hasn't changed anything by itself yet." in body.decode()

    entry = _seed_settings_change(env)
    status, _headers, body = env.request("GET", "/settings/activity", auth)
    page = body.decode()
    assert "Changes the desk made by itself" in page
    assert "Quiet hours started, so the cap went down." in page
    assert entry.id in page
    assert 'action="/api/ledger/undo"' in page
    assert page.index("Changes the desk made by itself") < page.index("Questions you asked")

    status, headers, _body = _post_form(
        env, auth, "/api/ledger/undo",
        {"id": entry.id, "return_to": "%2Fsettings%2Factivity"},
    )
    assert status == 303
    assert headers["Location"] == "/settings/activity"
    assert env.server.settings.get("daily_cap") == 3

    status, _headers, body = env.request("GET", "/settings/activity", auth)
    page = body.decode()
    assert "Undone " in page
    assert "Quiet hours started, so the cap went down." in page

    status, _headers, body = env.request("GET", "/settings", auth)
    assert status == 200
    assert "3 (normal)" in body.decode()


def _card_capture(server, card) -> bytes:
    return json.dumps(card.to_json(server.inbox.now_ts()), ensure_ascii=False).encode()


def test_card_undo_kinds(env, auth) -> None:
    server = env.server
    inbox = server.inbox

    # A card the desk added by itself is undone by dismissing it.
    added = inbox.add("suggestion", "excel", "Try a pivot table")
    entry = server.ledger.record(
        actor="agent-desk",
        action="inbox.add",
        subject=f"card/{added.id}",
        why="The desk added a suggestion card.",
        undo_kind="card-added",
        before=_card_capture(server, added),
    )
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 200, body
    assert inbox.get(added.id).status == STATUS_DISMISSED
    inverse = server.ledger.get(json.loads(body)["entry"])
    assert inverse.undo_kind == "card-dismissed"

    # A card the desk dismissed by itself is undone by reopening it.
    dismissed = inbox.add("suggestion", "excel", "Act on the plan")
    dismissed = inbox.dismiss(dismissed.id)
    entry = server.ledger.record(
        actor="agent-desk",
        action="inbox.dismiss",
        subject=f"card/{dismissed.id}",
        why="The desk dismissed a card nobody needed.",
        undo_kind="card-dismissed",
        before=_card_capture(server, dismissed),
    )
    status, _headers, body = env.post_json("/api/ledger/undo", {"id": entry.id}, auth)
    assert status == 200, body
    assert inbox.get(dismissed.id).status == STATUS_WAITING
    inverse = server.ledger.get(json.loads(body)["entry"])
    assert inverse.undo_kind == "card-added"


def test_redoing_a_card_undo_uses_the_opposite_kind(env, auth) -> None:
    server = env.server
    inbox = server.inbox
    added = inbox.add("suggestion", "excel", "Try a pivot table")
    entry = server.ledger.record(
        actor="agent-desk",
        action="inbox.add",
        subject=f"card/{added.id}",
        why="The desk added a suggestion card.",
        undo_kind="card-added",
        before=_card_capture(server, added),
    )
    first = json.loads(env.post_json("/api/ledger/undo", {"id": entry.id}, auth)[2])
    redo = json.loads(env.post_json("/api/ledger/undo", {"id": first["entry"]}, auth)[2])
    assert server.ledger.get(redo["entry"]).undo_kind == "card-added"
    assert inbox.get(added.id).status != STATUS_DISMISSED

    dismissed = inbox.add("suggestion", "excel", "Act on the plan")
    dismissed = inbox.dismiss(dismissed.id)
    entry = server.ledger.record(
        actor="agent-desk",
        action="inbox.dismiss",
        subject=f"card/{dismissed.id}",
        why="The desk dismissed a card nobody needed.",
        undo_kind="card-dismissed",
        before=_card_capture(server, dismissed),
    )
    first = json.loads(env.post_json("/api/ledger/undo", {"id": entry.id}, auth)[2])
    redo = json.loads(env.post_json("/api/ledger/undo", {"id": first["entry"]}, auth)[2])
    assert server.ledger.get(redo["entry"]).undo_kind == "card-dismissed"
    assert inbox.get(dismissed.id).status == STATUS_DISMISSED


def test_a_crafted_return_to_cannot_inject_a_header(env, auth) -> None:
    status, headers, _body = _post_form(env, auth, "/settings/toggle", {
        "key": "quiet_hours",
        "return_to": "/settings%0d%0aX-Injected:%20yes",
    })
    location = headers.get("Location", "")
    joined = " ".join(f"{name}:{value}" for name, value in headers.items())
    assert status == 303
    assert "X-Injected" not in joined
    assert "\r" not in joined and "\n" not in joined
    assert location.split("?", 1)[0] in ("/inbox", "/settings")

    entry = _seed_settings_change(env)
    status, headers, body = _post_form(env, auth, "/api/ledger/undo", {
        "id": "missing",
        "return_to": "/settings%0d%0aX-Injected:%20yes",
    })
    assert status == 303
    assert not body.startswith(b"{")
    location = headers.get("Location", "")
    assert "X-Injected" not in location
    assert location.startswith("/settings")
    assert "not in the ledger" in location or "change" in location.lower()

    status, headers, _body = _post_form(env, auth, "/api/ledger/undo", {
        "id": entry.id,
        "return_to": "/settings%0d%0aX-Injected:%20yes",
    })
    location = headers.get("Location", "")
    joined = " ".join(f"{name}:{value}" for name, value in headers.items())
    assert status == 303
    assert "X-Injected" not in joined
    assert location == "/settings"
