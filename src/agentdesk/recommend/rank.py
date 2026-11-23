"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, cron/scripts/classify_items.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

Model ranking of waiting recommendations (spec 016 §6.3).

One pass sends the waiting recommendation titles, the facts they cite and
the learned profile lines to the company endpoint. A reply above the
threshold replaces the card's why line; a reply below it snoozes the card
until tomorrow morning. The step never writes the reply, the prompt or any
fact text to the audit trail: only the model name and the request size.

The rules and the builder stay deterministic. This module is the one
place where a recommendation's wording may come from the endpoint, so
every reply is parsed against the cards that were actually sent and the
strict threat scan before it can change a card.
"""

import datetime
import json
from typing import Callable

from agentdesk.assistant import audit as audit_store
from agentdesk.llm import LlmUnavailable, effective_llm_config, settings_chat
from agentdesk.memory.profile import learned_lines as profile_learned_lines
from agentdesk.safety import first_threat_message

PROMPT = """You rank decisions for a small business desk. Score each candidate from 0 to 10 for urgency and relevance to the user right now. Return only a JSON array of objects with "id", "score" (an integer from 0 to 10), and "why" (at most 140 characters, plain words, no emoji, no threats). Do not add prose, code fences or markdown.
"""

MAX_WHY = 140
STEP_NAME = "rank"


def rank_enabled(settings) -> bool:
    """The rank step runs only when all three switches agree."""
    return bool(
        settings.get("recommendations")
        and settings.get("recommend_model_rank")
        and settings.get("endpoint_enabled")
    )


def build_input(cards, memory, learned_lines, now) -> dict:
    """The stable prompt payload: one candidate per waiting card.

    Only stable fields are hashed for the unchanged-input latch, so a
    ranking that rewrites a card's why line does not make the next pass
    look like a different input.
    """
    facts = {fact.id: fact.text for fact in memory.all()}
    candidates = []
    for card in sorted(cards, key=lambda row: row.id):
        recommendation = (card.meta or {}).get("recommendation") or {}
        cited = [
            facts[fact_id]
            for fact_id in recommendation.get("cites") or []
            if fact_id in facts
        ]
        due = recommendation.get("dueTs")
        days_until = None
        if isinstance(due, (int, float)):
            due_date = datetime.datetime.fromtimestamp(due).astimezone().date()
            days_until = (due_date - now.date()).days
        candidates.append(
            {
                "id": card.id,
                "title": card.title,
                "facts": cited,
                "daysUntil": days_until,
            }
        )
    return {"candidates": candidates, "learned": list(learned_lines)}


def render_prompt(payload: dict) -> str:
    """The endpoint prompt, with the payload serialized deterministically."""
    return PROMPT + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_reply(text: str, ids) -> list[dict]:
    """Keep only grounded, bounded, threat-free scores for the sent ids."""
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    allowed = set(ids)
    kept = []
    seen = set()
    for item in decoded:
        if not isinstance(item, dict):
            continue
        card_id = item.get("id")
        if not isinstance(card_id, str) or card_id not in allowed or card_id in seen:
            continue
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        score = max(0, min(10, int(score)))
        why = item.get("why")
        if not isinstance(why, str):
            continue
        why = why.strip()
        if not why or len(why) > MAX_WHY:
            continue
        if first_threat_message(why, "strict") is not None:
            continue
        kept.append({"id": card_id, "score": score, "why": why})
        seen.add(card_id)
    return kept


def tomorrow_8am_ts(now) -> float:
    """Tomorrow at 08:00 in the pass's own timezone, as an epoch stamp."""
    next_day = (now + datetime.timedelta(days=1)).date()
    return datetime.datetime.combine(
        next_day, datetime.time(8, 0), tzinfo=now.tzinfo
    ).timestamp()


def apply_scores(inbox, ledger, scored, threshold: int, tomorrow_8am: float) -> dict:
    """Show a card with a model why, or snooze it until tomorrow morning."""
    del ledger  # the ranking is display-only; the card itself is the record
    shown = 0
    snoozed = 0
    for row in scored:
        try:
            card = inbox.get(row["id"])
        except Exception:  # noqa: BLE001 - a card may be decided mid-pass
            continue
        if row["score"] >= threshold:
            meta = dict(card.meta or {})
            recommendation = dict(meta.get("recommendation") or {})
            recommendation["score"] = row["score"]
            recommendation["whySource"] = "model"
            meta["recommendation"] = recommendation
            inbox.update_meta(card.id, meta, origin=row["why"])
            shown += 1
        else:
            inbox.snooze(card.id, tomorrow_8am)
            snoozed += 1
    return {"shown": shown, "snoozed": snoozed}


def run_rank(server, ctx, chat: Callable[[str], str] | None = None) -> dict:
    """One ranking pass over the visible waiting recommendations."""
    inbox = getattr(server, "inbox", None)
    settings = getattr(server, "settings", None)
    memory = getattr(server, "memory", None)
    if inbox is None or settings is None or memory is None:
        return {"skipped": "The desk has no recommendations to rank."}
    cards = [
        card
        for card in inbox.waiting()
        if (card.meta or {}).get("recommendation")
    ]
    payload = build_input(cards, memory, _learned_lines(server), ctx.now)
    if not cards:
        # Remember the empty pass, so the card that wakes from a snooze
        # changes the payload instead of being skipped as unchanged.
        ctx.remember_input(STEP_NAME, payload)
        return {"ranked": 0}
    if ctx.input_unchanged(STEP_NAME, payload):
        return {"skipped": "unchanged"}
    prompt = render_prompt(payload)
    base, _key, model = effective_llm_config(settings)
    call = chat or settings_chat(settings)
    try:
        reply = call(prompt)
    except LlmUnavailable as exc:
        _audit(server, base, model, prompt, "error", str(exc))
        return {"skipped": str(exc)}
    except Exception as exc:  # noqa: BLE001 - one step must not stop the pass
        cause = f"{type(exc).__name__}: {exc}"
        _audit(server, base, model, prompt, "error", cause)
        return {"skipped": cause}

    try:
        decoded = json.loads(reply)
        if not isinstance(decoded, list):
            raise ValueError("The endpoint reply was not a JSON array.")
    except (TypeError, ValueError) as exc:
        cause = str(exc) or "The endpoint reply was not JSON."
        _audit(server, base, model, prompt, "error", cause)
        return {"skipped": cause}

    scored = parse_reply(reply, {card.id for card in cards})
    if not scored:
        # A reply with no usable score changed nothing. Remembering the
        # input here would latch every later pass as unchanged.
        cause = "The endpoint reply had no usable scores."
        _audit(server, base, model, prompt, "error", cause)
        return {"skipped": cause}
    _audit(server, base, model, prompt, "ok", "")
    counts = apply_scores(
        inbox,
        getattr(server, "ledger", None),
        scored,
        int(settings.get("recommend_threshold") or 7),
        tomorrow_8am_ts(ctx.now),
    )
    ctx.remember_input(STEP_NAME, payload)
    counts["ranked"] = len(scored)
    return counts


def rank_step(ctx) -> dict:
    """The agent loop's entry point: rank the server's waiting cards."""
    return run_rank(ctx.server, ctx)


def _learned_lines(server) -> list[str]:
    """The learned profile entry texts from the store's document."""
    profile = getattr(server, "learned_profile", None)
    document = getattr(profile, "document", None)
    if document is None:
        return []
    try:
        return list(profile_learned_lines(document()))
    except (OSError, ValueError, TypeError):
        return []


def _audit(server, base: str, model: str, prompt: str, status: str, detail: str) -> None:
    """Record the model and request size, never the prompt or the reply."""
    conn = getattr(server, "audit_conn", None)
    if conn is None:
        return
    try:
        audit_store.record(
            conn,
            "llm.rank",
            target=base or "settings",
            status=status,
            detail=(detail or "")[:200],
            model=model,
            request_bytes=len(prompt.encode("utf-8")),
        )
    except Exception:  # noqa: BLE001 - audit trouble must not stop the pass
        pass
