# 04: Research falsification and counter-evidence press

**What to build:** Give every non-empty research reading a deterministic `"What would change my mind"` falsification block derived from the stored answer's claims, wire its provenance, and add a `"check-counter"` press action (`"Check counter-evidence"`) to test the conclusion against opposing evidence with explicit disclosure and model-off refusal.

**Build in:** `src/agentdesk/insight/research.py`, `src/agentdesk/insight/press.py`, `src/agentdesk/insight/reading.py` (`PRESS_LABELS` and `"falsify"` block emission), `tests/test_insight_research.py`, and `tests/test_insight_press.py`. Do not edit `types.py`, `service.py`, `workbook.py`, `app.py`, or `frontend/`.

**Blocked by:** 01: Provenance contract and memory citations.

**Status:** ready-for-agent

- [ ] `InsightReading` (or `reading.blocks`) supports a `"falsify"` block (`{"kind": "falsify", "text": ...}` when `reading.falsify` is non-empty), placed after `"receipts"` and before `"note"` without touching `reading.elements` so pinned research element contracts remain intact.
- [ ] `research.derive` deterministically derives `"What would change my mind: ..."` from comparative, causal, quantitative, or keyword claims in `_answer(payload)`, populates `why` (claim, rule, recalled fact IDs/sources), and omits falsification when no answer is stored (`status == "empty"`).
- [ ] `research.derive` attaches a press offer `{"label": "Check counter-evidence", "route": "/api/insight/draft", "kind": "check-counter", "text": ...}` bounded to `press.MAX_FINDING` characters.
- [ ] `press.KINDS` and `reading.PRESS_LABELS` include `"check-counter"` (`"Check counter-evidence"`), preserving the `set(PRESS_LABELS) == set(PRESS_KINDS)` invariant pinned at `tests/test_insight_blocks.py:109` (no edit needed there; it must stay green).
- [ ] `press.draft_reply` handles `kind == "check-counter"` with explicit disclosure lines, 400 refusal on missing or oversized `text`, 409 `insight:model-off` refusal when Your AI is off, and bounded counter-evidence prompt when a completer is available.
- [ ] `tests/test_insight_research.py` and `tests/test_insight_press.py` cover falsification generation and press disclosure/refusal/completion; `tests/test_insight_blocks.py`, which pins the press-vocabulary equality, stays green without edits. All new code parses under Python 3.10 and carries docstrings.
