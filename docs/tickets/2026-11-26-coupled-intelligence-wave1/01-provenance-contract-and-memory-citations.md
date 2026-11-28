# 01: Provenance contract and memory citations

**What to build:** Extend the insight reading contract so every reading can carry structured `"why"` provenance (claim, columns, bounded cell references, rule/threshold, cited memory fact IDs/sources, and matched desk entity citations), surface `"why"` cleanly inside the `"receipts"` block, and populate provenance on the digest and calendar families.

**Build in:** `src/agentdesk/insight/types.py`, `src/agentdesk/insight/context.py`, `src/agentdesk/insight/agenda.py`, `src/agentdesk/insight/insight_connect.py`, `src/agentdesk/insight/reading.py` (`blocks` only; `PRESS_LABELS` belongs to ticket 04), `src/agentdesk/insight/digest.py`, `src/agentdesk/insight/calendar.py`, and `tests/test_insight_provenance.py`. Do not edit `service.py`, `relations.py`, `workbook.py`, `research.py`, `press.py`, `app.py`, or `frontend/`.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `InsightReading` gains `why: tuple[dict, ...] = ()` and `falsify: str = ""` at the end of its dataclass fields (`falsify` is consumed later by ticket 04, so keep it even though nothing reads it in this ticket), keeping all existing positional and keyword constructions unchanged.
- [ ] `context._memory` and `agenda.recalled` preserve integer fact `id` (excluding `bool`) on returned fact dicts only when the recalled fact object exposes an integer `id`, preserving exact compatibility with mock `Fact(text, source)` objects in `tests/test_insight_seam.py`.
- [ ] `insight_connect` exposes a helper returning `(line, notes, matched_entities)` (or similar pure projection of `DeskName` with `entity_id`, canonical name, `fact_count`, and `event_clause`) while keeping `connect_line(rows, index) -> (line, notes)` unchanged.
- [ ] `reading.blocks(reading)` resolves `reading.why` into a bounded, sanitized `"why"` list attached directly to the `"receipts"` block when `reading.why` is non-empty, omitting `"why"` when empty so `tests/test_insight_blocks.py` and `tests/test_insight_seam.py` pass untouched. Each `why` entry keeps only bounded `claim`, `columns`, `cells` (capped at 6), `rule`, and `facts` (`id`/`source` or `entityId`/`name`/`factCount`, never raw fact prose).
- [ ] `digest.derive` and `calendar.derive` populate `why` with the matched thread/meeting reference, rule/threshold (including focus/prep window context), and cited fact IDs/sources without changing their `elements` or `receipts`.
- [ ] All new functions/methods have concise docstrings, parse under Python 3.10, and pass existing insight tests plus `tests/test_insight_provenance.py`.
