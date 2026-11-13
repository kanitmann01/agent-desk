---
name: workbook-report
description: Report on the watched report workbook for the dashboard card. Reads the parsed rows and the 24h snapshot diff, then writes one plain-language report naming how many rows the workbook holds and which rows appeared or disappeared in the window.
---

# Workbook report

Reads the parsed rows of the watched report workbook and writes a short
report line.

Use it after an excel-watch poll when the user asks what is in the
reports folder. Lead with the row count and the workbook name, then name
what changed in the last 24 hours (rows added, rows removed). Quote at
most two example rows; never paste the whole workbook. The report is a
derived abstraction, not a copy.
