# Sales 24h Delta

Answers: what changed in the sales workbook since yesterday?

- Source: excel-watch on ${workspace}/reports/*.xlsx, window 24h.
- Elements: a 24h delta, the rows-seen count, and the changed-row list.
- Blank state: when the workbook is missing the card names the glob and
  shows no number, never a zero.
- Sample: sample.json shows 1,284 rows seen with 18 new and 4 removed.

The plugin keeps its original id, skill, and threshold preference, so an
install over 0.1.0 upgrades in place.
