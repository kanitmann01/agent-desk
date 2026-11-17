# File selection and wizard finish-line merge record, 2026-11-17

## Context

Spec 006 (issue #123, snapshot at specs/006-file-selection-and-wizard-fix.md), cut into
tickets #124 through #129 (files under docs/tickets/2026-11-17-file-selection/). Three
connected deliverables from the user's 2026-11-17 session: the Add-plugin wizard's
approve step ends on a real page instead of raw JSON; the wizard's workbook builds stop
fabricating a `reports/*.xlsx` permission and become configurable instances; the
per-instance file setup (browse, preview, pick columns and rows) becomes a capability any
config-backed plugin gets, with drag/brush/shift-click/select-all row selection and a
manage-surface entry.

The approve dead-end was reproduced live before any code: against the real server, a
plain form post to the wizard approve action answered 200 JSON and the browser parked on
the raw response document at the approve URL. The answer step already redirected; approve
did not.

## Provenance

| Commit | Ticket | Delivered |
| --- | --- | --- |
| abb2010, 58b784e | spec | specs/006 file, published as issue #123, amended once (wizard workbook builds become config-backed instances rather than keeping the fabricated glob) |
| 0c3cea7 | tickets | six tickets published as issues #124-#129 with REST blocked_by edges |
| 08ac06e | #124 | approve answers form posts 303 to the session page, which renders an approved state (id, version, pilot, does/reads/never, removal hint, honest CTA); JSON clients keep the 200 contract; the full no-JS walk test |
| fe0fc0b | #126 | instance setup serves any plugin declaring config kinds (runtime card expansion `<plugin>~<instance>`, wireframe-with-Set-up, per-plugin grant isolation, uniform cap); fixture plugin qbr-pack validates through the shared validator and proves the chain over real HTTP |
| 1b65494 | #126 follow-up | the instance dispatch parsed the plugin id but never forwarded it, so every `/api/plugins/<id>/instances` request served excel-report's namespace; helpers require plugin_id, chain test un-xfailed (its cap arithmetic corrected: the seventh instance is the refused one) |
| ba22710 | #125 | wizard workbook builds compose the config-backed shape (workbook kind, empty filesystem read, file-less excel-watch dataSource); `_sanitize_manifest` pins the floor so no LLM suggestion can escape it; approval summary names setup instead of a path; non-workbook builds byte-identical |
| 14c87b0 | #127 | rows selection: shared RowSelectGrid (click toggle, pointer sweep respecting anchor state, shift-click range, select all, clear, live count) + ModalSheet dialog shell; confirm carries tracking.rows; stored config records it, the tracker read honors it, out-of-range confirms refuse with the existing mismatched-file code |
| 8d906cf | #128 | GET /api/plugins/<id>/instances listing; marketplace manage view lists instances with Set up/Edit against the same endpoints; alias plugins resolve to their target instance with no second config surface |
| b3b31a8, 57e1c29 | #129 | the manage sheet walks the shared pick-and-rows flow; chain test drives describe -> questions -> approve (form) -> approved page -> instance create -> pick (fake picker) -> confirm with rows -> fresh dashboard card reading exactly the selected rows; walkthrough updated (picker injection, setup-state wizard card, no fabricated glob); committed bundle rebuilt; a chain-exposed runtime seam fixed (instance cards now pass the real pilot flag) |
| 70b2511 | merge | origin/main merged in (brand rename #122, marketplace/memory provenance #130); bundle rebuilt inside the merge so the tree is self-consistent |
| 662675b | review | the two review findings fixed red-first: the approved screen's CTA resolves a wizard-installed plugin (installed-record fallback in the marketplace id lookup; Discover unchanged), and an unconfirmed `main` instance keys under the plugin id so its setup card never vanishes between pick and confirm; both setup surfaces now offer the explicit outside-workspace acceptance the API already had |
| 8e2fcb3, 99dc013 | #115 piece | the license manifest and its generator name the fonts the bundle actually ships (Geist, Geist Mono, Montserrat; the #121 font swap left them naming the Source/Plex set the tokens test has guarded since); committed bundle refreshed |

## Review findings and their disposition

The binding pre-merge review returned FAIL with two findings, both fixed red-first in
662675b: (1) the approved screen's CTA dead-ended at a marketplace 404 because
wizard-installed plugins are not catalog entries; resolution now falls back to a
catalog-shaped entry synthesized from the installed record for a requested id, without
changing the Discover listing (one deliberate consequence: install/update POSTs for such
an id now refuse 409 install:source-unavailable instead of 404). (2) An unconfirmed
`main` instance keyed `plugin~main` while its card rendered id `plugin`, so the setup
card vanished between pick and confirm (and permanently on abandonment); keys now mirror
the card rule, confirmed `main` keeps `<plugin>~main`. The review also surfaced that no
UI called the accept-outside endpoint, so an outside-workspace file dead-ended at the
confirm error; both setup surfaces now offer the explicit acceptance the API already
had.

## Verification

- Backend: the full pytest failure set on the branch is **byte-identical** to the set on
  origin/main at 0f8d007 (24 failures on both, measured by running the same suite in a
  clean worktree at origin/main and diffing the FAILED lists; the branch passes 29 more
  tests than main, its new ones). The 24 are the pre-existing debt owned by issue #115
  (registry library hash mismatches, fresh-desk pins, catalog bundle ids, marketplace
  walkthrough, registry hardening root doc, server shell rail markings, sources v2
  payload, start-cmd labelling). No branch-introduced failures.
- Frontend: tsc clean; the full vitest suite green (245 tests including the dev-proxy
  scan and the tokens test).
- Local CI gate (tools/ci_local.py): 4/6 gates pass; the two failing gates (pytest,
  registry-ci) fail identically on origin/main and the branch. The licenses gate, red on
  main, is green on the branch after 8e2fcb3.
- Demo walkthrough: runs headless; passes all non-registry-install steps; the two
  registry-install steps stop on the same pre-existing install:hash-mismatch debt.
- Committed SPA bundle rebuilt from the merged frontend source; no new third-party
  dependencies.
