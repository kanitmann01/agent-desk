# O3: What is the feeder's privacy, consent and failure contract?

Type: grilling. Claim: unclaimed. Blocked by: O1, O2.

## Question

Given the chosen local source and scheduler, what exactly does the feeder read, what does it write, what does the app show, and what does it refuse to do?

Settle:

- the fields the feeder may read (headers only, or a named metadata subset) and the fields it must never read;
- whether the feeder writes `.eml` files, a local SQLite database, or both, and why;
- where the files live, how long they are kept, and how the user deletes them;
- the consent moment: what the user sees before the feeder is installed, and what the app records;
- the honest states: Outlook not installed, no profile, new Outlook unsupported, cache locked, source stale, task not running, app closed, folder unreadable;
- the exact user-facing copy for each state, following the repo's rule that an attention state never shows an invented zero;
- the uninstall path: remove the task, stop the feeder, keep or delete the data, and what the app says.

## Answer

Pending. Resolve with the research answers, the repo's existing mail and calendar states, and the PRD privacy constraints. Record the contract here, then close this ticket and add a line to the map's Decisions so far.
