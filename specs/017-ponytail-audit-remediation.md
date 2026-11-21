# Spec 017: Ponytail audit remediation

Status: ready-for-agent (2026-11-21). GitHub: issue #217; its body is the live
copy when the two disagree.

## Problem Statement

A full ponytail audit of every component of the desk, ten reports dated 2026-11-21, found roughly ninety defects and debts.

The verdict underneath them is good news: the product's core invariants hold. The security spine (loopback-only binding, the token bootstrap, the request gate, body limits) is the strongest and most tested part of the repo. The Class D guarantee holds with no escape found: the wizard's compiler emits data, the renderer stringifies through a whitelist, and no plugin path executes code. The memory bank's crypto and deterministic ranker, the metadata-only mail record, and the canonical JSON signer were each verified excellent. Nothing the audit found argues for a new abstraction, a new option, or a new dependency.

Around that spine, three layers of damage:

- **Binding-constraint violations.** The pressed-card JSON route spends model calls and stages inbox cards with no audit row, so the IT review's CSV export silently omits exactly the calls and decisions the review depends on. The lethal trifecta (file-reading widgets get no network) is broken structurally by one reader: a manual-metric source can open a workspace file the manifest never declared, inside the same plugin as a network widget. The Install button, unlike Update, applies a scope-widening release with no consent screen and destroys rollback history in the same click. And the trust plane can fail open: a corrupt anchor silently resets the key pins to trust-any-key, a float inside a signed policy 500s every marketplace route instead of falling back, and the state files behind the kill switch, the anchor and the audit trail are written non-atomically, so a crash can erase an administrator's hard block with no warning anywhere.
- **User-visible bugs.** The repetition detector never runs: nothing schedules it, hooks it, or links to it, so a shipped capability is dead code behind an endpoint nobody addresses. The calendar bridge reads the UTC-shaped timestamps the sync flow actually writes as if they were local, so early and late meetings drop off "today" or show at the wrong clock time. Plugin action notices die in a double redirect, so publish confirmations and named refusals never reach the user. Customize mode's Hide and reorder are a silent no-op on the dashboard the user actually sees.
- **Accumulated lean debt.** Verified-dead code (an unreachable rendered plugins page, an unused activity renderer, rail icon constants the rail ignores, dead polling and budget helpers, a never-read column), duplicated helpers (eleven branches of one response shape, five copies of two tiny text helpers, three copies of the JSON state helpers), a seven-thousand-line server module accreting five unrelated jobs, and binding design documents that describe a visual system the code and the token tests both rejected.

## Solution

A prioritized remediation in eleven workstreams, each landing as its own PR with the gate green and evidence attached: trust state, plugin lifecycle, the audit trail, memory bookkeeping, source correctness, gate integrity, unknown routes, naming and copy, the nudges budget, frontend fixes, and a lean sweep that lands last, after the first ten.

Every fix is the ponytail fix, the same lens the audit used: the smallest complete change at the seams that already exist, no new options, no new frameworks, no new dependencies. The never-cut list is enforced, not eroded: validation at trust boundaries, error handling that prevents data loss, security, and accessibility all come out stronger.

## User Stories

1. As the manager, I want a broken signed policy to fall back to the curated default with a visible warning, so that one hand-edited value never takes the marketplace down.
2. As the technical owner, I want the kill switch, the anchor and the audit state written atomically, so that a crash mid-write can never silently erase the administrator's hard block.
3. As the technical owner, I want a corrupt anchor to fail closed with a warning, so that a damaged pin store never becomes trust-on-first-use for any key.
4. As an IT reviewer, I want the unsigned policy overlay unable to set signature status or source, so that no page can claim a signature nobody verified.
5. As an IT reviewer, I want the audit listing behind the same admin gate as the export, so that admin mode off means nothing is served, on both reads.
6. As the manager, I want installing a newer release over an installed plugin to hold for consent when the scope widens, so that the Install button cannot grant what the Update button would ask for.
7. As the manager, I want version history and pilot state kept across that install, so that rollback still works and the pilot badge does not restart.
8. As the manager, I want the plugin lockfile written atomically, so that a power loss mid-write cannot brick every plugins route.
9. As the technical owner, I want peer bundle extraction capped, so that a small bundle with one huge member cannot spike the laptop's memory.
10. As the technical owner, I want rollback to re-verify the prior release digest against the history pin, so that a tampered older tree cannot be certified by the lock.
11. As an IT reviewer, I want a manual-metric file read refused in combination with network access, so that the lethal trifecta holds structurally again.
12. As the manager, I want the wizard to actually build the JSON-file and web-page source kinds it offers, so that picking its own menu options never dead-ends.
13. As the manager, I want the pilot badge on my first five runs of a new plugin, so that the badge matches the interaction document.
14. As the technical owner, I want a dedicated escape-review pass over the plugin card renderer, so that the heaviest plugin-string boundary gets the audit it was flagged for.
15. As an IT reviewer, I want the pressed-card JSON route to write the same audit rows its no-JS twin writes, so that the export covers every model call and staged card whichever door the SPA uses.
16. As an IT reviewer, I want a refused press recorded with an error status, so that a log reader cannot call a refused press a working one.
17. As an IT reviewer, I want the what-this-touches table to cover every action the app can record, so that the one-page review under-describes nothing.
18. As the manager, I want a failed explanation to keep the endpoint's named cause, so that the recovery action is named instead of discarded.
19. As the manager, I want undo to refuse when any removed row's id has been reused, so that undo can never wire a fact to the wrong entity.
20. As the manager, I want a merge to delete the absorbed entity's consolidated observation and rebuild the survivor's at once, so that the page never states a conclusion the bank no longer supports.
21. As the manager, I want deleting a superseding fact to release the fact it pointed at, so that recall returns the older true value instead of skipping it forever.
22. As the manager, I want a corrupt memory key named as corrupt, so that I look for the right recovery instead of a file that exists.
23. As the manager, I want calendar events normalized to my local time before the today window is computed, so that early and late meetings count and show at the right clock time.
24. As the manager, I want mail self-detection to use my configured address against the address inside the From header, so that threads I already answered stop producing follow-up cards.
25. As the manager, I want the workbook shadow copy to drop the source's read-only attribute, so that a read-only workbook is not a permanently locked card blaming an open Excel.
26. As the manager, I want a degraded generic breakdown retried rather than cached, so that one endpoint outage does not freeze the fallback forever.
27. As the manager, I want malformed workbooks and calendar files to land in the designed amber state with a cause, so that a torn file never becomes the generic error page.
28. As the manager, I want old source snapshots pruned after seven days, so that the data directory does not bloat forever.
29. As the manager, I want the first worksheet resolved by workbook order, so that a tab reorder does not silently change which sheet the delta reports.
30. As the manager, I want the workbook path chosen only with the native picker, so that the product keeps its no-typed-paths promise.
31. As the technical owner, I want the local gate to check every file even in worktree checkouts, so that a zero-file pass can never read as a green light.
32. As the technical owner, I want the registry append-only history check running in automated CI, so that a refactor cannot break pinned desks with every light green.
33. As the technical owner, I want the registry risk tier to see optional network permissions, so that the one network plugin is not indexed as low risk.
34. As the manager, I want the launcher's Python-not-found message to stay on screen, so that the one failure I cannot fix myself is at least readable.
35. As the technical owner, I want the local license leg watching the authoritative SBOM chain, so that a local green means what the hosted green means.
36. As the manager, I want unknown skill and wizard addresses to answer not-found pages, so that a stale link is a client error, not a "restart the app" page.
37. As a developer, I want the redirect helper to set the responded flag its twin sets, so that a later failure can never answer twice over a finished redirect.
38. As a developer, I want deprecated alias routes to carry a named release or be deleted, so that "one release" finally falls due.
39. As the manager, I want every surface to say Agent Desk, so that no page tells me to open a product that does not exist on my machine.
40. As the manager, I want plugin action results to survive into the page I land on, so that publish confirmations and named refusals actually reach me.
41. As a screen-reader user, I want the wizard's free-text fallback input to carry an accessible name, so that a degraded session never announces an unnamed field.
42. As the manager, I want the repetition detector to actually run, so that five similar asks produce the skill proposal the product promises.
43. As the manager, I want accepting a brief to prevent twins, so that an acknowledged meeting never costs another notification.
44. As the manager, I want a bad window-hours payload rejected at the boundary, so that one malformed card cannot take down every page that shows the rail count.
45. As the manager, I want undoing a skill to start the same cooldown as dismissing its proposal, so that the desk does not re-ask what I just declined twice.
46. As the manager, I want the dismissed shelf to purge past the recovery window, so that restore buttons that cannot work are never shown.
47. As the manager, I want Customize hide and reorder to change the dashboard I actually see, so that the click is the truth.
48. As the manager, I want the tracker setup sheet to show its error and unblock when the server is unreachable, so that a restart mid-setup is not a silent wedge.
49. As a keyboard user, I want the destructive dialogs to take focus, trap Tab, answer Escape and restore focus, so that uninstall, rollback and purge are keyboard-complete.
50. As the manager, I want my card renames kept in every card state, so that the name does not revert exactly when the source misbehaves.
51. As the manager, I want truncated labels to carry a tooltip, so that the full text is always reachable.
52. As a developer, I want the two near-copy setup sheets merged, so that their error guards cannot drift again.
53. As a developer, I want the verified-dead code deleted, so that every future reader has less to rule out.
54. As a developer, I want the response, text and JSON state helpers each merged to one owner, so that a contract change is made once.
55. As a developer, I want the server application module split by job, so that whole features stop accreting into one class.
56. As a contributor, I want the design-language documents to describe the shipped three-theme system, so that following the contract does not fail the token tests.
57. As the technical owner, I want the peer-catalog doc claim to match what ships, so that the sharing story tells the truth.

## Implementation Decisions

Eleven workstreams. Each lands as its own PR with the gate green and evidence attached; the order below is priority by promise broken, and workstream 11 lands last, after 1 through 10. Items are lettered so remediation PRs can cite exactly what they fix (for example 4c).

1. **Trust state (marketplace and signed-policy robustness).**
   - a. A signed-looking policy whose body cannot be canonically serialised (a float in a value) is rejected through the same path as a bad signature: amber fallback to the curated default with a warning, never a 500 on every marketplace route.
   - b. Kill-switch, anchor and audit state files write atomically: temp file in the same directory, then replace.
   - c. A present-but-corrupt anchor fails closed with a warning: no key is trusted, never a silent reset of the pins to trust-any-key; "exists but unreadable" and "never existed" mean opposite things and are answered differently.
   - d. The unsigned policy overlay can no longer set signature status or source; those fields are loader-owned, exactly as the signed path already treats them.
   - e. The audit listing endpoint gets the same admin gate the export already has, so admin mode off closes both audit reads.
   - f. One shared JSON read/write helper replaces the three copies, and it is the one place writes are made atomic (1b).

2. **Plugin lifecycle.**
   - a. An install over an already-installed plugin runs the same scope-diff consent check the update path runs: a widening release holds for consent instead of applying silently.
   - b. That install keeps version history (rollback still works) and keeps pilot state (the badge does not restart).
   - c. The plugin lockfile writes atomically, so a crash mid-write cannot leave every plugins route broken with no designed amber state.
   - d. Peer bundle extraction caps decompressed size per member, refusing with the existing unsafe-zip code.
   - e. Rollback re-verifies the prior release digest against the history pin before repointing the lock.
   - f. The validator closes the manual-metric gap: a relative file read on a manual-metric source, combined with network in the same plugin, is refused, restoring the lethal trifecta structurally (the file stays a display hint unless it is plugin-data-rooted).
   - g. The wizard's deterministic composer actually builds the json-watch and http-get source kinds it advertises: a default selector for json-watch, and http-get composed like the config-backed workbook case (no read globs, url and allow parsed from the answers). Picking an offered option must never dead-end in a validator code.
   - h. The pilot badge covers the first five runs, per the binding interaction document.
   - i. A dedicated escape-review pass over the plugin card renderer, the heaviest plugin-string boundary, which this audit cycle flagged as under-audited; its findings feed tickets under this spec.

3. **Audit trail.**
   - a. The pressed-card JSON route writes the same audit rows its no-JS twin writes: the model spend and the staged card are both recorded, on success and refusal.
   - b. A refused press is recorded with an error status, not the success default.
   - c. The IT action vocabulary behind the what-this-touches page covers every action the app can record, the press included, so the generated table cannot under-describe the machine.
   - d. A failed explanation keeps the endpoint's named cause in its note instead of collapsing to the generic line.

4. **Memory bookkeeping.**
   - a. Undo refuses id reuse for entities, sources and observations, not just facts, so a restore can never wire rows to a new owner of a recycled id.
   - b. Entity merge deletes the absorbed entity's consolidated observation and reconciles the survivor's inside the same transaction, so no orphaned derived text outlives the merge.
   - c. Deleting a superseding fact releases the dangling pointer (repoint to the survivor, or clear), so recall returns the older true value instead of skipping it forever. Both delete paths that can strand the pointer (edit-merge and the startup dedupe) get the release the removal path already has.
   - d. A corrupt key file names its true cause ("exists but is not a valid key"), distinct from missing, because the recovery action starts from the named cause.

5. **Sources correctness.**
   - a. Calendar timestamps normalize to local at the parse boundary, before today-windowing, week load and display; the UTC shape the sync flow actually writes is the case that must work.
   - b. Mail self-detection compares the configured address, extracted from inside the From header, not a placeholder against the whole header; the user's address becomes one settings field next to the mail folder.
   - c. The workbook shadow copy does not inherit the source's read-only attribute, so a read-only workbook is not a permanent locked card with a false cause.
   - d. A cached generic breakdown is not permanent: fallback answers are retried on the next poll or retest, real answers stay cached.
   - e. Snapshots prune after seven days: nothing reads a snapshot older than the 24-hour reference, and each source's poll history stops growing forever.
   - f. Corrupt shared-string indexes and non-dict calendar events degrade to the designed amber state with a cause, not the generic 500 page; file input is a trust boundary.
   - g. The first worksheet resolves by workbook order (the declared sheet order), not by archive member name, so a tab reorder does not silently change which sheet the delta reports.
   - h. The typed workbook-path fallback is removed: the picker is the contract, and a picker failure gets its own honest amber state instead of teaching the banned behavior.

6. **Gate integrity.**
   - a. The local gate relativizes path exclusion before testing it, so worktree checkouts get full coverage (the skip is proven to check zero files today), and the grammar gate fails on an empty file set.
   - b. The grammar floor covers the scripts tree as well.
   - c. The append-only registry history check runs somewhere automated: hosted CI gains the registry job (same tool, so the validator stays byte-identical), and the local gate passes the base index the history check needs.
   - d. The registry sync indexes network-allowance risk from optional permissions as well as required ones, so the one network plugin is tiered honestly; the index is regenerated after the fix.
   - e. The launcher's Python-not-found message pauses on the failure path only, like the probe launcher does, so the person it was written for can read it.
   - f. The local licenses leg watches the authoritative SBOM chain (SBOM, license gate, notices check), and once it does, the legacy hardcoded license manifest and its tool are deleted.

7. **Unknown routes.**
   - a. Unknown skill and wizard subpaths answer 404, using the same parse-guard pattern the memory routes already use.
   - b. Unknown wizard actions surface the store's own not-found error instead of the generic "restart the app" page, and the test that pins today's 500 is corrected to pin the 404.
   - c. The redirect helper sets the responded flag its 302 twin sets, so a later failure can never answer twice over a finished redirect.
   - d. Deprecated alias routes get a named release or deletion now: "stays for one release" with no named release never falls due, and any SPA call to an old address moves first.

8. **Naming and copy.**
   - a. User-visible copy says Agent Desk everywhere; the Nexuus Bot strings, including the README title, are bugs against the binding name.
   - b. Plugin action notices actually reach the user after the SPA redirect: the POST targets the page that renders the notice (or the SPA surfaces the cause from its own API), so publish confirmations and named refusals stop dying in the double redirect.
   - c. The wizard's free-text fallback input carries an accessible name (the question text it sits under).
   - d. Pressed-card refusal statuses shown to the user match the error convention the rest of the desk follows.

9. **Nudges budget.**
   - a. The repetition detector actually runs: one guarded consolidation call inside the existing briefs evaluation hook, the same catch-up-on-read pattern the inbox already uses; no scheduler, no timer thread.
   - b. Accepting a brief card prevents the twin: the one-brief-per-meeting rule counts accepted cards, by reading the meeting id field the cards already carry instead of scanning serialised metadata.
   - c. Window hours validate at the trust boundary (the card constructor), so a bad payload answers 400 at the API instead of a 500 on every page that shows the rail count.
   - d. The daily cap spend is atomic under concurrency: one serialized store method decides and spends inside the same lock, so two near-simultaneous loads cannot overspend the day.
   - e. Skill undo starts the existing dismiss cooldown before deactivating, so an undone skill is not immediately re-proposed.
   - f. The dismissed shelf purges past the retention window instead of listing restore buttons that answer gone.

10. **Frontend fixes.**
    - a. Customize hide and reorder actually apply: the normal view reads the layout and filters and orders its cells by it, and the server honors the layout for plugin cards; reorders and hides hold after Done.
    - b. The tracker setup sheet degrades visibly when the server is unreachable: the existing error slot fills, busy clears, and the sheet stays operable.
    - c. The four destructive dialogs (uninstall, rollback, purge in both surfaces that carry them) get the consent sheet's focus contract: focus moves in, Tab is trapped, Escape closes, focus is restored, via the shared focus hook the consent sheet already implements.
    - d. Card titles keep user renames in every card state, including the states the source enters when it misbehaves.
    - e. Truncated labels carry title attributes, so a long or translated name is always readable in full.
    - f. The two near-copy setup sheets (the dashboard tracker sheet and the marketplace instance sheet) merge into one shared walk with app-specific slots; the drifted error guards come along, which is the point.
    - g. Dead exports delete.

11. **Lean sweep (lands last, after 1 through 10).**
    - a. The roughly 700 lines of verified-dead code delete: the unreachable rendered plugins page (after 8b fixes the notice flow), the unused activity renderer, the rail icon constants the rail ignores, the dead polling helpers, the dead budget helpers, and the never-read column.
    - b. The eleven-branch form-versus-JSON response helper merges to one.
    - c. The server application module splits by job exactly twice: the memory api block and the peers api block move out as pure code movement behind their existing test suites; routing, gate and bootstrap stay. Stop after two moves.
    - d. The five copies of the count/plural/bounded text helpers merge.
    - e. The design-language documents are rewritten to tell the truth of the shipped three-theme Geist system; the code and the token tests are the reality the docs must match.
    - f. The peer-catalog claim in the docs aligns with what ships: the merge path stays, the sharing claim goes unless it is already true.

## Testing Decisions

- Every fixed bug ships with the one test that fails without the fix. The audits name the missing tests; those are the tests to write, attached to the fixes, not coverage for its own sake.
- Existing seams only, the highest one available: the server harness (real server on a real socket) for route behavior, status codes and audit rows; the stores directly for bookkeeping (undo id refusal, merge reconciliation, supersession release, cap atomicity, shelf purge, snapshot pruning); the validator harness for the trifecta refusal and wizard compositions; the SPA test stack for frontend behavior. No new seams, no new test frameworks, no new dependencies anywhere.
- Prior art in the repo: the agents suite's audit-row assertions, the marketplace signed-policy and trust suites, the memory loop and store suites, the briefs and repetition suites, the registry hardening suite, the wizard view script-tag test, the customize, cards, marketplace-a11y and tokens frontend suites, and the walkthrough contract tests.
- The audits' named gaps that become tests here: press audit rows on both doors (JSON and page) and the refusal status; undo id-reuse per table; merge with observations on both sides; the superseding-fact edit release; the calendar offset with a local now; mail self-detection with a display-name header and a configured address; the shared-string and non-dict-event ambers; the second poll of a read-only workbook; breakdown recovery after the endpoint returns; the float, corrupt-anchor, overlay-forgery and admin-gate trust tests; the accept-twin and undo-cooldown regressions plus the quiet-hours boundary pins; the end-to-end no-JS plugin action notice; the wizard no-options render; the optional-network risk tier fixture; the rollback digest re-verification; the customize return-to-normal view, the dialog focus walk, and the unreachable-server setup sheet.
- Each workstream PR lands with the gate green. The gate-integrity workstream is verified by the gate itself: the empty-file-set failure and the registry job prove their own fixes.

## Out of Scope

- Streaming assistant responses (a deferred product decision).
- Mail-context briefs (blocked on the IT DLP decision; briefs stay calendar-only).
- Autostart persistence (blocked on Security sign-off in writing).
- Spec 016's open tickets (a separate initiative; nothing here touches them).
- The dev-only npm advisories in the test toolchain (a scheduled toolchain bump; no product surface).
- Any refactor of code the audits verified excellent: the security spine, the Class D chain and the shared-validator mechanism, the memory crypto and the deterministic ranker, the metadata-only mail record, the canonical JSON and Ed25519 verifier (the Ed25519 replacement stays opportunistic, only when that module is next touched for other reasons), and the recorded personal-scale divergences of the memory bank.

## Further Notes

- The full audit pack lives outside the repository, in ponytail-audit-2026-11-21/ next to the repo: ten reports (intelligence, server core, server views, sources, nudges, plugins, distribution, memory, frontend, tooling), roughly ninety ranked findings, each reproduced on a worktree or traced to an exact input, plus per-component architectural-decision reviews and lean estimates.
- The top claims were spot-verified in code before this spec was cut; every checked claim confirmed.
- Remediation PRs cite the finding they fix by workstream letter (for example 4c) and, where useful, the audit report and finding number from the pack.
- The remediation honors the ponytail lens the audit used: smallest complete change, and the never-cut list (validation at trust boundaries, error handling that prevents data loss, security, accessibility, anything the user asked for) is never cut to make a diff smaller.
- Workstreams are independently landable and priority-ordered; the lean sweep lands last because two of its deletions depend on earlier fixes (the rendered plugins page waits on 8b, the legacy license manifest on 6f).
