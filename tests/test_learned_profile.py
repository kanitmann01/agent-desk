"""The learned profile store and its reads (spec 016 ticket 08).

`profile.learned.json` holds what the desk can honestly say it learned
about you: focus topics taken from repeated asks (this ticket) and
profile lines from reviewed activity (ticket 09). These tests pin the
store's contract: the empty document a fresh folder answers, the
character budget joined with the Hermes delimiter, the topic limits
shared with the stated preferences, the merged read, and the digest
prompt that states the learned lines after the stated ones.
"""

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.insight import context as insight_context
from agentdesk.insight import digest
from agentdesk.insight.preferences import MAX_TOPICS, MAX_TOPIC_CHARS
from agentdesk.memory import profile

NOW = 1763650000.0


def test_the_topic_limits_match_the_stated_store():
    # The constants are duplicated (insight/__init__ imports this
    # module's readers, so memory importing back would close a circle);
    # the pin keeps them from drifting, like the embeddings model pair.
    from agentdesk.insight import preferences as stated_preferences
    from agentdesk.memory import profile as learned

    assert learned.MAX_TOPICS == stated_preferences.MAX_TOPICS
    assert learned.MAX_TOPIC_CHARS == stated_preferences.MAX_TOPIC_CHARS


@pytest.fixture()
def store(tmp_path):
    """A store over a file that does not exist yet, on a frozen clock."""
    return profile.LearnedProfileStore(
        tmp_path / "profile.learned.json", clock=lambda: NOW)


# -- the document ----------------------------------------------------------


def test_a_missing_file_reads_as_the_empty_document(store):
    doc = store.document()
    assert doc["version"] == 1
    assert doc["entries"] == []
    assert doc["focusTopics"] == []
    assert isinstance(doc["updatedAt"], float)


def test_add_topic_records_the_ask_count(store):
    assert store.add_topic("Kestrel Foods", 5) is True
    [topic] = store.document()["focusTopics"]
    assert topic == {"topic": "Kestrel Foods", "learnedFrom": {"asks": 5},
                     "ts": NOW}


def test_add_topic_refuses_duplicates_case_insensitively(store):
    store.add_topic("Kestrel Foods", 5)
    assert store.add_topic("kestrel foods", 3) is False
    assert len(store.document()["focusTopics"]) == 1


def test_add_topic_refuses_a_too_long_topic(store):
    assert store.add_topic("x" * (MAX_TOPIC_CHARS + 1), 5) is False
    assert store.add_topic("", 5) is False


def test_add_topic_stops_at_the_shared_topic_cap(store):
    for number in range(MAX_TOPICS):
        assert store.add_topic(f"topic {number}", 5) is True
    assert store.add_topic("one more", 5) is False


def test_remove_topic_returns_whether_it_was_there(store):
    store.add_topic("Kestrel Foods", 5)
    assert store.remove_topic("kestrel foods") is True
    assert store.document()["focusTopics"] == []
    assert store.remove_topic("Kestrel Foods") is False


def test_raw_and_restore_round_trip_the_whole_document(store):
    store.add_topic("Kestrel Foods", 5)
    raw = store.raw()
    assert isinstance(raw, bytes)
    twin = profile.LearnedProfileStore(store.path.parent / "twin.json")
    twin.restore(raw)
    assert twin.document() == store.document()


# -- the entry budget (Hermes user_char_limit and ENTRY_DELIMITER) ---------


def test_add_entry_returns_the_stored_line(store):
    entry = store.add_entry("Owns the Kestrel Foods account.",
                            {"activity": [881]}, "review")
    assert entry["id"].startswith("p-")
    assert entry["text"] == "Owns the Kestrel Foods account."
    assert entry["learnedFrom"] == {"activity": [881]}
    assert entry["by"] == "review"
    assert store.document()["entries"] == [entry]


def test_add_entry_refused_over_budget_names_the_entries(store):
    with pytest.raises(profile.OverBudget) as caught:
        store.add_entry("word " * 400, {"activity": [1]}, "review")
    assert caught.value.entries == []
    assert store.document()["entries"] == []


def test_the_budget_counts_the_delimiter_joined_texts(store):
    store.add_entry("a" * 700, {"activity": [1]}, "review")
    # 700 + 3 (the "\n§\n" delimiter) + 700 lands over BUDGET_CHARS.
    with pytest.raises(profile.OverBudget):
        store.add_entry("b" * 700, {"activity": [2]}, "review")
    # Filling the budget exactly is allowed: 700 + 3 + 672 = 1375.
    entry = store.add_entry("c" * (profile.BUDGET_CHARS - 700 - 3),
                            {"activity": [3]}, "review")
    assert len(entry["text"]) == profile.BUDGET_CHARS - 703
    assert profile.BUDGET_CHARS == 1375


def test_patch_entry_replaces_text_and_provenance(store):
    entry = store.add_entry("short text", {"activity": [1]}, "review")
    patched = store.patch_entry(entry["id"], "longer text now",
                                {"activity": [1, 2]})
    assert patched["text"] == "longer text now"
    assert patched["learnedFrom"] == {"activity": [1, 2]}
    assert store.document()["entries"] == [patched]


def test_patch_entry_refused_when_it_breaks_the_budget(store):
    entry = store.add_entry("a" * 1300, {"activity": [1]}, "review")
    with pytest.raises(profile.OverBudget):
        store.patch_entry(entry["id"], "b" * 1400, {"activity": [1]})


def test_remove_entry_and_unknown_ids(store):
    entry = store.add_entry("a line", {"activity": [1]}, "review")
    assert store.remove_entry(entry["id"]) is True
    assert store.document()["entries"] == []
    assert store.remove_entry(entry["id"]) is False
    with pytest.raises(LookupError):
        store.patch_entry("p-none", "text", {"activity": [1]})


def test_concurrent_add_and_remove_leaves_a_valid_document(tmp_path):
    """The loop thread learns while a request thread removes; the lock
    across each read-mutate-write keeps a removal landing between one
    writer's read and its save from being silently overwritten, and the
    document ends on one of exactly two valid states."""
    store = profile.LearnedProfileStore(
        tmp_path / "profile.learned.json", clock=lambda: NOW)
    store.add_topic("Kestrel Foods", 5)
    errors: list[Exception] = []

    def adder() -> None:
        try:
            for _ in range(60):
                store.add_topic("Kestrel Foods", 5)
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    def remover() -> None:
        try:
            for _ in range(60):
                store.remove_topic("kestrel foods")
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=adder), threading.Thread(target=remover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    topics = store.document()["focusTopics"]
    # One of exactly two valid endings: the removal won, or the last add
    # re-learned the topic. Nothing else may be in the file.
    assert topics in ([], [{"topic": "Kestrel Foods",
                            "learnedFrom": {"asks": 5}, "ts": NOW}])


# -- the reads the rest of the desk uses -----------------------------------


def test_merged_topics_state_first_then_learned_deduped():
    stated = ["Kestrel Foods", "Acme"]
    learned = [{"topic": "kestrel foods"}, {"topic": "Halvorsen Freight"}]
    assert profile.merged_topics(stated, learned) == [
        "Kestrel Foods", "Acme", "Halvorsen Freight"]


def test_merged_topics_cap_at_the_stated_store_limit():
    stated = [f"topic {number}" for number in range(MAX_TOPICS)]
    learned = [{"topic": "extra"}]
    assert profile.merged_topics(stated, learned) == stated


def test_learned_lines_are_the_entry_texts(store):
    store.add_entry("Owns the Kestrel Foods account.", {"activity": [1]}, "review")
    store.add_entry("Prefers short summaries.", {"activity": [2]}, "review")
    assert profile.learned_lines(store.document()) == [
        "Owns the Kestrel Foods account.", "Prefers short summaries."]


# -- the digest: merged topics, learned lines after the stated ones --------

THREAD = {
    "subject": "Kestrel Foods weekly order",
    "sender": "orders@kestrel.example",
    "last": "Attaching this week's order sheet.",
}


def test_digest_uses_merged_topics_and_learned_lines():
    prompts: list[str] = []
    preferences = {
        # What build_insight_context produces: the stated topics first,
        # then the learned ones, deduped; plus the learned lines.
        "focusTopics": ["Acme", "Kestrel Foods"],
        "learnedLines": ["Owns the Kestrel Foods account."],
    }
    digest.compose_draft(THREAD, preferences, complete=prompts.append)
    prompt = prompts[0]
    assert "Focus topics: Acme, Kestrel Foods." in prompt
    assert "What the desk learned about you:" in prompt
    assert "Owns the Kestrel Foods account." in prompt
    assert prompt.index("Focus topics:") < prompt.index(
        "What the desk learned about you:")


def test_digest_without_learned_lines_keeps_its_old_shape():
    prompts: list[str] = []
    digest.compose_draft(THREAD, {"focusTopics": ["Acme"]},
                         complete=prompts.append)
    prompt = prompts[0]
    assert "Focus topics: Acme." in prompt
    assert "What the desk learned about you:" not in prompt


def test_build_context_merges_the_learned_document(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESK_DATA", str(tmp_path / "data"))
    store = profile.LearnedProfileStore(tmp_path / "data" / "profile.learned.json")
    store.add_topic("Kestrel Foods", 5)
    store.add_entry("Owns the Kestrel Foods account.", {"activity": [1]}, "review")

    class Desk:
        """The one attribute the context builder reads."""
        learned_profile = store

    built = insight_context.build_context(Desk(), {"focusTopics": ["Kestrel Foods"]})
    assert built.preferences["focusTopics"] == ["Kestrel Foods"]
    assert built.preferences["learnedLines"] == [
        "Owns the Kestrel Foods account."]


def test_build_context_reads_nothing_without_a_store():
    built = insight_context.build_context(object(), {"focusTopics": ["Acme"]})
    assert built.preferences["focusTopics"] == ["Acme"]
    assert built.preferences.get("learnedLines") is None
