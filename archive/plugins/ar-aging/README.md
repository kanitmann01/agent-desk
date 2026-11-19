# A/R Aging

Answers: how much cash is stuck, and how old is it?

- Source: excel-watch on ${workspace}/finance/ar*.xlsx, keyed on
  Customer with the Balance column, 30-day window.
- Elements: the cash-stuck metric, an aging-bucket table
  (0-30 / 31-60 / 61-90 / 90+ days), and the oldest-balances list.
- Blank state: a missing workbook names the glob, key, and value columns.

The sample totals 184,500 USD across four buckets.
