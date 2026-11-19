# Week Load

Answers: how booked is next week, and where does the load sit?

Reads: the calendar bridge only. No workspace files, no network.

Shows: hours next week (metric), meetings by day (sparkline), today's
events (list).

Never writes to the calendar, asks the model, or invents hours. `weekHours`
and `weekPoints` come from the host's day view (next 7 days of hours, 14
days of event counts); a missing or stale bridge renders blank with the
bridge's cause rather than a made-up number.
