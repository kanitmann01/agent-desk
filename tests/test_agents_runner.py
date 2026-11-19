"""Unit seams of the agents layer: registry lookup, prompt assembly,
the recall receipt and the tolerant artifact parse.

The runner owns no IO here: the llm callable, the ranked facts and the
excel status are injected, so these tests pin the pure contract the
HTTP suite then drives end to end through the booted server.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.agents import runner
from agentdesk.agents.registry import (
    CONTEXT_NONE,
    CONTEXT_WORKBOOK,
    ROSTER,
    AgentKind,
    find_agent,
)
from agentdesk.llm import LlmUnavailable
from agentdesk.memory.core import Fact


class ScriptLlm:
    """Records every prompt and answers with the given text, or raises."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.prompts = []
        self.reply = reply
        self.error = error

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


def _fact(text: str, fact_id: int = 1) -> Fact:
    return Fact(id=fact_id, text=text, source="page", created_ts=1.0)


def _ranked(*texts: str) -> list:
    return [(1.0 - index * 0.1, _fact(text, index + 1)) for index, text in enumerate(texts)]


# -- the registry ---------------------------------------------------------


def test_find_agent_returns_the_presentation_kind_by_id():
    agent = find_agent("presentation")
    assert agent is not None
    assert agent.name == "Presentation"
    assert agent.context == CONTEXT_NONE
    assert agent.artifact_kind == "slides"


def test_find_agent_returns_the_worksheet_brief_kind_by_id():
    agent = find_agent("worksheet-brief")
    assert agent is not None
    assert agent.name == "Worksheet brief"
    assert agent.context == CONTEXT_WORKBOOK
    assert agent.artifact_kind == "outline"


def test_find_agent_refuses_an_unknown_id():
    assert find_agent("worksheet") is None
    assert find_agent("") is None


def test_the_roster_carries_unique_ids():
    ids = [agent.id for agent in ROSTER]
    assert len(ids) == len(set(ids))
    assert "presentation" in ids
    assert "worksheet-brief" in ids


# -- prompt assembly ------------------------------------------------------


def test_the_prompt_places_the_facts_block_before_instructions_and_brief():
    agent = find_agent("presentation")
    prompt = runner.build_agent_prompt(
        agent, "the Q3 review", facts_block="Known facts about the user:\n- revenue is 220"
    )
    block_at = prompt.index("Known facts about the user")
    instructions_at = prompt.index(agent.instructions)
    brief_at = prompt.index("the Q3 review")
    assert block_at < instructions_at < brief_at


def test_the_prompt_without_facts_carries_no_block():
    agent = find_agent("presentation")
    prompt = runner.build_agent_prompt(agent, "the Q3 review")
    assert "Known facts about the user" not in prompt
    assert "the Q3 review" in prompt


def test_the_prompt_bounds_come_from_the_block_whole_facts_only():
    # Seven ranked facts: the block keeps at most five, and only whole
    # facts, because the bounds live in memory/service once.
    agent = find_agent("presentation")
    ranked = _ranked(*[f"revenue fact number {i}" for i in range(7)])
    block, receipt = runner.recall_block(ranked)
    lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(lines) <= 5
    assert len(receipt) == len(lines)
    prompt = runner.build_agent_prompt(agent, "revenue", facts_block=block)
    carried = {
        ln for ln in prompt.splitlines() if ln.startswith("- ")
    }
    assert carried == set(lines)


def test_the_receipt_names_exactly_the_facts_that_fit():
    # Three 126-character facts fit inside the 500-character payload; a
    # fourth is dropped whole, so the receipt and the block agree.
    long_fact = "revenue " * 15  # 120 characters with its trailing space
    ranked = _ranked(*[f"{long_fact}mark {i}" for i in range(5)])
    block, receipt = runner.recall_block(ranked)
    lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(lines) == 3
    assert [row["id"] for row in receipt] == [1, 2, 3]
    assert all(row["text"].startswith("revenue") for row in receipt)


def test_no_recall_means_no_block_and_an_empty_receipt():
    block, receipt = runner.recall_block([])
    assert block == ""
    assert receipt == []


def test_a_workbook_kind_gains_the_excel_context_lines():
    worksheet = AgentKind(
        id="worksheet",
        name="Worksheet",
        blurb="A briefing grounded in the watched workbook.",
        artifact_kind="briefing",
        instructions="Write a short briefing.",
        context=CONTEXT_WORKBOOK,
    )
    excel_status = {
        "configured": True,
        "path": "C:/sales/q3.xlsx",
        "state": "watching",
        "delta": {"added": [{"region": "EMEA", "value": 10}], "removed": []},
    }
    prompt = runner.build_agent_prompt(
        worksheet, "brief me", context_block=runner.workbook_context(worksheet, excel_status)
    )
    assert "Sales workbook watched: q3.xlsx" in prompt
    assert "brief me" in prompt


def test_a_none_kind_carries_no_widget_context():
    agent = find_agent("presentation")
    assert runner.workbook_context(agent, {"configured": True}) == ""


def test_the_worksheet_brief_prompt_carries_workbook_lines_and_the_facts_block():
    agent = find_agent("worksheet-brief")
    excel_status = {
        "configured": True,
        "path": "C:/sales/q3.xlsx",
        "state": "watching",
        "delta": {"added": [{"region": "EMEA", "value": 10}], "removed": []},
    }
    facts_block, _receipt = runner.recall_block(
        _ranked("the watched workbook tracks EMEA revenue")
    )
    prompt = runner.build_agent_prompt(
        agent, "brief me",
        context_block=runner.workbook_context(agent, excel_status),
        facts_block=facts_block,
    )
    context_at = prompt.index("Sales workbook watched: q3.xlsx")
    facts_at = prompt.index("Known facts about the user")
    instructions_at = prompt.index(agent.instructions)
    brief_at = prompt.index("brief me")
    assert context_at < facts_at < instructions_at < brief_at
    assert "- the watched workbook tracks EMEA revenue" in prompt


def test_the_worksheet_brief_context_says_the_empty_honestly():
    agent = find_agent("worksheet-brief")
    prompt = runner.build_agent_prompt(
        agent, "brief me",
        context_block=runner.workbook_context(
            agent, {"configured": False, "state": "not_configured"}
        ),
    )
    assert "no sources connected yet" in prompt
    assert "Sales workbook watched" not in prompt


# -- the tolerant artifact parse -------------------------------------------


def test_parse_artifact_reads_the_slides_json():
    reply = json.dumps(
        {"title": "Q3 Review", "slides": [{"title": "Revenue", "bullets": ["revenue is 220"]}]}
    )
    artifact = runner.parse_artifact(reply, find_agent("presentation"))
    assert artifact["kind"] == "slides"
    assert artifact["title"] == "Q3 Review"
    assert artifact["slides"][0]["bullets"] == ["revenue is 220"]


def test_parse_artifact_tolerates_a_fenced_reply():
    reply = "```json\n" + json.dumps({"title": "Q3", "slides": []}) + "\n```"
    artifact = runner.parse_artifact(reply, find_agent("presentation"))
    assert artifact["kind"] == "slides"
    assert artifact["title"] == "Q3"


def test_parse_artifact_falls_back_to_a_text_outline():
    artifact = runner.parse_artifact(
        "1. Revenue\n- revenue is 220", find_agent("presentation")
    )
    assert artifact["kind"] == "outline"
    assert "revenue is 220" in artifact["text"]


def test_parse_artifact_names_an_empty_reply_honestly():
    artifact = runner.parse_artifact("   ", find_agent("presentation"))
    assert artifact["kind"] == "outline"
    assert artifact["text"]


# -- the run --------------------------------------------------------------


def test_run_agent_calls_the_llm_once_and_returns_the_parsed_artifact():
    llm = ScriptLlm(reply=json.dumps({"title": "Q3", "slides": []}))
    result = runner.run_agent(
        find_agent("presentation"), "the Q3 review", llm, ranked_facts=_ranked("revenue is 220")
    )
    assert len(llm.prompts) == 1
    assert "- revenue is 220" in llm.prompts[0]
    assert result.status == runner.STATUS_OK
    assert result.artifact["kind"] == "slides"
    assert [row["text"] for row in result.facts] == ["revenue is 220"]


def test_run_agent_degrades_with_the_pinned_cause():
    llm = ScriptLlm(error=LlmUnavailable("no corporate endpoint configured"))
    result = runner.run_agent(find_agent("presentation"), "brief", llm)
    assert result.status == runner.STATUS_DEGRADED
    assert result.cause == "no corporate endpoint configured"
    assert result.artifact is None


def test_run_agent_gives_a_workbook_kind_its_live_status_lines():
    agent = find_agent("worksheet-brief")
    llm = ScriptLlm(reply="The EMEA rows are up; nothing else moved.")
    result = runner.run_agent(
        agent, "brief me", llm,
        excel_status={
            "configured": True,
            "path": "C:/sales/q3.xlsx",
            "state": "watching",
            "delta": {"added": [{"region": "EMEA", "value": 10}], "removed": []},
        },
    )
    assert result.status == runner.STATUS_OK
    assert "Sales workbook watched: q3.xlsx" in llm.prompts[0]
    assert result.artifact["kind"] == "outline"
    assert result.artifact["text"] == "The EMEA rows are up; nothing else moved."


def test_run_agent_degrades_with_the_standing_line_on_unexpected_errors():
    llm = ScriptLlm(error=RuntimeError("boom"))
    result = runner.run_agent(find_agent("presentation"), "brief", llm)
    assert result.status == runner.STATUS_DEGRADED
    assert result.cause == runner.DEGRADED_CAUSE
    assert result.reply == ""


def test_the_brief_bound_is_a_few_hundred_characters():
    assert runner.BRIEF_MAX_CHARS == 400
