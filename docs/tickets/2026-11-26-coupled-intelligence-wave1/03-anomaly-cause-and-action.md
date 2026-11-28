# 03: Anomaly cause and action

**What to build:** Extend workbook outlier detection so every anomaly names the categorical or date segment that shifted most and attaches one concrete action to verify it, and wire structured provenance (`columns`, `cells`, `rule`, plus desk entity citations) across all workbook findings.

**Build in:** `src/agentdesk/insight/relations.py`, `src/agentdesk/insight/workbook.py`, `tests/test_insight_relations.py`, and `tests/test_insight_workbook.py`. Do not edit `types.py`, `reading.py`, `service.py`, `app.py`, or `frontend/`.

**Blocked by:** 01: Provenance contract and memory citations.

**Status:** ready-for-agent

- [ ] `Finding` gains the new defaulted fields `cells: tuple[str, ...] = ()`, `rule: str = ""`, `segment: str = ""`, and `action: str = ""`; `columns` and `suggested` already exist and are already populated by all five detectors, so they keep their current meaning and values. Existing positional/keyword constructions stay valid.
- [ ] `relations.outliers` checks categorical text columns (passing `_categorical`) and date columns (exact dates or `YYYY-MM` month buckets passing `_categorical` with `>= 2` rows in a segment, so unique-date-per-row columns never treat a single outlier row's date as a segment) to identify the segment whose mean shifted most from the rest of the column (`|segment_mean - rest_mean|`), keeping `Finding.suggested == (outlier_index,)` and all existing z-score/row-count thresholds unchanged.
- [ ] Outlier `Finding.text` includes the most-moved segment cause (when a categorical or date segment exists) and one concrete action (falling back to a concrete row check when no segment column exists, never inventing a segment), while keeping `workbook.derive` within `MAX_FINDINGS` + Chart and `context.max_elements`.
- [ ] All five detectors (`trends`, `correlations`, `shares`, `ratios`, `outliers`) populate `cells` and `rule` (naming the detector rule and threshold) on `Finding`, and `workbook.derive` maps the surfaced findings plus any `insight_connect` entity matches into `InsightReading.why`.
- [ ] Existing tests in `tests/test_insight_relations.py` and `tests/test_insight_workbook.py` remain green, with new tests covering categorical segment shift, date segment shift, flat-label-only fallback action, and workbook `why` provenance. All new code parses under Python 3.10 and carries docstrings.
