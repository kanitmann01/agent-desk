"""The learn-topics step, its latch, and the learned surfaces (ticket 08).

Five or more similar asks that name a memory entity add that entity as a
learned focus topic, labelled "Learned from N asks", recorded in the
ledger and undoable; once removed (route or Undo) the latch keeps it from
ever coming back. The stated preferences file is never touched by any of
it, which a sha256 comparison pins.
"""

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path


import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import server_harness
from agentdesk.agentloop import STEPS
from agentdesk.insight.preferences import PreferenceStore
from agentdesk.ledger.store import Ledger, LedgerError
from agentdesk.memory import profile
from agentdesk.memory.store import MemoryStore
from agentdesk.repetition.activity import ActivityLog
from agentdesk.server import app as server_app
from agentdesk.settings import SettingsStore

ASK = "summarise the Kestrel Foods order history"


class Desk:
    """The three attributes the step reads, over real stores."""

    def __init__(self, activity, memory, learned_profile):
        self.activity_log = activity
        self.memory = memory
        self.learned_profile = learned_profile


def _desk(tmp_path, monkeypatch, stated=None):
    """A desk-shaped bundle over in-memory stores; AGENTDESK_DATA moves
    the preferences file the step reads the stated topics from."""
    data = tmp_path / "data"
    monkeypatch.setenv("AGENTDESK_DATA", str(data))
    memory = MemoryStore(sqlite3.connect(":memory:", check_same_thread=False),
                         time.time)
    activity = ActivityLog(sqlite3.connect(":memory:", check_same_thread=False),
                           clock=lambda: 1763650000.0)
    learned = profile.LearnedProfileStore(
        data / "profile.learned.json", clock=lambda: 1763650000.0)
    if stated:
        PreferenceStore(data).write({"focusTopics": stated})
    return Desk(activity, memory, learned)


def _seed_entity(memory):
    """One standing fact that gives Kestrel Foods a memory entity."""
    fact = memory.add("Kestrel Foods supplies the staff canteen.",
                      source="seed")
    memory.resolve_and_link(fact.id, [("Kestrel Foods", "org")])


def _ledger_bundle():
    """One shared ledger, settings and audit connection, so a latch
    written by one pass is visible to the next (the real desk keeps its
    ledger on disk across passes)."""
    ledger = Ledger(":memory:")
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False))
    audit = sqlite3.connect(":memory:", check_same_thread=False)
    from agentdesk.assistant import audit as audit_store
    audit_store.ensure_schema(audit)
    return ledger, settings, audit


def _run(desk, bundle):
    ledger, settings, audit = bundle
    outcome = server_app.learn_focus_topics(desk, ledger, settings,
                                            audit_conn=audit)
    return outcome, ledger, audit


# -- the step ---------------------------------------------------------------


def test_topic_learned_from_entity_cluster_only(tmp_path, monkeypatch):
    desk = _desk(tmp_path, monkeypatch)
    _seed_entity(desk.memory)
    for _ in range(5):
        desk.activity_log.record("research", ASK)
    bundle = _ledger_bundle()
    outcome, ledger, audit = _run(desk, bundle)
    assert outcome == {"topics": 1}
    [topic] = desk.learned_profile.document()["focusTopics"]
    assert topic["topic"] == "Kestrel Foods"
    assert topic["learnedFrom"] == {"asks": 5}
    entry = ledger.entries()[0]
    assert entry.action == "profile.learned"
    assert entry.undo_kind == "learned-profile"
    assert entry.undoable is True
    actions = {row[0] for row in audit.execute("SELECT action FROM audit")}
    assert "profile.learned" in actions
    # The latch is what keeps a removed topic away forever.
    assert ledger.latch_value("topic:kestrel foods") is not None


def test_asks_without_a_named_entity_learn_nothing(tmp_path, monkeypatch):
    desk = _desk(tmp_path, monkeypatch)
    _seed_entity(desk.memory)
    for _ in range(5):
        desk.activity_log.record("research", "summarise the order history")
    bundle = _ledger_bundle()
    outcome, ledger, _audit = _run(desk, bundle)
    assert outcome == {"topics": 0}
    assert desk.learned_profile.document()["focusTopics"] == []
    assert [e.action for e in ledger.entries()] == []


def test_four_similar_asks_learn_nothing(tmp_path, monkeypatch):
    desk = _desk(tmp_path, monkeypatch)
    _seed_entity(desk.memory)
    for _ in range(4):
        desk.activity_log.record("research", ASK)
    bundle = _ledger_bundle()
    outcome, _ledger, _audit = _run(desk, bundle)
    assert outcome == {"topics": 0}
    assert desk.learned_profile.document()["focusTopics"] == []


def test_a_stated_topic_is_not_learned_again(tmp_path, monkeypatch):
    desk = _desk(tmp_path, monkeypatch, stated=["Kestrel Foods"])
    _seed_entity(desk.memory)
    for _ in range(5):
        desk.activity_log.record("assistant", ASK)
    bundle = _ledger_bundle()
    outcome, _ledger, _audit = _run(desk, bundle)
    assert outcome == {"topics": 0}
    assert desk.learned_profile.document()["focusTopics"] == []


def test_removed_topic_never_returns(tmp_path, monkeypatch):
    desk = _desk(tmp_path, monkeypatch)
    _seed_entity(desk.memory)
    for _ in range(5):
        desk.activity_log.record("research", ASK)
    bundle = _ledger_bundle()
    outcome, ledger, _audit = _run(desk, bundle)
    assert outcome == {"topics": 1}
    # The user removes it through the store, exactly as the route does
    # through its one helper; the latch set at learn time stays put.
    assert desk.learned_profile.remove_topic("Kestrel Foods") is True
    for _ in range(5):
        desk.activity_log.record("research", ASK)
    outcome, _ledger, _audit = _run(desk, bundle)
    assert outcome == {"topics": 0}
    assert desk.learned_profile.document()["focusTopics"] == []


class _FailingCaptureLedger:
    """A ledger whose captures cannot be stored (the blob cap gone, a
    sealed store refusing): record raises before anything is written."""

    def __init__(self) -> None:
        self.latched: dict[str, str] = {}

    def latch_value(self, key: str) -> str | None:
        """The latched value, or None when never set."""
        return self.latched.get(key)

    def latch(self, key: str, value: str = "") -> None:
        """Remember the latch, the way the ledger's own latch does."""
        self.latched[key] = value

    def record(self, **_kwargs):
        """Always refuse, the way a required capture that cannot be
        stored refuses the whole record."""
        raise LedgerError("that capture no longer fits")


def test_a_failed_record_leaves_the_topic_learned_and_the_pass_alive(
        tmp_path, monkeypatch):
    """A record that cannot keep its Undo promise must not fail the step
    or undo the learning: the topic stays learned and latched, only its
    Activity entry is lost, and the pass continues."""
    desk = _desk(tmp_path, monkeypatch)
    _seed_entity(desk.memory)
    for _ in range(5):
        desk.activity_log.record("research", ASK)
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False))
    assert server_app.learn_focus_topics(
        desk, _FailingCaptureLedger(), settings) == {"topics": 1}
    assert [t["topic"] for t in desk.learned_profile.document()["focusTopics"]] \
        == ["Kestrel Foods"]


def test_stated_preferences_untouched(tmp_path, monkeypatch):
    desk = _desk(tmp_path, monkeypatch, stated=["Competitor"])
    _seed_entity(desk.memory)
    data = tmp_path / "data"
    before = hashlib.sha256((data / "preferences.json").read_bytes()).hexdigest()
    for _ in range(5):
        desk.activity_log.record("research", ASK)
    bundle = _ledger_bundle()
    _run(desk, bundle)
    desk.learned_profile.remove_topic("Kestrel Foods")
    after = hashlib.sha256((data / "preferences.json").read_bytes()).hexdigest()
    assert after == before
    document = PreferenceStore(data).read()
    assert document["focusTopics"] == ["Competitor"]


def test_activity_rows_carry_ids():
    activity = ActivityLog(sqlite3.connect(":memory:", check_same_thread=False),
                           clock=lambda: 1763650000.0)
    activity.record("research", "first")
    activity.record("assistant", "second")
    rows = activity.entries()
    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["text"] == "first"


def test_the_step_is_registered_after_the_desk_check():
    assert [step.name for step in STEPS] == [
        "deskcheck", "learn-topics", "rank", "update"]
    assert STEPS[1].enabled(SettingsStore(
        sqlite3.connect(":memory:", check_same_thread=False))) is True
    assert STEPS[1].enabled(None) is False
    settings = SettingsStore(sqlite3.connect(":memory:", check_same_thread=False))
    settings.set("learn_topics", False)
    assert STEPS[1].enabled(settings) is False


# -- the surfaces: routes and the settings section --------------------------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    booted = server_harness.Booted()
    try:
        yield booted
    finally:
        booted.close()


@pytest.fixture()
def auth(env):
    return env.exchange()


def test_the_learned_document_route_on_a_fresh_folder(env, auth):
    status, _h, body = env.request("GET", "/api/profile/learned", auth)
    assert status == 200
    doc = json.loads(body)
    assert doc["version"] == 1
    assert doc["entries"] == []
    assert doc["focusTopics"] == []
    assert "updatedAt" in doc


def test_the_learned_settings_section_empty_state(env, auth):
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "What the desk learned about you" in page
    assert ("Nothing learned yet. The desk learns from what you ask it; "
            "nothing here is guessed.") in page
    assert "Save captured facts without asking" in page
    assert "data-setting='learn_topics'" in page


def test_the_settings_section_lists_the_learned_topic_and_removes_it(env, auth):
    server = env.server
    fact = server.memory.add("Kestrel Foods supplies the staff canteen.",
                             source="seed")
    server.memory.resolve_and_link(fact.id, [("Kestrel Foods", "org")])
    for _ in range(5):
        server.activity_log.record("research", ASK)
    assert server_app.learn_focus_topics(
        server, server.ledger, server.settings) == {"topics": 1}

    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "Kestrel Foods" in page
    assert "Learned from 5 asks" in page
    assert "/api/profile/learned/remove" in page

    status, _h, body = env.post_json("/api/profile/learned/remove",
                                     {"topic": "Kestrel Foods"}, auth)
    assert status == 200
    payload = json.loads(body)
    assert payload["removed"] is True
    assert isinstance(payload["entry"], str) and payload["entry"]

    doc = json.loads(env.request("GET", "/api/profile/learned", auth)[2])
    assert doc["focusTopics"] == []
    entry = server.ledger.get(payload["entry"])
    assert entry.action == "profile.removed"
    assert entry.undo_kind == "learned-profile"

    # More asks and another pass never bring it back.
    for _ in range(5):
        server.activity_log.record("research", ASK)
    assert server_app.learn_focus_topics(
        server, server.ledger, server.settings) == {"topics": 0}
    page = env.request("GET", "/settings", auth)[2].decode("utf-8")
    assert "Learned from 5 asks" not in page
