# Coupled intelligence: what shipped, and what it found

Spec 009, tickets 01–06, branch `feature/coupled-intelligence`. Everything
below is runnable in this checkout: `PYTHONPATH=src python -m pytest tests/test_insight_*.py
tests/test_server_insight_html.py tests/test_server_preferences_form.py`.

## What shipped

- **One seam, five families.** `src/agentdesk/insight/service.py` maps a plugin
  id to a reading (`excel-report` -> `workbook.derive`, `calendar-today` and
  `meeting-prep` -> `calendar.derive`, `outlook-digest` and `waiting-on-you` ->
  `digest.derive`, `research-brief` -> `research.derive`). Readings append at
  most four elements to the card's own payload and write
  `payload["insight"] = {status, source, preferences, note, press, suggested}`.
  An unmapped plugin is untouched; a reading that raises degrades to a note
  rather than a blank card.
- **The workbook reads its own rows** (`insight/relations.py`, pure stdlib
  arithmetic). It classifies columns as number/date/text, then looks for share,
  trend, correlation, ratio and near-tie, and prints the strongest one or two
  with their numbers: "Booked and Margin move opposite (r = -0.92 over 8 rows)."
  It names the chart the data wants (trend -> line, share or outlier -> bar,
  correlation or ratio -> table), honours the user's chart preference when it
  is not `auto`, and exposes `suggested` row indices (at most five) for a setup
  sheet to preselect.
- **The calendar turns the next meeting into prep.** It sizes a checklist to
  the user's prep window ("Set aside 20 minutes before this."), adds up to two
  recalled lines prefixed "Last time:", and overlaps the meeting title with the
  user's focus topics. It never repeats the card's own next-event sentence.
- **The digest names why a thread is waiting and drafts the reply.** It picks
  the one thread that matches a focus topic or a recalled fact, states the
  reason, and offers `{"label": "Draft a reply", "route": "/api/insight/draft",
  "kind": "reply-draft"}`. `insight/digest.compose` builds a skeleton from the
  subject, sender and last line shaped by `replyTone` and `replyLength`, and
  upgrades to one model call (<= 900 characters of prompt) only when a model
  route exists.
- **The research card continues from the answer it has.** It states the closest
  focus topic, flags an answer older than the next meeting, proposes up to
  three questions each naming its source (focus list or calendar), and lists up
  to two attributed memory lines ("You already decided this: ...").
- **Preferences the user owns.** `insight/preferences.py` holds six fields in
  one versioned `preferences.json`: chart, replyTone, replyLength,
  insightDensity, focusTopics, prepMinutes. Writes validate the whole document,
  refuse unknown keys and off-vocabulary values with a named code, and persist
  atomically. Settings shows them in a no-JavaScript form that states they are
  never inferred. `prompt_lines()` gives readings at most six bounded lines.
- **Two surfaces, one path.** `/api/dashboard` and the server-rendered dashboard
  both go through `with_insight()`, and the HTML card renderer now knows
  `list`, `checklist` and `status` elements in addition to `metric` and `text`.

## What the survey found about the existing desk

- **`meeting-prep` already printed the next event and its own prep checklist**,
  and `calendar-today` was purely mechanical. The honest addition was therefore
  small: the prep window from preferences, memory lines, and a focus-topic
  overlap. Anything larger would have restated the card.
- **`waiting-on-you` and `outlook-digest` already ranked threads**
  (`mail/brief.score_message`: +5 urgent word, +2 question, +2 to-me, +3 within
  two hours, -4 no-reply). Re-ranking would have been a second opinion, so the
  digest reading reuses that ranking and adds only the *reason* and the draft.
- **Row picking was entirely manual** (`RowSelectGrid.tsx`,
  `TrackerSetup.tsx:110` preselects every row). `tracker.read_tracker()` was
  pure arithmetic with no relationship, correlation or anomaly code anywhere in
  the runtime. This was the real gap.
- **The research card had no topic-suggestion path at all** — one sqlite row of
  the last answer, rendered as text. Everything the reading adds is new.
- **No preference store existed.** `SettingsStore` held toggles and
  credentials only, and an unknown key raised `KeyError`; a "preference" was an
  untyped fact of kind `world` or `experience`. Hence a typed document, and
  hence the copy that says these six are the only ones used and never inferred.
- **Memory writes stay behind approval.** The only accepted fact write is
  `_on_fact_carried` after a user accepts an inbox card; the insight readings
  only read. Retain remains an explicit press.

## Thresholds that decided behaviour

| Relationship | Needs | Claim |
| --- | --- | --- |
| correlation | >= 8 paired numeric rows, |r| >= 0.6 | "move together / opposite, r = ..., over N rows" |
| trend | >= 6 dated points, >= 70% monotonic | direction plus first-to-last change |
| share | >= 3 groups, top >= 50% | "X carries N% of the range" |
| near-tie | >= 5 rows, max/min <= 1.5 | "the top N rows are within 1.5x of each other" |
| outlier | >= 8 points, |z| >= 2.5 | names the row and its value |

Below these the maths returns nothing. A reading is capped at quiet 1 /
normal 3 / chatty 4 elements, a press prompt at 900 characters, and a finding
sentence at 400.

## What did not land, and why

- **Attendee-named prompts.** `context.build_context` gives a reading the next
  event's title, time, meta and prep items — not its attendees. Naming people
  would have meant inventing them, so the calendar reading names topics and the
  meeting title instead.
- **Entity-derived research questions.** An entity the stored answer already
  names is the one thing a "research this next" prompt must not claim is
  uncovered, so entities are used for *coverage* testing and the questions come
  from focus topics and the calendar.
- **A ranked list of three waiting threads.** The digest reading picks the one
  thread with the best reason and leaves the ranking visible in the card's own
  list.
- **A press button on any surface.** `payload["insight"]["press"]` carries the
  offer and `POST /api/insight/draft` answers it, but no page draws the button
  yet. Both kinds work when called.
- **The built SPA's tracker card.** `frontend/src/dashboard/TrackerCard.tsx`
  renders its own figure and ignores `payload.elements`, so the workbook
  reading is visible on the server-rendered dashboard and invisible in a built
  SPA until that card maps the elements. `frontend/dist` is not in this
  checkout and `node_modules` is empty, so this could not be built or checked.
- **A reset for preferences.** `PreferenceStore.reset()` exists and is tested;
  no route exposes it.
- **The registry gate.** `tests/test_registry_library.py` fails 8 tests from
  content-pin drift (`sha256 e0a9e77147fe` vs pinned `e53efb1fb99a`) at base
  commit `daaa8d6` too, and `git diff --name-only daaa8d6 | grep -c '^registry/'`
  is 0. `tools/ci_local.py` therefore cannot be green on this machine for a
  reason that predates this branch.

## What the next round should pick

1. **Draw the press.** A no-JS form per card that posts to
   `/api/insight/draft` and renders the draft in the existing reply writer —
   this is the shortest path from "the desk noticed" to "the desk did".
2. **Map elements in `TrackerCard`** so the workbook reading survives the SPA.
3. **Preference receipts (#15).** The store is now typed; showing where each
   reading used a preference would make the coupling legible.
4. **Provenance surface (#17).** Every reading already knows its source; the
   card does not yet show it.
5. **Commitments ledger (#1).** The agenda seam already carries the next meeting
   and recall; a ledger of what the desk promised is the natural next asset.

Ideas 1–20 with their trade-offs are in
`docs/ideas/2026-11-18-coupled-intelligence.md`.
