# Spec 007: Real data on the demo path, one audit trail, one settings home

Status: ready-for-agent (2026-11-17). Demo target: 2026-11-18 (EVP walkthrough).
Tickets live in docs/tickets/2026-11-17/.

## Problem Statement

The desk is being demonstrated tomorrow, and the demo path is not a product path yet.

1. **The visible tracker is fake.** The dashboard's TRACKER card is stamped SAMPLE DATA
   and reads sample-sales.xlsx (412,300 USD, "Closed Won, this quarter"). Nothing in
   the UI walks a user from "this is my file" to "my rows are tracked" as one story;
   the sample is what a viewer sees first.
2. **Only Excel and CSV are readable.** The ask names Excel or JSON. preview_table has
   a csv branch and an xlsx branch and no json branch, so a JSON export cannot be
   browsed, previewed, or tracked even though JSON is the common shape of an export.
3. **The model judges the file before the user chooses, never after.** suggest.py runs
   its heuristic/model suggestion on staging and asks the model which columns it likes.
   When the user's own choice is already on screen there is no second opinion, no
   accept/adjust step, and no language for "this pairing does not correlate".
4. **Three rail surfaces do not earn their slot.** Activity renders an empty page.
   Capabilities duplicates Marketplace (installs/updates) and Settings (endpoint and
   gates). Peers is not wanted on the demo rail. Settings is a 3,264 px stack of
   differently shaped cards.
5. **There is no one audit trail.** Several modules record their own audit rows
   (llm.*, marketplace.*), the Activity page renders none of them, and Settings shows
   fragments. "Every trace of what the user does" has no single home.
6. **Nothing proves the path in a browser.** Verification has been endpoint tests and a
   headless walkthrough script; no run has driven the real UI from Browse to a card
   showing real numbers, and no run has checked every rail button and card geometry.

## Solution

Surface-level outcome: one browser session that browses a real workbook or JSON export,
picks rows, gets one model opinion on the choice, accepts or declines it, confirms, and
sees the tracker card show the file's real numbers; the same session proves every rail
destination renders and every card sits inside its grid.

- **G1 File truth.** Browse accepts .xlsx, .csv and .json. JSON (array of objects, or an
  object with a list of objects) previews as a table with the same header/row contract
  the tracker already consumes. The card names the file it reads and the last time it
  read it; the SAMPLE DATA stamp is reserved for genuinely sample-backed instances.
- **G2 One evaluation call.** After the user assigns label/value columns and selects
  rows, one call evaluates that choice: does the pairing make sense for a tracker, and
  is there a better column or row set. The answer is a verdict plus an optional
  recommendation with a one-line reason. Accept applies it, decline keeps the user's
  choice, and "no recommendation" leaves a plain Approve. A missing endpoint, timeout,
  or malformed answer never blocks confirmation: the heuristic stands in and the surface
  says the check was skipped, in plain words.
- **G3 Rail surgery.** Peers leaves the rail (route stays, reachable by URL, so nothing
  breaks). Activity becomes Settings > Activity. Capabilities becomes a section inside
  Settings. One rail, no dead ends: every remaining destination renders content.
- **G4 One audit trail.** One store and one reader: every mutating request and every
  model call records who/what/when/outcome/target. Settings > Activity lists it newest
  first with a kind filter and a CSV export. The old /audit/tail JSON stays for scripts.
- **G5 One settings shape.** Settings is a grid of one card component: title, one-line
  purpose, body, actions. No mixed card chrome, no duplicate endpoint controls, no card
  that renders only a divider. The three theme swatches become one control.
- **G6 Browser proof.** A recorded walkthrough (script + screenshots + pass/fail table)
  from served HTML through Browse, selection, evaluation, confirm, and the real card,
  plus a full rail sweep: every link returns a page with content, no card overlaps
  another, no horizontal scroll at 1280 px and 1600 px.

## User Stories

1. As the presenter, I want the first tracker on screen to read a real file, so that the
   demo never opens on sample data.
2. As a desk owner, I want Browse to accept my JSON export as readily as my workbook, so
   that I do not convert files before using the product.
3. As a desk owner, I want the model to check my column and row choice, so that a
   meaningless pairing gets caught before I track it for a month.
4. As a desk owner, I want to decline the model's suggestion and keep my choice, so that
   the tool advises and I decide.
5. As a desk owner, I want a skipped check to say it was skipped, so that silence is not
   mistaken for approval.
6. As a desk owner, I want one Settings page that covers endpoint, gates, sources, and
   history, so that I stop hunting across three tabs.
7. As a desk owner, I want one activity log of everything the desk did, so that I can
   answer "what changed and when" without reading files.
8. As a reviewer, I want the demo path proven in a browser with screenshots, so that
   "it works" is evidence, not a claim.

## Acceptance Criteria

- G1: a .json file of 3+ objects previews with correct headers and rows through the same
  endpoint as xlsx; a tracker instance bound to it returns the summed value of the chosen
  rows; an .xlsx path still returns the same shape as today.
- G2: evaluate returns 200 with {verdict: "ok" | "adjust", message, recommendation?} for
  a valid selection; recommendation, when present, contains labelColumn/valueColumn/rows
  that exist in the preview; accept applies them and the stored tracking matches; decline
  stores the user's original tracking; no endpoint configured returns 200 with
  verdict "unchecked" and a one-line cause, and confirm still succeeds.
- G3: no rail contains Peers; /activity redirects to /settings#activity; /capabilities
  redirects to /settings#capabilities; every rail link's page body has at least one card
  or form control.
- G4: one page action (e.g. confirming a tracker) and one model call each appear in the
  Settings > Activity list with action, target, and outcome; CSV export contains them.
- G5: Settings renders as a single card grid at 1280 and 1600 px with no overlapping
  cards, no horizontal overflow, and no section that is only a heading.
- G6: docs/demo/2026-11-18-evp.md records each step, its evidence, and the rail sweep
  result; failures found are fixed in the same ticket set.

## Non-Goals

- Issue #115 (registry pin drift) and the enterprise workflow red state.
- Nuitka installer, SBOM, counsel-review licensing.
- Multi-user, RBAC, real peer sync.
- Reworking the wizard's describe/questions steps.

## Risks

- The demo laptop may have no LLM endpoint configured: G2's unchecked path must be the
  rehearsed path too, and the surface must read as a feature ("skipped, no endpoint"),
  not an error.
- The native file dialog runs in the windowless pythonw process; it is the existing
  pick path, but ticket T01 must prove it opens and returns a path on this machine.
- The live data dir holds a sample instance; the demo must not depend on deleting it,
  only on creating the real one alongside it.
