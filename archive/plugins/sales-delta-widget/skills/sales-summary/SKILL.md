---
name: sales-summary
description: Summarize the 24h sales delta for the dashboard widget. Reads the watched workbook's parsed rows, compares them with the T-24h snapshot, and writes one plain-language summary line naming what changed and by how much.
---

# Sales summary

Reads the parsed rows of the sales workbook and writes a short summary line.

Use it after an excel-watch poll when the user asks what changed in the
sales file. Name the counts first (new rows, removed rows), then quote at
most two example rows. Never paste the whole workbook; the summary is a
derived abstraction, not a copy.
