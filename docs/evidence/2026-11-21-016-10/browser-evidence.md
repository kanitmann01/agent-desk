# Browser evidence: ticket 016-10, self-improving skills and curator

Captured 2026-11-21 against branch `ticket/016-10-skills` at `ae71cd5`,
booted from a throwaway `AGENTDESK_DATA` with the chat endpoint pointed at
`tools/mock_endpoint.py` on loopback via `AGENTDESK_LLM_BASE` (the one
runtime channel this build has; no settings route writes the endpoint row).
Server: `python -m agentdesk.server --port 8805 --no-browser`. Every claim
below is tied to same-instant DOM text read at capture, and, where state
matters, to a direct read of the throwaway SQLite files.

The branch was later rebased onto main after #198 and #199, and the review
fixes (future annotations, the shared strict scan, a blank-line cleanup)
plus the step-order fix touched no rendered HTML, CSS or desktop state. The
undo-return fix restores the inverse entry the Activity page already renders
for other kinds; it does not change the skills section markup. The full gate
at the final code head `c032209` passed 7/7 (3080 passed, 1 skipped).

## Walkthrough 1: creation, label, pin

- `settings-skills-made-by-desk.png`: after five similar assistant asks
  (Jaccard cluster, threshold 5) and one Run now pass whose `skills` step
  reported `created 1`, Settings > Skills shows the skill
  `prepare-the-quarterly-revenue-summary`, `v1 on`, labelled
  "Made by the desk - Active". (The card's description reads "(10 times)"
  because each ask logs two activity rows, question and reply.)
- `settings-skills-pinned.png`: the Pin button clicked; the button flipped
  to "Unpin" (same-instant DOM). Unpinned again afterwards.
- `activity-skill-created-undo.png`: the Activity page ledger row
  "Made the skill ... by itself after the same ask kept coming back."
  with its Undo control, next to the `skill.created` audit row.

## Walkthrough 2: improve, refine, history, undo

- `settings-skills-improve-field.png`: the "Improve this skill" field with
  its "Queue feedback" button on the desk-made card (DOM: FIELD PRESENT).
- `settings-skills-version-refined.png`: after queueing
  "Keep the summary under 200 words and lead with the revenue delta." and
  one Run now pass (`skills` step: `refined 1`), the card's version line
  shows `v1 on, v2 on`. The DB row corroborates: v2 note
  "feedback: Keep the summary under 200 words..." with the refined prompt
  carrying "User feedback applied". (The card caps displayed prompt
  markdown at 400 characters, a pre-existing render rule, so the appended
  feedback text itself is in the DB, not on the card.)
- `activity-skill-refined-undo.png`: the Activity ledger row "Improved the
  skill ... from the queued feedback through the endpoint." with Undo.
- `settings-skills-after-undo.png`: after clicking that Undo, the card
  shows `v1 on, v2 on, v3 on`; the DB proves the restore: v3's prompt is
  byte-equal to v1's, and the live `skills.prompt` equals v1's (the
  refined text is gone).

## Curator

- `settings-skills-curator-line.png`: the Skills section renders
  "Curator last ran 2026-11-21 22:23." (the `curator` step ran in both
  passes). Time-based transitions themselves are covered by the
  clock-injected tests; the ticket only asks for this line to render.

## Made by you: never touched

- `settings-skills-made-by-you.png`: with `skills_auto_create` toggled
  off, five similar asks on a second topic produced a proposal card
  (`skills` step: `proposed 1`, today's behaviour), accepted in the inbox;
  the card is labelled "Made by you" and, per same-instant DOM, has NO
  Improve field (`improve: false`), while the desk-made card keeps its
  field (`improve: true`). The toggle was restored to on afterwards.

## Other files

- `boot-log.txt`: sanitized boot transcript (start-link token redacted;
  the link is single-use).
- `gate-transcript.txt`: `python tools/ci_local.py`, 7/7 PASS, 2892
  passed / 1 skipped, at the fix-back head.
