# 03: The workbook says what the rows mean, which chart fits, and which rows to pick

**What to build:** a tracked workbook card whose reading names the strongest relationship in the selected data, recommends a chart shape with a reason, calls out outliers by name, and proposes the rows worth selecting — all in sentences that carry their own numbers.

**Blocked by:** 01, 02.

**Status:** ready-for-agent

- [ ] Pure table maths classifies columns (number, date, text), and detects share, trend, correlation, ratio and outlier relationships under the conservative thresholds the spec fixes.
- [ ] Each statement carries the numbers that justify it; below the thresholds the maths returns nothing rather than a weak claim.
- [ ] Chart choice maps the strongest relationship onto a shape (trend to line, share to bar, ratio to table), honours the user's chart preference when it is not auto, and explains itself in one clause.
- [ ] The tracker card gains at most three text elements, or a checklist when the user's density is chatty, and one line when the table was too small or too flat to read.
- [ ] Suggested row indices are exposed on payload["insight"] for the setup sheet to preselect later, bounded to five.
- [ ] tests/test_insight_relations.py covers each relationship, each refusal, and the chart mapping over hand-built tables.
