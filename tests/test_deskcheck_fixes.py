"""The desk check's automatic fixes: set aside, wiring, latch, ask card.

Every fix records itself in the ledger before it changes anything, so every
fix can be undone. A fix that fails three times for the same finding stops
being called and the desk check says so instead; a changed finding starts the
count over.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import server_harness
import test_deskcheck as base
from nexuusbot import deskcheck
from nexuusbot.deskcheck import fixes
from nexuusbot.ledger import Ledger
from nexuusbot.ledger import undo as ledger_undo


def _ctx(tmp_path, **kwargs):
    """A DeskContext with a real ledger, built from the ticket's helpers."""
    values = dict(
        settings=base.settings_store(),
        inbox=None,
        excel=None,
        calendar=None,
        plugins=None,
        catalog_ids=frozenset(),
        data_dir=tmp_path,
        ledger=Ledger(":memory:"),
        clock=lambda: base.NOW,
    )
    values.update(kwargs)
    return base.context(tmp_path, **values)


def test_set_aside_then_undo_roundtrip(tmp_path):
    """The rows leave the inbox only after their file and ledger entry exist."""
    inbox = base.inbox_with_raw_row(tmp_path)
    before = inbox.unreadable()
    ctx = _ctx(tmp_path, inbox=inbox)
    result = deskcheck.run_checks(ctx, should_fix=True)
    assert result.failed == {}
    assert len(result.fixed) == 1
    assert inbox.unreadable() == []
    files = sorted((tmp_path / "set-aside").glob("inbox-*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["rows"] == before
    assert saved["build"]
    entry = ctx.ledger.get(result.fixed[0])
    assert entry is not None
    assert entry.action == "deskcheck.fixed"
    assert entry.undo_kind == "inbox-rows"
    assert entry.detail["count"] == 1
    server = SimpleNamespace(inbox=inbox, ledger=ctx.ledger)
    ledger_undo.undo(server, ctx.ledger, entry.id)
    assert inbox.unreadable() == before
    # Undo of the undo puts the same rows away again.
    undo_entry = ctx.ledger.entries(limit=1)[0]
    ledger_undo.undo(server, ctx.ledger, undo_entry.id)
    assert inbox.unreadable() == []


def test_without_a_ledger_the_desk_does_not_fix(tmp_path):
    """No ledger means no before-state, so nothing is changed."""
    inbox = base.inbox_with_raw_row(tmp_path)
    ctx = _ctx(tmp_path, inbox=inbox, ledger=None)
    result = deskcheck.run_checks(ctx, should_fix=True)
    assert [finding.id for finding in result.findings] == ["inbox-unreadable-rows"]
    assert "ledger" in result.failed["inbox-unreadable-rows"]
    assert len(inbox.unreadable()) == 1
    assert not (tmp_path / "set-aside").exists()


def test_autonomy_off_reports_only(tmp_path):
    """The same run with autonomy off only reports; nothing is changed."""
    inbox = base.inbox_with_raw_row(tmp_path)
    ctx = _ctx(tmp_path, inbox=inbox, settings=base.settings_store(autonomy=False))
    result = deskcheck.run_checks(ctx, should_fix=True)
    assert [finding.id for finding in result.findings] == ["inbox-unreadable-rows"]
    assert result.fixed == []
    assert len(inbox.unreadable()) == 1
    assert not (tmp_path / "set-aside").exists()


def test_fix_fail_latch_and_reset(tmp_path, monkeypatch):
    """Three failures stop the fix; a changed finding lets it try again."""
    inbox = base.inbox_with_raw_row(tmp_path)
    original = fixes.FIXES["inbox-unreadable-rows"]
    calls = []

    def broken(ctx, finding):
        calls.append(finding.id)
        raise RuntimeError("set-aside folder disappeared")

    monkeypatch.setitem(fixes.FIXES, "inbox-unreadable-rows", broken)
    ctx = _ctx(tmp_path, inbox=inbox)
    for attempt in range(1, 4):
        result = deskcheck.run_checks(ctx, should_fix=True)
        ids = [finding.id for finding in result.findings]
        assert "inbox-unreadable-rows" in ids
        if attempt < 3:
            assert "fix-failing:inbox-unreadable-rows" not in ids
        else:
            assert "fix-failing:inbox-unreadable-rows" in ids
        assert result.fixed == []
        assert result.failed["inbox-unreadable-rows"] == "RuntimeError: set-aside folder disappeared"
    assert len(calls) == 3
    state = json.loads(ctx.ledger.latch_value("fixfail:inbox-unreadable-rows"))
    assert state["count"] == 3
    fourth = deskcheck.run_checks(ctx, should_fix=True)
    ids = [finding.id for finding in fourth.findings]
    assert "inbox-unreadable-rows" in ids
    assert "fix-failing:inbox-unreadable-rows" in ids
    failing = next(finding for finding in fourth.findings if finding.id.startswith("fix-failing:"))
    assert "tried to fix this 3 times" in failing.cause
    assert "set-aside folder disappeared" in failing.cause
    assert len(calls) == 3
    # A different detail hash is a different problem: the count starts over.
    monkeypatch.setitem(fixes.FIXES, "inbox-unreadable-rows", original)
    inbox.conn.execute(
        "INSERT INTO cards (id, kind, origin, title, body, action_label, status, created_ts, meta) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("raw-promise", "promise", "desk", "A promise this version cannot show",
         "body", "Open", "waiting", base.NOW, "{}"),
    )
    inbox.conn.commit()
    reset = deskcheck.run_checks(ctx, should_fix=True)
    assert len(reset.fixed) == 1
    assert inbox.unreadable() == []
    assert ctx.ledger.latch_value("fixfail:inbox-unreadable-rows") is None


def test_retired_plugins_is_one_ask_card(tmp_path):
    """The retired-plugins check asks once, by card, never by uninstalling."""
    runtime = base.plugin_runtime(tmp_path, **{"retired-thing": "enabled"})
    inbox = base.inbox_store(tmp_path / "inbox")
    ctx = _ctx(tmp_path, inbox=inbox, plugins=runtime,
               catalog_ids=frozenset({"kept-plugin"}))
    for _ in range(2):
        deskcheck.run_checks(ctx)
    cards = [card for card in inbox.waiting(include_snoozed=True)
             if card.meta.get("ask") == "retired-plugins"]
    assert len(cards) == 1
    card = cards[0]
    assert card.kind == "suggestion"
    assert card.action_label == "Remove them"
    assert card.meta["ids"] == ["retired-thing"]
    assert "retired-thing" in card.body
    assert runtime.record("retired-thing")["state"] != "uninstalled"


def _installed_runtime(tmp_path, plugin_id="retired-thing"):
    """A real runtime with one installed plugin that has its own data folder."""
    from nexuusbot.plugins.runtime import PluginRuntime

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "plugin-data" / plugin_id
    data_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": plugin_id,
        "state": "enabled",
        "versions": [],
        "pending_update": None,
        "schedules": [],
        "data_dir": str(data_dir),
    }
    (plugins_dir / "lockfile.json").write_text(
        json.dumps({"plugins": {plugin_id: entry}, "graveyard": {}}),
        encoding="utf-8",
    )
    runtime = PluginRuntime(plugins_dir, tmp_path / "plugin-data", tmp_path / "workspace")
    return runtime, data_dir


def test_accepting_ask_card_uninstalls_keeps_data(tmp_path, monkeypatch):
    """Accepting the card is the only path that uninstalls; data folders stay."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    runtime, data_dir = _installed_runtime(tmp_path)
    (data_dir / "kept.txt").write_text("keep me", encoding="utf-8")
    booted = server_harness.Booted(plugins=runtime)
    try:
        auth = booted.exchange()
        status, _headers, _body = booted.request("GET", "/api/desk-check", auth)
        assert status == 200
        cards = [card for card in booted.server.inbox.waiting(include_snoozed=True)
                 if card.meta.get("ask") == "retired-plugins"]
        assert len(cards) == 1
        status, _headers, _body = booted.post_json(
            "/inbox/cards/" + cards[0].id + "/accept", {}, auth)
        assert status == 200
        assert runtime.record("retired-thing")["state"] == "uninstalled"
        assert data_dir.exists()
        assert (data_dir / "kept.txt").read_text(encoding="utf-8") == "keep me"
    finally:
        booted.close()


def test_the_desk_never_uninstalls_or_sends_without_the_card():
    """The fix machinery may only ask: no uninstall, purge or mail send there."""
    repo = Path(__file__).resolve().parents[1]
    folders = [repo / "src/nexuusbot/deskcheck"]
    for extra in ("agentloop", "recommend"):
        folder = repo / "src" / "nexuusbot" / extra
        if folder.is_dir():
            folders.append(folder)
    forbidden = ("uninstall(", "purge_data(", "send_mail(")
    checked = 0
    for folder in folders:
        for path in sorted(folder.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                assert word not in text, f"{path} calls {word} without the user's card"
            checked += 1
    assert checked > 0


def test_fix_route_sets_rows_aside_and_activity_undo_restores(tmp_path, monkeypatch):
    """The acceptance path: one POST fixes, Activity offers Undo, Undo restores."""
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "desk-data"))
    inbox = base.inbox_with_raw_row(tmp_path)
    before = inbox.unreadable()
    booted = server_harness.Booted(inbox_store=inbox)
    try:
        auth = booted.exchange()
        status, _headers, body = booted.request("GET", "/api/desk-check", auth)
        assert status == 200
        assert "inbox-unreadable-rows" in [
            finding["id"] for finding in json.loads(body)["findings"]
        ]

        status, _headers, body = booted.post_json(
            "/api/desk-check/fix", {"id": "inbox-unreadable-rows"}, auth)
        assert status == 200, body
        result = json.loads(body)
        assert result["fixed"] is True
        assert result["entry"]
        assert inbox.unreadable() == []
        files = sorted((tmp_path / "desk-data" / "set-aside").glob("inbox-*.json"))
        assert len(files) == 1
        assert json.loads(files[0].read_text(encoding="utf-8"))["rows"] == before

        status, _headers, body = booted.request("GET", "/settings/activity", auth)
        assert status == 200
        page = body.decode("utf-8")
        assert result["entry"] in page
        assert "Undo" in page

        status, _headers, body = booted.post_json(
            "/api/ledger/undo", {"id": result["entry"]}, auth)
        assert status == 200, body
        assert inbox.unreadable() == before

        # The same rows are unreadable again, so the check detects them again.
        status, _headers, body = booted.request("GET", "/api/desk-check", auth)
        assert status == 200
        assert "inbox-unreadable-rows" in [
            finding["id"] for finding in json.loads(body)["findings"]
        ]
    finally:
        booted.close()
