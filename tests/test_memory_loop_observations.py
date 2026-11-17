"""Observations written per entity (by the endpoint or the rules), the
removal preview's after-text, the workbook channel, and the inbox's
thread safety."""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentdesk.excel.core import Delta  # noqa: E402
from agentdesk.inbox.store import InboxStore  # noqa: E402
from agentdesk.memory import loop  # noqa: E402
from agentdesk.memory.store import MemoryStore  # noqa: E402


class Clock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def _store():
    return MemoryStore(sqlite3.connect(":memory:", check_same_thread=False), Clock())


def _inbox():
    return InboxStore(sqlite3.connect(":memory:", check_same_thread=False), Clock())


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


class StubSummaryLlm:
    """An endpoint that answers the summary prompt with one sentence that
    cites the first fact id it was shown."""

    def __init__(self, fail: bool = False) -> None:
        self.prompts: list[str] = []
        self.fail = fail

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise OSError("connection refused")
        name = prompt.split("observation about ", 1)[1].split(" in a work", 1)[0]
        first_id = int(prompt.split("Facts (id | date | text):\n", 1)[1].split(" |", 1)[0])
        return json.dumps({"text": f"{name} is current as of fact {first_id}.",
                           "sourceFactIds": [first_id, 9999]})


def _acme(memory):
    a = loop.store_fact(memory, "Priya Shah owns the Acme Corp renewal.", source="page",
                        entities=[("Acme Corp", "org"), ("Priya Shah", "person")]).fact
    b = loop.store_fact(memory, "Acme Corp signed for three years.", source="page",
                        entities=[("Acme Corp", "org")]).fact
    c = loop.store_fact(memory, "Acme Corp is based in Pune.", source="page",
                        entities=[("Acme Corp", "org")]).fact
    return a, b, c


def _entity_id(memory, name):
    return next(e.id for e in memory.entities() if e.canonical_name == name)


# -- the deterministic summary ---------------------------------------------


def test_rule_summary_is_a_count_and_the_latest_state_newest_first():
    memory = _store()
    facts = [loop.store_fact(memory, f"Halvorsen Freight moved to stage {n}.", source="page",
                             entities=[("Halvorsen Freight", "org")]).fact for n in range(1, 8)]
    summary = loop.rule_summary("Halvorsen Freight", facts)
    assert summary.text.startswith("7 facts about Halvorsen Freight. Latest, Jan 15: "
                                   "Halvorsen Freight moved to stage 7.")
    assert "stage 6" in summary.text and "stage 1" not in summary.text
    assert ";" not in summary.text and len(summary.text) <= loop.MAX_SUMMARY_CHARS
    assert summary.method == loop.METHOD_RULES
    assert summary.fact_ids[0] == facts[-1].id and len(summary.fact_ids) == loop.MAX_CONSOLIDATED_FACTS


# -- the model-written observation -----------------------------------------


def test_the_endpoint_writes_one_short_observation_per_entity_citing_its_facts():
    memory = _store()
    a, b, c = _acme(memory)
    stub = StubSummaryLlm()
    outcome = loop.reconcile_observations(memory, summarize=loop.EndpointSummarizer(stub))
    [obs] = memory.observations()
    assert obs.text == f"Acme Corp is current as of fact {c.id}."
    assert obs.fact_ids == (c.id,)  # an id it was not shown (9999) is dropped
    assert memory.observation_marks()[obs.id] == (loop.METHOD_MODEL, frozenset({a.id, b.id, c.id}))
    assert outcome.model_written == 1 and len(stub.prompts) == 1
    assert "Acme Corp is based in Pune." in stub.prompts[0]

    # Nothing changed: the next pass asks nothing.
    loop.reconcile_observations(memory, summarize=loop.EndpointSummarizer(stub))
    assert len(stub.prompts) == 1

    # A new fact rebuilds it: the rules first (synchronously), then the model.
    d = loop.store_fact(memory, "Acme Corp renewed early.", source="page",
                        entities=[("Acme Corp", "org")]).fact
    [obs] = memory.observations()
    assert memory.observation_marks()[obs.id][0] == loop.METHOD_RULES
    loop.reconcile_observations(memory, summarize=loop.EndpointSummarizer(stub))
    [obs] = memory.observations()
    assert obs.text == f"Acme Corp is current as of fact {d.id}." and len(stub.prompts) == 2


def test_an_endpoint_failure_leaves_the_rules_text_and_is_reported():
    memory = _store()
    _acme(memory)
    outcome = loop.reconcile_observations(memory, summarize=loop.EndpointSummarizer(StubSummaryLlm(fail=True)))
    [obs] = memory.observations()
    assert obs.text.startswith("3 facts about Acme Corp.")
    assert outcome.model_written == 0 and "connection refused" in outcome.model_failure


def test_an_overlong_or_empty_model_reply_is_refused():
    memory = _store()
    _a, _b, c = _acme(memory)
    for reply in ('{"text": ""}', json.dumps({"text": "x" * 400}), "not json"):
        summarizer = loop.EndpointSummarizer(lambda _p, reply=reply: reply)
        try:
            summarizer("Acme Corp", [c])
        except loop.SummaryFailed:
            continue
        raise AssertionError(f"accepted {reply!r}")


def test_two_entities_with_the_same_facts_share_one_observation():
    memory = _store()
    loop.store_fact(memory, "Jordan Lee moved the Halvorsen Freight renewal to legal.", source="page",
                    entities=[("Jordan Lee", "person"), ("Halvorsen Freight", "org")])
    loop.store_fact(memory, "Jordan Lee closed the Halvorsen Freight renewal.", source="page",
                    entities=[("Jordan Lee", "person"), ("Halvorsen Freight", "org")])
    [obs] = memory.observations()
    loop.store_fact(memory, "Halvorsen Freight is based in Oslo.", source="page",
                    entities=[("Halvorsen Freight", "org")])
    # Now the sets differ: each entity gets its own.
    texts = sorted(o.text for o in memory.observations())
    assert len(texts) == 2 and texts[0].startswith("2 facts about Jordan Lee")


# -- the removal preview ---------------------------------------------------


def test_the_preview_shows_each_observation_after_the_removal():
    memory = _store()
    a, b, c = _acme(memory)
    plan = loop.plan_removal(memory, "fact", c.id, summarize=loop.EndpointSummarizer(StubSummaryLlm()))
    preview = plan.to_json(memory)
    [row] = preview["observationsUpdated"]
    assert row["text"].startswith("3 facts about Acme Corp")
    assert row["after"] == f"Acme Corp is current as of fact {b.id}." and row["afterMethod"] == "model"
    # The removal writes exactly what was previewed.
    loop.apply_removal(memory, plan, planned=plan.planned())
    [obs] = memory.observations()
    assert obs.text == row["after"]


def test_the_preview_falls_back_to_the_rules_text_when_the_endpoint_fails():
    memory = _store()
    _a, _b, c = _acme(memory)
    plan = loop.plan_removal(memory, "fact", c.id,
                             summarize=loop.EndpointSummarizer(StubSummaryLlm(fail=True)))
    [row] = plan.to_json(memory)["observationsUpdated"]
    assert row["after"].startswith("2 facts about Acme Corp") and row["afterMethod"] == "rules"


def test_removing_an_entity_does_not_list_it_among_the_entities_forgotten():
    memory = _store()
    _acme(memory)
    acme = _entity_id(memory, "Acme Corp")
    preview = loop.plan_removal(memory, "entity", acme).to_json(memory)
    names = [e["name"] for e in preview["entitiesRemoved"] + preview["entitiesUpdated"]]
    assert "Acme Corp" not in names and "Priya Shah" in names
    assert preview["observationsRemoved"] and not preview["observationsUpdated"]


def test_preview_cache_hands_back_a_plan_once_and_expires():
    clock = Clock()
    cache = loop.PreviewCache(clock, ttl_s=5)
    memory = _store()
    _a, _b, c = _acme(memory)
    plan = loop.plan_removal(memory, "fact", c.id)
    cache.put(plan)
    assert cache.take("fact", c.id) == plan.planned()
    assert cache.take("fact", c.id) is None
    cache.put(plan)
    clock.now += 10
    assert cache.take("fact", c.id) is None


# -- the workbook channel --------------------------------------------------


HEADER = ["Deal", "Stage", "Owner"]


def test_workbook_rows_become_facts_written_from_the_cells():
    delta = Delta(
        added=[["Halvorsen Freight", "Legal", "Jordan Lee"], ["Brightwater", "Intro", "Priya Shah"]],
        removed=[["Halvorsen Freight", "Proposal", "Jordan Lee"], ["Old Mill", "Lost", ""]],
    )
    found = loop.workbook_candidates(HEADER, delta.added, delta.removed)
    assert [c.text for c in found] == [
        "Halvorsen Freight: Stage changed from Proposal to Legal.",
        "Brightwater was added to the tracker with Stage Intro, Owner Priya Shah.",
        "Old Mill was removed from the tracker.",
    ]
    assert found[0].entities == (("Halvorsen Freight", "org"),) or found[0].entities[0][0] == "Halvorsen Freight"


def test_workbook_capture_stages_cards_and_does_not_repropose_rejected_ones():
    memory, inbox = _store(), _inbox()
    candidates = loop.workbook_candidates(
        HEADER, [["Halvorsen Freight", "Legal", "Jordan Lee"]], [["Halvorsen Freight", "Proposal", "Jordan Lee"]])
    settings = loop.CaptureSettings()

    def run():
        return loop.capture(memory, inbox, channel="workbook",
                            excerpt=loop.workbook_excerpt("tracker.xlsx", candidates), own_words="",
                            settings=settings, extract=None, stage_card=_stage(inbox),
                            speaker="Workbook", candidates=candidates)

    outcome = run()
    assert outcome is not None and len(outcome.card_ids) == 1 and outcome.method == "rules"
    [card] = inbox.waiting()
    assert card.meta["memoryFact"]["channel"] == "workbook"
    inbox.dismiss(card.id)
    # The watch reports the same 24-hour delta on the next poll.
    again = run()
    assert again is None or not again.card_ids
    off = loop.CaptureSettings(channels=frozenset({"assistant"}))
    assert not off.captures("workbook")


# -- the inbox under concurrent writers ------------------------------------


def test_the_inbox_serializes_every_writer_on_one_connection():
    inbox = InboxStore(sqlite3.connect(":memory:", check_same_thread=False), Clock())
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for i in range(40):
                card = inbox.add(kind="memory_draft", origin="captured", title=f"t{n}-{i}",
                                 draft=f"draft {n} {i}", meta={"n": n})
                inbox.waiting()
                if i % 3 == 0:
                    inbox.dismiss(card.id)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(inbox.waiting()) + len(inbox.dismissed()) == 8 * 40
