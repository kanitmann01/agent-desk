# Follow-up Watch

Answers: which promises have I made, and which are aging past their due date?

Reads: commitments/*.csv in the workspace only. Each row is keyed on Owner with Due as the promised date and a 30-day window.

Shows: open count (metric, bound to the csv-watch value, which is the row count when aggregate=count) and aging promises (list: owner, promise, due date). Age in days and the past-due flag need the source to supply them; the current CSV binding provides the due date only.

Never: edits the CSV, writes anywhere, calls the network or the model. Rows without a usable due date are left out of the age calculation rather than guessed.

Missing data: no matches in the window renders the count and list blank with the source's cause.

