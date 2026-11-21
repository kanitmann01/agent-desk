# Spec 019: BYOK settings UX pass

Status: ready-for-agent (2026-11-21). Filed as issue #254; when the
file and the issue disagree, the issue body is the live copy.

## Problem Statement

Spec 018 shipped the BYOK surfaces and they work: connections save,
keys stay in the keychain, jobs bind, badges update. The evidence pack
from 2026-11-21 (24 screenshots of exactly these surfaces under all
three themes) shows a page that is honest and specific, but a
refinement pass over that evidence and the templates behind it finds
small defects that add up to a page reading as less careful than the
code underneath it is:

- Every checkbox and radio on the Connections card (the twelve preset
  radios, show-the-key, make-default, remove-the-key) renders as a
  tall ellipse instead of its proper circle or square, in all three
  themes. The form's text-field sizing rule leaks onto the small
  controls, and a checked state in a 16 by 36 ellipse is hard to see.
- A connections table row is hard to scan: Test, Edit and Delete wrap
  into three stacked full-size buttons, and a base URL that cannot
  break forces the columns wide, so one row grows past 150 pixels and
  three connections fill a screen.
- The three badge states do not tell their story by color: error
  renders in a gray close to unknown's, and in one theme the failure
  color and the quiet ink are the same value, so error and unknown
  differ only by their word.
- The delete warning page, the one page that must read as carefully
  reviewed, prints run-on words: "job.Deleting", "thosebindings",
  "singleremaining", "thoseanswers". The confirm button on that page
  wears the accent primary styling, the vocabulary of a go button, on
  a destructive action.
- The add form keeps one focus until it ends, then hangs twelve
  equal-weight console link buttons below itself.
- The Jobs card repeats the same long model label ("picked from the
  cached lists or typed") under all seven pickers.

None of this blocks a task. All of it is the difference between a page
a category-fluent user trusts at a glance and one they pause at.

## Solution

A refinement pass, not a redesign. The page identity, every behavior,
every route, the no-JS rule, the three-theme system and the secrets
hygiene are unchanged. The pass fixes the shared control vocabulary at
the one CSS rule that breaks it, compacts the connections table into
scannable rows, gives the three badge states colors that separate them
in every theme, cleans the delete warning page's words and gives its
confirm button the destructive vocabulary, folds the console links
into a no-script disclosure, and lets the Jobs card state its model
hint once instead of seven times.

## User Stories

1. As a user choosing a provider on any theme, I want the twelve
   preset radios to render as circles of their intended size with a
   visible checked state, so the preset grid reads as one standard
   radiogroup instead of a wall of ellipses.
2. As a user filling in the connection form, I want the show-the-key,
   make-default and remove-key checkboxes to render as small squares
   with a visible check, so what is and is not ticked is readable at a
   glance.
3. As a user with several saved connections, I want Test, Edit and
   Delete to sit on one line per row and long base URLs to wrap
   instead of forcing their column wide, so each row stays short
   enough to scan and three rows fit in a screenful.
4. As a user scanning the connections list, I want the ok, error and
   unknown badges distinguishable by color as well as by word in all
   three themes, so a dead key is spotted during the scan rather than
   at the job failure that names it.
5. As a user about to delete a connection that serves jobs, I want the
   warning page's sentences to be whole words in the right order, so
   the page reads as carefully reviewed at the exact moment I am
   deciding whether to trust it.
6. As that same user, I want the delete confirmation styled as a
   destructive action and the Keep it exit as the quiet secondary, so
   the buttons' weights match the stakes of what each one does.
7. As a user adding a connection, I want the provider console links
   available one click away under a disclosure that opens without any
   script, so the form keeps one focus and the twelve links stop
   competing with it.
8. As a user binding jobs, I want each picker's model field labeled
   simply, with the cached-lists-or-typed hint stated once at the top
   of the Jobs card, so the seven forms read as a list of decisions
   rather than seven repeated explanations.
9. As a user who navigates by keyboard or screen reader, I want this
   pass to change shapes and colors only, never labels, focus rings,
   accessible names or tab order, so everything I rely on keeps
   working identically.
10. As a reviewer of this pass, I want every changed flow re-proven
    with screenshots under all three themes in the evidence folder, so
    the visual truth stays current with the code (a flow without a
    screenshot means it was not done).

## Implementation Decisions

- **The control fix lands once, at the shared form-control rule.** The
  text-field rule that styles card-form inputs carries a minimum
  height and padding that leak onto checkbox and radio inputs; the fix
  releases the small controls from that minimum at the rule level, not
  with per-surface patches. The inbox's card-form grid already carries
  this exact opt-out for its consent checkbox, so the precedent and
  the fix pattern exist in the codebase; this pass promotes it to the
  shared vocabulary so every settings checkbox and radio benefits.
- **The connections table compacts by layout, not by new components.**
  The actions cell keeps its three existing controls (the two plain
  forms and the edit link) and lays them on one line; long base URLs
  gain anywhere-wrapping so a mono URL can no longer dictate the
  column widths; the checked-at stamp and cached-model lines keep
  their places in the status cell. The button vocabulary is unchanged:
  same secondary buttons, no smaller variant invented.
- **Badges separate by theme token, not by new chrome.** Error keeps
  the failure token and unknown keeps the quiet ink; the fix gives
  each theme a failure value that can be told apart from that theme's
  quiet ink steps and passes contrast on that theme's surface (4.5:1
  for the word it carries). Themes whose failure token already
  differs keep it. The other consumers of the failure token (down
  deltas, negative cells) are reviewed in the same change, since a
  token value moves them too; they move toward correctness (a falling
  number reading as a falling number), not away.
- **The delete warning page is cleaned word by word.** The non-migrated
  consequence paragraph loses its run-on words (adjacent string
  fragments joined without their spaces); both the normal and the
  migrated variant are re-read in full for the same defect. The
  confirm button takes the existing danger styling, Keep it stays
  secondary, and the named-jobs sentence keeps its pluralization.
- **Console links fold into a native disclosure.** A details element
  (summary, then the existing links) opens with no script at all, so
  the no-JS rule holds and the links stay plain anchors in their
  current vocabulary. The disclosure sits where the link wall is
  today: the last block of the card.
- **The Jobs card states its model hint once.** Each picker's model
  label shortens to "Model"; the "picked from the cached lists or
  typed" fact moves into the card's intro paragraph. The selects, the
  datalists, the save buttons, the preselection rule and the readback
  lines are untouched: behavior is identical, including the untouched
  save that re-posts the same binding.
- **Untouched by design.** The check-the-key block, the deeper-check
  form, the preset grid's structure and its script-assisted base-URL
  fill, the empty states, the endpoint card, the migration flows, the
  masked-hint rules and every route behave exactly as shipped in spec
  018. Restraint is the point of a refinement pass: scanability,
  consistency and restraint beat expression.
- **The locked constraints hold throughout.** Server-rendered markup
  only, every flow working with scripts off, progressive enhancement
  only (the disclosure, the preset fill and the key reveal stay
  enhancements); all three themes render every change; no new runtime
  dependencies; no route changes; no raw key in any state and no
  screenshot of an input holding a value.

## Testing Decisions

- **The primary seam is the existing HTTP seam, unchanged.** The three
  suites that pin the settings markup today (the settings API suite,
  the keys API suite, the job routing suite) are extended in the same
  commits as the markup they pin, per the house rule. No new test
  files, no new seams.
- **What the seams assert is external behavior only**: the corrected
  warning-page sentence renders and the run-on strings are gone (both
  the normal and the migrated variant); the delete confirm posts the
  same delete and carries the danger styling class; the console links
  live inside the disclosure and stay real anchors; the Jobs pickers
  still preselect their binding and their model label reads "Model"
  with the hint in the card intro; the badge classes and inline causes
  render server-side exactly as before. The CSS itself is proven by
  the evidence screenshots, not by string-matching the stylesheet.
- **Prior art**: the keys API suite's page tests (preset grid, masked
  hints, badge states, real no-JS form posts) and the job routing
  suite's warning-page test (the no-JS delete post answering the
  confirmation page) are the patterns these extensions follow.
- **Evidence refresh is an acceptance criterion.** Every changed flow
  is re-screenshot under unkey, coforge and momentuum into the
  evidence folder, keeping the pack's naming, with the same hygiene as
  before: fake demo keys only, no screenshot of an input holding a
  value. The badge story is proven with the three states side by side
  in all three themes.
- **The full local gate stays green**, including the no-keychain leg
  (this pass touches no store and no secret path) and the packaged
  build's smoke is unaffected and untouched.

## Out of Scope

- Animation and motion of any kind beyond the existing transition
  tokens.
- New features: table search, filter or sort; a bound-jobs column on
  the connections table; per-connection model datalists; key
  rotation; bulk actions; keyboard shortcuts beyond the browser's
  own.
- New pages, route changes, or any SPA migration of settings.
- Copy rewrites beyond the named clarity fixes (the run-on paragraph,
  the model label, the disclosure summary): the factual wording,
  vocabulary and voice stay as shipped.
- Reconciling the repo's root design docs with the shipped three-theme
  system; that is repo-wide documentation debt with its own task, and
  this spec treats the shipped theme code as the incumbent authority.
- A responsive or mobile redesign of the settings page.
- Theme rework beyond the failure-token distinguishability fix.

## Further Notes

- Open decisions, each with a recommended default; none blocks cutting
  tickets, and each is the point to veto:
  - The badge fix changes one theme's failure token value (the theme
    where it currently equals a quiet ink step), which also moves that
    theme's down deltas and negative cells. Recommended default: move
    the token, review those consumers in the same change. The
    alternative is a badge-scoped treatment that leaves the other
    consumers broken. Veto point at PR review.
  - The console-link disclosure is a native details element rather
    than leaving the links inline or hiding them behind script.
    Recommended default: details. Veto point.
  - The Jobs model hint moves to the card intro rather than staying
    per-form. Recommended default: move it once. Veto point.
  - The seam cut follows spec 018 precedent: the three existing HTML
    seam suites, no new seams, evidence screenshots as the visual
    proof. Recommended default; the point to veto before tickets are
    cut.
- Method note: this pass was planned with the impeccable critique
  method (operate mode: settings pages; scanability, consistency,
  restraint beat expression), the component taste guide's sections for
  cards, tables, forms, buttons, empty states, status badges and
  dashboards, the 24-screenshot evidence pack, and the template code.
  The heuristic score lands in the good band (28 of 40): the surfaces
  are specific to this product (live stamps, honest state lines,
  plain-language causes) and the findings above are what keeps them
  from scoring higher. A deterministic scan ran and produced only
  advisory drift findings against a stale design document; nothing
  from it is folded in. Findings seen and deliberately excluded, with
  reasons: the design-doc drift itself (repo-wide docs debt, out of
  scope), the settings page's single-column length (page identity,
  preserved), the seven save buttons on the Jobs card (one decision
  per no-JS form is the house rule, correct as built), the pooled
  model datalist across connections (behavior change with seam churn
  for marginal gain, named above as out of scope), and the awkward
  mid-stamp date wrap (subsumed by the table compaction).
- The secrets invariant is restated for the implementer: a masked hint
  is the only key-shaped thing any of these changes may render, no
  state may carry a raw key, and no evidence screenshot may show an
  input holding a value.
