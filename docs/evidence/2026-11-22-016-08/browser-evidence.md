<!-- Note (2026-11-25): the sample client's name in this record was replaced with the fictional sample name (Harborlight) on 2026-11-25. -->

# Browser evidence: ticket 016-08, learned focus topics and memory auto-save

Captured 2026-11-22 against branch `ticket/016-08-topics` at head
`29c7a6a`, booted twice from throwaway `AGENTDESK_DATA` folders (no
endpoint configured; assistant replies degrade gracefully, which the topic
learner does not read). Every claim below is tied to same-instant DOM text
at capture.

## Walkthrough 1: five asks, Run now, the topic, Remove

- A first batch of five loosely-worded Harborlight asks produced four small
  clusters (the greedy seeder matches against each cluster's first text),
  and the pass honestly reported `learn-topics ok, topics 0`. A second
  batch sharing one core wording ("What do we know about the Harborlight
  Freight <noun>") clustered with the earlier pair; the next pass reported
  `learn-topics ok, topics 1`.
- `settings-learned-topic.png`: Settings > What the desk learned about you
  shows "Harborlight Freight - Learned from 7 asks" with its Remove button,
  plus the two switches this ticket owns, both On. (The DOM text at
  capture includes the full section copy and the learned line.)
- Remove was clicked; `activity-topic-removed.png`: the Activity page
  holds both ledger rows with Undo controls, "Learned the focus topic
  Harborlight Freight: named in 7 similar asks." (`profile.learned`) and
  "You removed the learned topic or line: Harborlight Freight."
  (`profile.removed`), next to the `agentloop.pass` and `profile.learned`
  audit rows.

## Walkthrough 2: the auto-save switch by folder age

- `settings-autosave-on-fresh.png`: fresh folder boot; the section reads
  "0 LEARNED" with its verbatim empty state, and both "Learn focus topics
  from repeated asks" and "Save captured facts without asking" read On
  (default True).
- `settings-autosave-off-existing.png`: the same folder copied with its
  `memory_auto_approve` settings row deleted (a faithful stand-in for a
  pre-016 folder: stores present, no explicit row); that boot shows the
  switch Off and the section's verbatim empty state "Nothing learned yet.
  The desk learns from what you ask it; nothing here is guessed."

## Other files

- `boot-log-fresh.txt`, `boot-log-existing.txt`: sanitized boot
  transcripts (start-link tokens redacted; single-use).
- `gate-transcript.txt`: `python tools/ci_local.py`, 7/7 PASS at the code
  head `29c7a6a`: pytest 2979 passed, 1 skipped; frontend 326 passed.
