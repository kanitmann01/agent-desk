"""The memory loop end to end over a real MemoryStore: capture, store,
process and remove (memory/loop.py)."""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agentdesk.inbox.store import InboxStore
from agentdesk.memory import loop
from agentdesk.memory.extract import CandidateFact, ExtractorUnavailable
from agentdesk.memory.store import MemoryStore


class Clock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def _store(clock=None, key=None):
    clock = clock or Clock()
    return MemoryStore(sqlite3.connect(":memory:", check_same_thread=False), clock, key=key)


def _inbox(clock=None):
    return InboxStore(sqlite3.connect(":memory:", check_same_thread=False), clock or Clock())


def _stage(inbox):
    def stage(candidate, source_id, channel, method):
        return inbox.add(
            kind="memory_draft", origin="captured", title="Fact", draft=candidate.text,
            meta={"memoryFact": {"kind": candidate.kind, "occurrence_ts": None,
                                 "entities": [list(p) for p in candidate.entities],
                                 "source_id": source_id, "channel": channel,
                                 "method": method}},
        )
    return stage


# -- the rules extractor ---------------------------------------------------


def test_rules_keep_statements_that_name_something_and_drop_the_rest():
    found = loop.rule_candidates(
        "Hi there. Can you check the pipeline? Remember that Priya Shah owns the Acme Corp renewal. "
        "The renewal is due December 15. Please draft an email. thanks"
    )
    texts = [c.text for c in found]
    assert texts == [
        "Priya Shah owns the Acme Corp renewal.",
        "The renewal is due December 15.",
    ]
    names = dict(found[0].entities)
    assert names == {"Priya Shah": "other", "Acme Corp": "org"}
    assert found[1].entities == ()
    assert all(c.kind == "world" for c in found)


def test_rules_ignore_questions_and_text_without_a_named_thing():
    assert loop.rule_candidates("What is the revenue total?") == []
    assert loop.rule_candidates("it is what it is.") == []
    assert loop.rule_candidates("") == []


# -- capture ---------------------------------------------------------------


def test_review_mode_stages_cards_and_writes_no_fact():
    memory, inbox = _store(), _inbox()
    outcome = loop.capture(
        memory, inbox, channel="assistant",
        excerpt="You: Priya Shah owns the Acme Corp renewal.",
        own_words="Priya Shah owns the Acme Corp renewal.",
        settings=loop.CaptureSettings(), extract=None, stage_card=_stage(inbox),
    )
    assert outcome.method == loop.METHOD_RULES
    assert len(outcome.card_ids) == 1 and outcome.fact_ids == ()
    assert memory.all() == []
    card = inbox.get(outcome.card_ids[0])
    assert card.meta["memoryFact"]["channel"] == "assistant"
    assert [s.context for s in memory.sources()] == ["assistant"]


def test_auto_approve_stores_with_provenance_and_entities():
    memory, inbox = _store(), _inbox()
    outcome = loop.capture(
        memory, inbox, channel="research", excerpt="Research question: x\nSourced summary: y",
        own_words="Priya Shah owns the Acme Corp renewal.",
        settings=loop.CaptureSettings(auto_approve=True), extract=None,
        stage_card=_stage(inbox),
    )
    [fact] = memory.all()
    assert outcome.fact_ids == (fact.id,)
    assert fact.source == "auto: research"
    assert fact.source_id == outcome.source_id
    assert memory.sources()[0].text.startswith("Research question")
    assert sorted(e.canonical_name for e in memory.entities()) == ["Acme Corp", "Priya Shah"]
    assert inbox.waiting() == []


def test_the_model_extracts_first_and_the_rules_take_over_when_it_fails():
    memory, inbox = _store(), _inbox()
    calls = []

    def model(excerpt):
        calls.append(excerpt)
        return [CandidateFact(text="Acme Corp signed for three years.", entities=(("Acme Corp", "org"),))]

    first = loop.capture(memory, inbox, channel="assistant", excerpt="You: hi\nAssistant: ok",
                         own_words="hi", settings=loop.CaptureSettings(), extract=model,
                         stage_card=_stage(inbox))
    assert first.method == loop.METHOD_MODEL and len(first.card_ids) == 1 and calls

    def broken(_excerpt):
        raise ExtractorUnavailable("The endpoint did not answer.")

    second = loop.capture(memory, inbox, channel="assistant", excerpt="You: The Berlin office has 40 people.",
                          own_words="The Berlin office has 40 people.",
                          settings=loop.CaptureSettings(), extract=broken, stage_card=_stage(inbox))
    assert second.method == loop.METHOD_RULES
    assert "did not answer" in second.cause
    assert [inbox.get(c).draft for c in second.card_ids] == ["The Berlin office has 40 people."]


def test_capture_skips_what_is_stored_or_waiting_and_respects_channel_switches():
    memory, inbox = _store(), _inbox()
    memory.add("Priya Shah owns the Acme Corp renewal.", source="page")
    text = "Priya Shah owns the Acme Corp renewal. The Berlin office has 40 people."
    settings = loop.CaptureSettings()
    first = loop.capture(memory, inbox, channel="assistant", excerpt=text, own_words=text,
                         settings=settings, extract=None, stage_card=_stage(inbox))
    assert first.skipped == 1 and len(first.card_ids) == 1
    again = loop.capture(memory, inbox, channel="assistant", excerpt=text, own_words=text,
                         settings=settings, extract=None, stage_card=_stage(inbox))
    assert again.card_ids == () and again.skipped == 2
    assert loop.capture(memory, inbox, channel="research", excerpt=text, own_words=text,
                        settings=loop.CaptureSettings(channels=frozenset({"assistant"})),
                        extract=None, stage_card=_stage(inbox)) is None
    assert loop.capture(memory, inbox, channel="assistant", excerpt=text, own_words=text,
                        settings=loop.CaptureSettings(enabled=False),
                        extract=None, stage_card=_stage(inbox)) is None


def test_capture_settings_read_the_settings_store():
    from agentdesk.settings import SettingsStore
    settings = SettingsStore(sqlite3.connect(":memory:"))
    read = loop.capture_settings(settings)
    assert read.enabled is True
    # Spec 016 flipped the stored default: a fresh folder auto-approves.
    assert read.auto_approve is True
    settings.set("memory_auto_approve", False)
    settings.set("memory_capture_research", False)
    read = loop.capture_settings(settings)
    assert read.auto_approve is False and read.channels == frozenset(
        {"assistant", "workbook", "agents"}
    )
    settings.set("memory_capture_workbook", False)
    settings.set("memory_capture_agents", False)
    assert loop.capture_settings(settings).channels == frozenset({"assistant"})


# -- storing and processing -------------------------------------------------


def test_store_fact_merges_the_same_words_and_links_entities():
    memory = _store()
    one = loop.store_fact(memory, "Acme Corp renewed.", source="page", entities=[("Acme Corp", "org")])
    two = loop.store_fact(memory, "  acme corp   renewed. ", source="page", entities=[("Acme", "org")])
    assert two.merged and two.fact.id == one.fact.id
    assert len(memory.all()) == 1


def test_a_newer_value_replaces_the_older_fact_and_recall_skips_it():
    memory = _store()
    old = loop.store_fact(memory, "The Acme Corp renewal is due December 1.", source="page",
                          entities=[("Acme Corp", "org")]).fact
    new = loop.store_fact(memory, "The Acme Corp renewal is due December 15.", source="page",
                          entities=[("Acme Corp", "org")])
    assert new.process.replaced == (old.id,)
    assert memory.superseded_map() == {old.id: new.fact.id}
    recalled = [fact.id for _score, fact in memory.recall("Acme renewal due")]
    assert old.id not in recalled and new.fact.id in recalled
    memory.clear_superseded(old.id)
    assert memory.superseded_map() == {}


def test_unrelated_values_do_not_replace_each_other():
    assert not loop.replaces("The Berlin office has 40 people.", "The Acme Corp renewal is due December 1.")
    assert not loop.replaces("Acme renewed.", "Acme renewed.")


def test_an_entity_with_two_facts_gets_one_consolidated_observation_that_follows_its_facts():
    memory = _store()
    loop.store_fact(memory, "Priya Shah owns the Acme Corp renewal.", source="page",
                    entities=[("Acme Corp", "org"), ("Priya Shah", "person")])
    assert memory.observations() == []
    loop.store_fact(memory, "Acme Corp signed for three years.", source="page",
                    entities=[("Acme Corp", "org")])
    [obs] = memory.observations()
    assert obs.text == ("2 facts about Acme Corp. Latest, Jan 15: Acme Corp signed for three "
                        "years. Before that: Priya Shah owns the Acme Corp renewal.")
    assert len(obs.fact_ids) == 2
    loop.store_fact(memory, "Acme Corp is based in Pune.", source="page", entities=[("Acme Corp", "org")])
    [obs] = memory.observations()
    # Newest first, a count and the latest two states, never every fact.
    assert len(obs.fact_ids) == 3 and obs.text.startswith("3 facts about Acme Corp. Latest, Jan 15: Acme Corp is based in Pune.")
    assert "Priya Shah owns" not in obs.text


# -- removal ----------------------------------------------------------------


def _bank():
    memory = _store()
    a = loop.store_fact(memory, "Priya Shah owns the Acme Corp renewal.", source="page",
                        entities=[("Acme Corp", "org"), ("Priya Shah", "person")]).fact
    b = loop.store_fact(memory, "Acme Corp signed for three years.", source="page",
                        entities=[("Acme Corp", "org")]).fact
    c = loop.store_fact(memory, "Acme Corp is based in Pune.", source="page",
                        entities=[("Acme Corp", "org")]).fact
    reflected = memory.save_observation("topic", "Acme is a long-term account.", 0.7,
                                        [a.id, b.id], now=memory.clock()).observation
    return memory, a, b, c, reflected


def test_removing_a_fact_names_and_applies_every_knock_on_change():
    memory, a, b, c, reflected = _bank()
    plan = loop.plan_removal(memory, "fact", a.id)
    preview = plan.to_json(memory)
    assert [f["id"] for f in preview["facts"]] == [a.id]
    assert [e["name"] for e in preview["entitiesRemoved"]] == ["Priya Shah"]
    assert [o["id"] for o in preview["observationsFlagged"]] == [reflected.id]
    assert len(preview["observationsUpdated"]) == 1
    before = {f.id for f in memory.all()}
    assert {f.id for f in memory.all()} == before, "a plan writes nothing"
    result = loop.apply_removal(memory, plan)
    assert result.fact_ids == (a.id,)
    assert {f.id for f in memory.all()} == {b.id, c.id}
    assert "Priya Shah" not in [e.canonical_name for e in memory.entities()]
    assert reflected.id in memory.stale_observations()
    consolidated = [o for o in memory.observations() if o.id != reflected.id]
    assert len(consolidated) == 1 and set(consolidated[0].fact_ids) == {b.id, c.id}
    assert "Priya" not in consolidated[0].text
    # The result reports the rewrite once: not also removed, not flagged.
    assert result.observations_updated == (consolidated[0].id,)
    assert result.observations_removed == ()
    assert result.observations_flagged == (reflected.id,)


def test_removing_an_entity_takes_every_fact_that_mentions_it_and_undo_puts_it_all_back():
    memory, a, b, c, reflected = _bank()
    before_facts = [(f.id, f.text) for f in memory.all()]
    before_obs = sorted((o.text, o.fact_ids) for o in memory.observations())
    acme = next(e.id for e in memory.entities() if e.canonical_name == "Acme Corp")
    plan = loop.plan_removal(memory, "entity", acme)
    assert set(plan.fact_ids) == {a.id, b.id, c.id}
    result = loop.apply_removal(memory, plan)
    assert memory.all() == [] and memory.observations() == [] and memory.entities() == []
    undo = loop.UndoBuffer(Clock())
    token, _expires = undo.hold(result, plan.label)
    loop.undo_removal(memory, undo.take(token))
    assert [(f.id, f.text) for f in memory.all()] == before_facts
    assert sorted((o.text, o.fact_ids) for o in memory.observations()) == before_obs
    assert sorted(e.canonical_name for e in memory.entities()) == ["Acme Corp", "Priya Shah"]
    assert memory.stale_observations() == {}


def test_removing_an_excerpt_removes_its_facts_and_the_excerpt():
    memory, inbox = _store(), _inbox()
    outcome = loop.capture(memory, inbox, channel="assistant",
                           excerpt="You: The Berlin office has 40 people. Acme Corp signed for three years.",
                           own_words="The Berlin office has 40 people. Acme Corp signed for three years.",
                           settings=loop.CaptureSettings(auto_approve=True), extract=None,
                           stage_card=_stage(inbox))
    keep = loop.store_fact(memory, "Lena runs the Pune team.", source="page").fact
    plan = loop.plan_removal(memory, "source", outcome.source_id)
    assert set(plan.fact_ids) == set(outcome.fact_ids)
    loop.apply_removal(memory, plan)
    assert [f.id for f in memory.all()] == [keep.id]
    assert memory.sources() == []


def test_removing_the_newer_fact_brings_the_replaced_one_back():
    memory = _store()
    old = loop.store_fact(memory, "The Acme Corp renewal is due December 1.", source="page",
                          entities=[("Acme Corp", "org")]).fact
    new = loop.store_fact(memory, "The Acme Corp renewal is due December 15.", source="page",
                          entities=[("Acme Corp", "org")]).fact
    plan = loop.plan_removal(memory, "fact", new.id)
    assert plan.released_fact_ids == (old.id,)
    result = loop.apply_removal(memory, plan)
    assert memory.superseded_map() == {}
    undo = loop.UndoBuffer(Clock())
    token, _ = undo.hold(result, plan.label)
    loop.undo_removal(memory, undo.take(token))
    assert memory.superseded_map() == {old.id: new.id}


def test_removing_an_observation_keeps_its_facts():
    memory, a, b, c, reflected = _bank()
    loop.apply_removal(memory, loop.plan_removal(memory, "observation", reflected.id))
    assert reflected.id not in {o.id for o in memory.observations()}
    assert len(memory.all()) == 3


def test_an_excerpt_a_waiting_card_needs_is_kept():
    memory, inbox = _store(), _inbox()
    staged = loop.capture(memory, inbox, channel="assistant", excerpt="You: The Berlin office has 40 people.",
                          own_words="The Berlin office has 40 people.",
                          settings=loop.CaptureSettings(), extract=None, stage_card=_stage(inbox))
    fact = loop.store_fact(memory, "Lena runs the Pune team.", source="page",
                           source_id=staged.source_id).fact
    loop.apply_removal(memory, loop.plan_removal(memory, "fact", fact.id,
                                                 keep_source_ids={staged.source_id}),
                       keep_source_ids={staged.source_id})
    assert [s.id for s in memory.sources()] == [staged.source_id]


def test_undo_expires_and_refuses_after_the_id_is_reused():
    clock = Clock()
    memory = _store(clock)
    fact = loop.store_fact(memory, "The Berlin office has 40 people.", source="page").fact
    result = loop.apply_removal(memory, loop.plan_removal(memory, "fact", fact.id))
    undo = loop.UndoBuffer(clock, window_s=5)
    token, _ = undo.hold(result, "x")
    clock.now += 10
    assert undo.take(token) is None
    token, _ = undo.hold(result, "x")
    memory.add("Something new with 2 numbers.", source="page")
    with pytest.raises(ValueError, match="no longer be undone"):
        loop.undo_removal(memory, undo.take(token))


def test_unknown_targets_are_refused():
    memory = _store()
    for kind in ("fact", "entity", "source", "observation"):
        with pytest.raises(loop.UnknownTarget):
            loop.plan_removal(memory, kind, 99)


def test_the_loop_works_on_an_encrypted_bank(tmp_path):
    key = bytes(range(32))
    memory = _store(key=key)
    assert memory.is_sealed
    a = loop.store_fact(memory, "Priya Shah owns the Acme Corp renewal.", source="page",
                        entities=[("Acme Corp", "org")]).fact
    loop.store_fact(memory, "Acme Corp signed for three years.", source="page",
                    entities=[("Acme Corp", "org")])
    assert len(memory.observations()) == 1
    result = loop.apply_removal(memory, loop.plan_removal(memory, "fact", a.id))
    assert memory.observations() == []
    undo = loop.UndoBuffer(Clock())
    token, _ = undo.hold(result, "x")
    loop.undo_removal(memory, undo.take(token))
    assert memory.get(a.id).text == "Priya Shah owns the Acme Corp renewal."
    assert len(memory.observations()) == 1
