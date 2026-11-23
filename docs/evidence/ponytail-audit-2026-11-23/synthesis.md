# Synthesis: Agent Desk audit at 6bb5bbb

What this audit does: reads the product against its own promise (PRODUCT.md: six cards, a morning loop, a non-technical user, week-4 success = opens 4/5 days, one self-built plugin, zero IT incidents) and classifies every top-level surface as live, buried, inert, or demo-only. 71 commits and 192 files since the 2026-11-21 remediation (465884f). Area reports: sources.md, surfaces.md, intelligence.md, server-core.md, frontend.md, tooling.md.

Spot-verified by the lead at 6bb5bbb: #1-#7, #11, #13, #15 (source read; no execution). The rest are code-read by area auditors with file:line evidence.

## Surface classification

| Surface | Verdict | Evidence |
| --- | --- | --- |
| Dashboard (SPA Brief) | live | Brief.tsx:530; six cards render |
| Customize bento | inert for builtins | Dashboard.tsx:539-569; Brief ignores layout for builtins (Brief.tsx:119-122) |
| Server dashboard fallback | buried | app.py:2287-2296 serves SPA first; pages.py:934-1053 unreachable in shipped tree |
| Inbox | live | inbox_view.py; accept/dismiss JS at pages.py:544-557 |
| Assistant | buried | render_assistant_page pages.py:83; empty composer |
| Agents | live | app.py:2428-2436; roster plus run |
| Memory | live | memory_view.py 22KB; graph/loop islands |
| Mail | buried | needs terminal export; plugins/execute.py:1053 |
| Marketplace | live but oversized | 23 TSX files, 27KB CSS, 3 plugins |
| Settings | live but unstructured | 16 sections one page, settings_view.py:1164-1274 |
| Activity | redirect-only | 302 to Settings, activity_view.py |
| Capabilities | buried | no rail entry outside Settings |
| Peers | inert | no href, tests pin hidden, starts UDP discovery (test_peers_surface.py:95-98) |
| Wizard | buried | one dashboard form, no nav; wizard_view.py:52 points at dead /plugins |
| Presentations | buried | only POST /agents/run, app.py:2454-2455 |
| Trust + marketplace admin | inert | registry index has no signature; admin env-gated (marketplace/api.py:740-751) |
| Demo walkthroughs | demo-only | tools/demo_walkthrough.py 1,021 lines; scripts/marketplace_walkthrough.py 442 |

Counts: live 6, buried 5, inert 3, demo-only 2, redirect 2.

## Must fix

1. **The Decisions cell collapses at the target viewport.** What: the SPA lost the legacy action wrapper. Problem: index.css:642 .decisions li is a non-wrapping flex row and Brief.tsx:486-500 puts the buttons straight into the li (legacy pages.py:956-960 wrapped them in .decision-actions), so a long title leaves .decision-text about 25px wide at 1264x805, one word per line, row 566px. Fix: flex-wrap:wrap and flex:1 1 180px on .decision-text. If skipped: the fourth card is unreadable on the laptop the user actually uses.

2. **The inbox Accept button lies and destroys the card.** What: inbox_view.py:43-46 labels the accept button with card.action_label ("Prep in Assistant" for a recommendation) while pages.py:545-547 posts /accept. Problem: clicking "Prep in Assistant" consumes the card instead of opening Assistant; the action the label promises never happens. Fix: split the affordance, label the accept button "Accept" and render the action label as the link with context. If skipped: the primary inbox gesture silently discards the suggestion.

3. **Customize edits a second dashboard.** What: builtin hide/rename/reorder save /api/layout, but Brief renders the six cards from hardcoded titles and only orders plugin cards (Brief.tsx:119-122). Problem: rename Sales to X, press Done, the dashboard still says PIPELINE in the old position; the customization is a no-op the UI claims works. Fix: Brief renders builtins from layout, or delete the builtin controls from Customize. If skipped: the user's one personalization gesture does nothing.

4. **The learned profile never reaches ranking.** What: rank.py:202-206 calls learned_lines on server.learned_profile, but LearnedProfileStore has no such method (profile.py only has module-level learned_lines(document)). Problem: always returns [], so a user who taught the desk topics still gets cold-start scores; the "personal" intelligence never reaches Pipeline/Moves/Decisions. Fix: one line, learned_lines(profile.document()). If skipped: the product's core differentiator is inert.

5. **One malformed reply permanently disables ranking.** What: rank.py:183-193 audits ok and remember_input even when parse_reply returns []. Problem: the next pass sees an unchanged payload and skips forever (:159); snoozed cards stay in build_input, so a below-threshold card returns tomorrow with the rule why and is never re-scored. Fix: remember input only when scored is non-empty; exclude snoozed cards. If skipped: one bad model reply freezes the recommendation engine for that card set.

6. **Stale workbook money is shown as current.** What: watcher.py:283-297 keeps delta when state becomes stale; Brief.tsx:105-113 reads delta without checking state. Problem: a locked or unreadable workbook still shows "Net pipeline, last 24 hours"; only the DESK HEALTH row admits it. Fix: for any state except healthy/first, show the cause and Re-test instead of the KPI. If skipped: the flagship card presents old money as today's.

7. **Origin "null" bypasses the write guard.** What: guard.py:88-91 treats Origin: null as missing on every mutating route. Problem: cookies are not port-scoped and SameSite compares scheme+domain, so another server on 127.0.0.1:<other port> can frame the desk in a sandboxed iframe; the cookie rides, Host passes, and POST /settings/toggle or /memory/* is accepted. The docstring only reasons about cross-site. Fix: reject null Origin on POST, or require a per-session CSRF token on mutations. If skipped: any local web page can flip settings or write memory.

## Should fix

8. **Dismiss is silent and irreversible in place.** What: Brief.tsx:177-180 awaits postJson and only refetches on ok; no catch, no error, no undo. Problem: a 500 or offline click looks like nothing happened; the only restore is inbox_view.py:143-154 after all waiting cards (prior audit: y≈3867 after eight cards). Fix: show inline failure, optimistically remove with Undo, and link the dismissed shelf. If skipped: "Not now" reads as broken.

9. **Decision links carry no context.** What: recommend/rules.py:72-73 sends every deadline to the generic /agents roster; rules.py:125-126 sends meeting prep to an empty /assistant. Problem: subject, date and cited facts never travel, so the user retypes what the card already knew. Fix: carry the card id/title in the link and prefill the destination. If skipped: every accepted suggestion costs a retype.

10. **The only card controls live inside Customize.** What: check-off, re-test, skill-run and source chips render in CommitmentsCard.tsx:104-142, SalesCard.tsx:82-95, SkillsCard.tsx:20-35, ResearchCard.tsx:62-71, which only mount in the customize bento. Problem: checking off today's commitment from the normal dashboard is impossible. Fix: surface these in Brief's hero/digest/health. If skipped: the daily jobs require entering a layout editor.

11. **Four endpoints and two registry paths have no user.** What: /widgets/sales-24h (routes.py:151), /widgets/inbox (171), /audit/tail (176), GET+POST /api/preferences (187,208); /api/registry (app.py:5637-5646) and /api/registry/install (5725-5807); _plugins_page_action (5648-5693). Problem: tests keep them green, no frontend calls them; /plugins 302s to the marketplace and the SPA does install/enable/disable, so the nine lifecycle branches are dead. Fix: delete with their tests. If skipped: the maintained surface keeps growing for nothing.

12. **Trust and marketplace admin govern nothing.** What: registry/index.json releases carry no signature or keyId; stage_registry_install is called without a trust store (app.py:5775-5777), and admin routes require AGENTDESK_MARKETPLACE_ADMIN=1 (marketplace/api.py:740-751). Problem: 1,404 trust lines never run for bundled plugins, and the admin UI's own copy admits signatures are not re-verified (api.py:65-67) while claiming no plugin runs without a policy decision (:80). Fix: cut trust-at-install and the admin/Studio paths until a signed registry exists. If skipped: security theater, and a second UI to maintain.

13. **Peers is unreachable but starts a listener.** What: peers_view.py:258, routes.py:170; no href="/peers" in src, and tests/test_peers_surface.py:95-98 pin it hidden and assert UDP discovery starts. Problem: 1,700 lines of pairing/discovery/sharing with no way in and no job in the six cards. Fix: delete the surface and the discovery thread. If skipped: dead code that opens a network service.

14. **Wizard is buried and points at a dead surface.** What: one dashboard form posts /wizard/start (Dashboard.tsx:502-504), no nav entry; wizard_view.py:52 still names a "Plugins surface" that 302s to /marketplace/installed. Fix: make the wizard the install/add-card path or cut it; fix the copy. If skipped: the only guided flow is unfindable and misdirects.

15. **Hosted CI runs 49 of 3,084 Python tests and no tsc.** What: enterprise.yml:158-163 runs 4 files; the frontend job runs npm run build + npm test but not npm run check; ci_local.py:20 calls tsc "the workflow's typecheck gate" while tests/test_ci_local_tool.py:70-84 certify that false claim. Problem: type errors survive esbuild, and agentloop/memory/server breaks merge green. Fix: run the full pytest suite (or shard it) and npm run check in the frontend job. If skipped: this audit's must-fixes are the predictable result.

## Nice to have

16. **Settings is one 16-section page with no index; the Activity log is last** (settings_view.py:1164-1274, activity at 1268). Fix: an index or tabs, activity near the top. If skipped: the user scrolls past Connections, Jobs, Endpoint, Updates, Registry and Skills to see what happened.

17. **116 of 326 vitest tests pin machinery, 52 pin CSS literals, 12 assertions are duplicated across stylesheets** (devproxy.test.ts, marketplace-router.test.ts, tokens.test.ts:174-180 whose block name says light while asserting dark/#060609). Fix: move the proxies/routers to smoke tests, assert computed styles once. If skipped: a 16px→17px title fails two tests and the suite stops describing the product.

18. **Dead weight is kept alive by its own test:** tools/demo_walkthrough.py 1,021 lines and scripts/marketplace_walkthrough.py 442 lines have no product caller, and tests/test_demo_walkthrough_exists.py pins existence. Fix: delete both and the pin. If skipped: 1,463 lines of demo scaffolding read as product.

## The five highest-leverage simplifications

1. **One dashboard, not three.** Delete the customize bento (SalesCard 237, CommitmentsCard 312, SkillsCard 65, CustomizeCell 174, Dashboard customize branch ~120, related CSS ~20) and the unreachable server dashboard/decisions renderers (pages.py:934-1053, ~600). Brief becomes the only composition; layout orders plugin cards only. Deletes ~1,600 lines and the "which dashboard am I editing" failure.
2. **Cut Peers.** peers_view.py 259, peers_api.py 667, peers module 797, routes and tests: ~1,700 lines, one listener, zero users.
3. **Cut trust-at-install and marketplace admin.** trust 1,404 lines plus the admin/governance half of marketplace/api.py (roughly 800-1,000): ~2,400 lines for a registry with no signatures and an env-gated admin.
4. **Core-ify the two real plugins and delete the storefront chrome.** excel-report and competitor-watch become built-in cells; delete Studio.tsx 439, Admin.tsx 582, Installed.tsx 418, PluginDetail.tsx 795 (with the marketplace CSS) and keep a minimal install for custom plugins: ~2,200 lines. The plugin engine (5,536) then shrinks to what two cards need.
5. **Cut presentations unless a card earns them.** writer 605, pipeline 296, ooxml 308, packs 143, fit 148, leak 124, render 119: ~2,000 lines, reachable only by POST /agents/run and needed by none of the six cards.

Cheapest flavor win, not a deletion: fix rank.py:202-206 and the two latch bugs (3 lines). The "personal" intelligence then actually reaches Decisions instead of a Digest paragraph.

## The Hermes gap

The stated architecture is "Hermes plus custom connectors for enterprise". In code there is no Hermes connection: 46 grep hits in src/agentdesk are all docstrings, comments, or licence headers; zero imports, zero calls. The only live references are two dead threat patterns that match ~/.hermes (safety/threat_patterns.py:137,139). docs/research.md:30 considered Hermes as Path B and did not implement it. Either Hermes is the intended backbone and the connector layer was never built, or the claim should be deleted; the plugin engine is the only connector path that exists, and it ships three demo plugins, two with cards.

-6,000 to -8,000 lines and 4 nav entries (Peers, Activity, Capabilities, marketplace admin) in phases 1-2. Up to -12,000 if one UI is chosen and the server pages are ported or deleted; that is a product decision, not a free cut. Current tree: ~56k Python, 66 TSX.

## Verdict

The morning loop is real but thin: four of six cards depend on a manual plugin install or a live workbook, and the personal layer is broken by one line. The convolution is not the six cards; it is three dashboard compositions, two UI stacks, a marketplace/trust/governance stack for three demo plugins, an unreachable peers network, and a claimed Hermes integration that does not exist in code. Cut the unearned surfaces, fix the seven musts, and the product gets back to one screen that answers what changed, what is due, what is worth reading, and what to do next.

Not checked: no browser run at 6bb5bbb (F1 pixels are from b2a1d51, structurally re-verified; shipped index-Ba4ndPsL.css has the same rules); full pytest not run (suite ~3,084, last full run 522s), tsc/vitest not run; the null-origin exploit is reasoned from SameSite/port scoping, not executed; enterprise connector requirements (systems, auth, read/write) not gathered; no product decision yet on whether Hermes is the intended backbone.
