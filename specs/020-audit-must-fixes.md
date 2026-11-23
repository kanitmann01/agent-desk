# Spec 020: Audit must-fixes before the simplification

Status: ready-for-agent (2026-11-23). Filed as wayfinder ticket `kanitmann01/agent-desk#277`
on map #272 in that repo. When this file and the ticket disagree, the ticket is the live
copy.

## Problem Statement

The 2026-11-23 ponytail audit (evidence in
`docs/evidence/ponytail-audit-2026-11-23/`) found the desk still carries
defects that a user meets in the first ten minutes. They are small in
code and large in trust: each one makes the screen say something that is
not true.

- **The Decisions cell collapses.** At 1264x805 the text column is about
  25px wide, one word per line, because `frontend/src/index.css:642`
  lays the row out as a non-wrapping flex row and
  `frontend/src/dashboard/Brief.tsx:495-500` puts the actions in it
  without the `.decision-actions` wrapper the legacy renderer still
  has at `src/agentdesk/server/pages.py:956-963`.
- **The inbox button lies.** `src/agentdesk/server/inbox_view.py:48-51`
  renders every card action as `data-accept`. A meeting card labelled
  "Prep in Assistant" therefore consumes the card through
  `/inbox/cards/<id>/accept` (`src/agentdesk/server/pages.py:544-549`)
  instead of opening `/assistant`.
- **A failed dismiss is silent.** `Brief.tsx:177-180` ignores
  `res.ok`; the row stays and nothing says why.
- **A stale workbook is shown as today.** `src/agentdesk/excel/watcher.py:283-291`
  keeps the last good delta on a stale read, and `Brief.tsx:107` uses it
  without checking `status.state`, so last night's moves read as current.
- **The learned profile never reaches ranking.**
  `src/agentdesk/recommend/rank.py:202-206` asks the store for
  `learned_lines`, but `LearnedProfileStore` only has `document()`
  (`src/agentdesk/memory/profile.py:68,97`); the reader is the module
  function at `profile.py:272`. Ranking always sends an empty list.
- **Ranking latches on a useless reply.**
  `rank.py:151-159` ranks snoozed cards too, and `rank.py:183-192`
  remembers the input even when `parse_reply` returned no usable
  score. One empty reply then makes every later pass answer
  "unchanged".
- **The Customize panel is a second dashboard.**
  `frontend/src/dashboard/Dashboard.tsx:539-569` renders a bento that
  Brief ignores; renaming Sales changes a layout the Brief never reads.
  The actions that only exist there (check-off, re-test, run skill,
  source chip) are the real loss if it is deleted first.
- **An opaque Origin is trusted.**
  `src/agentdesk/server/guard.py:88-91` allows `Origin: null` on
  state-changing requests. The allowance exists for the inbuilt webview
  (#60) and is pinned by tests, so turning it off without a replacement
  would break a supported path.

## Solution

A narrow correctness pass. No route, no design system and no data shape
changes. The first six findings are fixed here:

1. Wrap the rendered action in `.decision-actions`, let the row wrap,
   give the text a real flex basis and keep the actions right-aligned.
2. When a card's recommendation meta carries a local href, render an
   anchor with the card's label instead of an accept button.
3. Show an alert when a dismiss fails, and clear it on the next success.
4. Drop the delta client-side when `sales.status.state === 'stale'`.
5. Read the learned lines from the store's document.
6. Rank only visible cards, remember the empty pass so a waking card is
   a change, and only remember the input when at least one score was
   usable.
7. Add tests for the anchor, the stale gate, the learned read and the
   latch.

The last two findings are design changes, not patches, and have their
own tickets:

- The Customize composition and the four actions it owns move into the
  Brief in #274 (core morning loop), then the composition is deleted in
  #275. Teaching the Brief the bento layout would preserve the second
  dashboard, which is the thing the simplification removes.
- The opaque-origin allowance needs a CSRF token on every
  state-changing form before it can be removed. Rejecting `null` now
  breaks the inbuilt webview path pinned by
  `tests/test_server_guard.py:145-162` and
  `tests/test_server_auth.py:190-205`. That work is filed as a
  follow-up; this spec records the residual risk rather than claiming a
  fix.

## User Stories

1. As a user reading Decisions at 1264x805, I want the title and why
   line to keep a readable measure and the actions to sit beside them
   or wrap below, so I can read the decision without one word per line.
2. As a user clicking "Prep in Assistant" on an inbox card, I want the
   assistant page to open, so the label and the result are the same
   thing.
3. As a user dismissing a decision when the desk is unreachable, I want
   the row to stay and an honest error to appear, so I know the click
   did not land.
4. As a user looking at a stale workbook, I want the pipeline card to
   stop presenting the last good delta as today's move, so stale data
   cannot read as current.
5. As a user who reviewed profile lines, I want the ranker to send them
   to the endpoint, so the ranking uses what the desk learned.
6. As a user whose card was snoozed, I want the ranking to wait until
   it wakes and then actually rank it, so a snooze cannot latch the
   step forever.
7. As a maintainer, I want the two remaining findings named with their
   tickets and their residual risk, so a green test run is not mistaken
   for a fixed security boundary.

## Acceptance Criteria

- `Brief` renders a `.decision-actions` wrapper around every decision
  action; `.decision-text` has `flex:1 1 220px` and the row wraps.
- A card whose `meta.recommendation.href` starts with `/` renders
  `<a class="btn btn-primary" href="...">label</a>` and no
  `data-accept`; a card without an href still renders the accept
  button.
- A failed dismiss sets a visible `role="alert"` line; a successful
  one clears it and refetches.
- A sales status with `state: "stale"` and a non-null delta renders the
  no-move line, not the movers.
- `rank._learned_lines` returns the store document's entry texts.
- An empty or unusable rank reply does not call `remember_input`;
  the second pass still calls the endpoint. A snoozed card is excluded
  from the pass, and the pass remembers the empty payload so the waking
  card is a change.
- `pytest` for the touched modules and the frontend tests pass; the
  full suites run before merge.
- The browser check at 1264x805 records the decisions text width after
  the fix (expected at least 200px, up from about 25px).

## Out of Scope

- Removing the Customize composition (#275).
- Moving check-off, re-test, run skill and source chip into the Brief
  (#274).
- CSRF tokens and the opaque-origin change (follow-up ticket).
- The other audit cuts: peers, storefront chrome, presentations.
