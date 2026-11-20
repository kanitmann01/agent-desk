"""Plan, gather and fill a presentation. One call per step, then the writer.

A failed plan or a timed-out call degrades the run and writes no file.
Numbers that no kept source contains are replaced with a data-needed marker.
"""

from __future__ import annotations

import json
import re
import threading

from agentdesk.llm import LlmUnavailable

DEFAULT_TIMEOUT_S = 30.0
_DIGITS = re.compile(r"\d[\d,.]*")


def timeout_seconds(raw) -> float:
    """The presentation timeout. A blank or unusable value is the 30s default."""
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    if value <= 0:
        return DEFAULT_TIMEOUT_S
    return value


def call_model(llm, prompt: str, timeout: float) -> str:
    """One model call bounded by `timeout` seconds.

    The request thread waits at most that long. A callable that accepts
    `timeout` is given it (the real client applies it to the socket).
    A callable that only takes the prompt is run in a daemon thread and
    abandoned if it overruns, so a hung call does not pin the request.
    """
    try:
        return llm(prompt, timeout=timeout)
    except TypeError:
        box: dict = {}

        def run() -> None:
            """The model call, off the request thread so a hang can be abandoned."""
            try:
                box["value"] = llm(prompt)
            except Exception as exc:  # noqa: BLE001 - handed back to the caller
                box["error"] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise LlmUnavailable(
                f"the endpoint did not answer within {timeout:g} seconds (timeout)"
            )
        if "error" in box:
            raise box["error"]
        return box.get("value", "")


def gather(memory: list, excel: dict | None, watch: dict | None,
           enabled: set[str]) -> list[dict]:
    """Numbered sources from the desk reads the user left on.

    A source whose name is not in `enabled` is not read: the arguments
    for a disabled source must be ignored.
    """
    sources = []

    def add(kind: str, label: str, text: str, at: str = "") -> None:
        """Append one numbered source."""
        sources.append({
            "id": len(sources) + 1,
            "kind": kind,
            "label": label,
            "text": text,
            "at": at,
        })

    if "memory" in enabled:
        for fact in memory or []:
            text = str(fact.get("text") or "").strip()
            if text:
                add("memory", "Memory", text)
    if "excel-report" in enabled and isinstance(excel, dict) and excel.get("configured"):
        bits = []
        if excel.get("path"):
            bits.append(f"workbook {excel['path']}")
        delta = excel.get("delta") or {}
        if isinstance(delta, dict):
            added = delta.get("added") or []
            if added:
                bits.append(f"added {len(added)}")
            for row in added:
                if isinstance(row, dict) and row.get("value") is not None:
                    bits.append(f"{row.get('region', '')} {row.get('value')}")
        at = str(excel.get("polledAt") or excel.get("checkedAt") or "")
        add("excel-report", "Workbook tracker", "; ".join(bits) or "workbook connected", at)
    if "competitor-watch" in enabled and isinstance(watch, dict) and watch.get("text"):
        add("competitor-watch", "Page watch", str(watch["text"]), str(watch.get("at") or ""))
    return sources


def guard_numbers(text: str, sources: list[dict], cited: list[int]) -> str:
    """Replace a digit sequence that no cited source contains.

    The replacement is the visible marker `[data needed]`.
    """
    allowed = " ".join(
        source["text"] for source in sources if source["id"] in set(cited)
    )

    def replace(match: re.Match) -> str:
        """Keep a number only when a cited source already contains those digits."""
        token = match.group(0)
        digits = re.sub(r"\D", "", token)
        if digits and digits in re.sub(r"\D", "", allowed):
            return token
        return "[data needed]"

    return _DIGITS.sub(replace, text)


def plan_prompt(brief: str, recipe: dict) -> str:
    """The one plan call: topic, recipe sections, JSON only."""
    sections = [
        {"id": section.get("id"), "title": section.get("title")}
        for section in recipe.get("sections") or []
    ]
    return (
        "Presentation plan. Reply with JSON only: "
        '{"sections": [{"id": "the section id", "title": "the section title"}]}. '
        "Use these sections, in this order, and do not add any.\n"
        f"Recipe: {recipe.get('id')}\n"
        f"Sections: {json.dumps(sections)}\n"
        f"Topic: {brief}"
    )


def parse_plan(reply: str, recipe: dict) -> list[dict] | None:
    """The recipe's sections, if the reply lists exactly those ids."""
    expected = [section for section in recipe.get("sections") or [] if section.get("id")]
    try:
        document = json.loads(_json_text(reply))
    except ValueError:
        return None
    got = document.get("sections") if isinstance(document, dict) else None
    if not isinstance(got, list) or len(got) != len(expected):
        return None
    planned = []
    for item, section in zip(got, expected):
        if not isinstance(item, dict) or item.get("id") != section.get("id"):
            return None
        planned.append({
            "id": section["id"],
            "title": str(item.get("title") or section.get("title") or section["id"]),
        })
    return planned


def fill_prompt(section: dict, sources: list[dict], brief: str) -> str:
    """One section fill. The model may cite only the numbered sources."""
    lines = [
        f"{source['id']}. ({source['kind']}) {source['text']}"
        for source in sources
    ]
    block = "\n".join(lines) or "(no sources)"
    return (
        "Presentation fill. Reply with JSON only: "
        '{"title": "slide title", "bullets": ["one point", "another"], '
        '"citations": [1]}. Cite source ids. Do not invent numbers.\n'
        f"Topic: {brief}\n"
        f"Section: {section['title']}\n"
        f"Sources:\n{block}"
    )


def parse_fill(reply: str) -> dict | None:
    """A fill object, or None when the reply is not that JSON."""
    try:
        document = json.loads(_json_text(reply))
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    bullets = document.get("bullets")
    if isinstance(bullets, str):
        bullets = [bullets]
    if not isinstance(bullets, list):
        bullets = []
    citations = document.get("citations") or []
    if not isinstance(citations, list):
        citations = []
    return {
        "title": str(document.get("title") or "").strip(),
        "bullets": [str(item).strip() for item in bullets if str(item).strip()],
        "citations": [int(item) for item in citations if str(item).isdigit()],
    }


def outline_from_fill(brief: str, recipe: dict, planned: list[dict],
                      filled: list[dict], sources: list[dict]) -> dict:
    """The writer's outline: title, a divider and content slides, closing.

    Bullets have passed the digit guard. Notes list the cited sources.
    """
    title = " ".join(brief.split())[:60] or "Untitled"
    slides = [{"role": "title", "title": title}]
    for section, fill in zip(planned, filled):
        slides.append({"role": "section", "title": str(section["title"])[:40]})
        cited = fill.get("citations") or []
        bullets = [
            guard_numbers(bullet, sources, cited)[:110]
            for bullet in (fill.get("bullets") or ["Prepared from the desk."])
        ]
        notes = _notes(cited, sources)
        slides.append({
            "role": "content",
            "title": guard_numbers(fill.get("title") or section["title"], sources, cited)[:60],
            "bullets": bullets[:5] or ["Prepared from the desk."],
            "notes": notes,
        })
    slides.append({"role": "closing"})
    return {"title": title, "slides": slides}


def receipt_lines(sources: list[dict]) -> list[dict]:
    """What the run page lists: kind, label, text, and the timestamp when there is one."""
    return [
        {"id": source["id"], "kind": source["kind"], "label": source["label"],
         "text": source["text"], "at": source.get("at") or ""}
        for source in sources
    ]


def _notes(cited: list[int], sources: list[dict]) -> str:
    """Speaker notes: each cited source, with its timestamp when it has one."""
    by_id = {source["id"]: source for source in sources}
    lines = []
    for number in cited:
        source = by_id.get(number)
        if source is None:
            continue
        when = f" ({source['at']})" if source.get("at") else ""
        lines.append(f"{number}. {source['label']}{when}: {source['text']}")
    if not lines:
        return "Sources: none."
    return "Sources:\n" + "\n".join(lines)


def _json_text(reply: str) -> str:
    """The JSON body of a reply, with a fence removed when the model added one."""
    text = (reply or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()
