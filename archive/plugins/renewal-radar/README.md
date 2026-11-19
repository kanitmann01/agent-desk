# Renewal Radar

Answers: which contracts hit their notice deadline in the next 30 days, and how long is left?

Reads: ops/contracts*.xlsx only. Rows are keyed on Vendor with NoticeDate as the date that matters, inside a 30-day window.

Shows: contracts due in 30 days (metric) and notice deadlines (list: vendor, renewal date, notice date as meta).

Never: writes the workbook, calls the network or the model, or treats the renewal date as the notice date. Rows already past their notice deadline are not counted as upcoming.

Missing data: no workbook or no matching rows renders blank with the source's cause.

