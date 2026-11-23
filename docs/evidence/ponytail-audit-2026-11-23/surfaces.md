# Surfaces audit (verified at 6bb5bbb, code read by audit-surfaces)

Surfaces: ~16 server views, 8 rail items, 16 Settings sections, 6 marketplace tabs. Verdicts: live 12, buried 5 (capabilities, activity trail, memory subpages, legacy dashboard fallback, marketplace admin/trust), inert 1 (peers), redirect-only 2 (/activity, /plugins), demo-only 0.

MUST FIX
1. SPA Decisions loses the legacy action wrapper: frontend/src/index.css:642 + frontend/src/dashboard/Brief.tsx:186-191, vs src/agentdesk/server/pages.py:959; long title+why cannot push actions to a new line, so the text column collapses (prior audit measured 24.6 px, row 566 px at 1264 px). The shipped index-Ba4ndPsL.css has the same rules, so it is live.
2. Inbox recommendation button is mislabelled and destructive: src/agentdesk/server/inbox_view.py:43-46 labels an accept button with card.action_label ("Prep in Assistant"), while src/agentdesk/server/pages.py:545-547 posts /accept; clicking it consumes the card instead of opening Assistant.
3. Decision actions carry no context: src/agentdesk/recommend/rules.py:72-73 sends every deadline to the generic /agents roster, and rules.py:125-126 sends meeting prep to an empty /assistant; subject, date and cited facts never travel, so the user retypes.

SHOULD FIX
4. Dismiss is silent and recovery buried: frontend/src/dashboard/Brief.tsx:177-180 posts dismiss + refetch with no undo, confirm, or aria-live; the only restore is src/agentdesk/server/inbox_view.py:143-154, after all waiting cards (prior audit: y≈3867 after eight cards).
5. "N more in inbox" cannot be opened: frontend/src/dashboard/Brief.tsx:195-197 and src/agentdesk/server/pages.py:984 render text, not a link; no total open count either.
6. Peers has no way in and starts a listener: src/agentdesk/server/routes.py:170, src/agentdesk/server/peers_view.py:258; no href="/peers" exists in src, pinned by tests/test_peers_surface.py:95-97, and a visit starts UDP discovery (test line 98). 259 view lines plus API and actions are unreachable.
7. Inbox primary actions need JS while the page claims no-JS: src/agentdesk/server/pages.py:544-557 binds [data-accept]/[data-dismiss], but src/agentdesk/server/inbox_view.py:43-46,101-103 emits buttons, not forms; with JS off, Accept and Dismiss do nothing (edit/snooze/more-info still submit).
8. Settings is one 16-section page with no tabs or index: src/agentdesk/server/settings_view.py:1164-1274; the Activity log is last at line 1268, after Connections, Jobs, Endpoint, Updates, Registry and Skills.

NICE TO HAVE
9. Inbox age has no date: src/agentdesk/server/inbox_view.py:36-38 prints only "Waiting since HH:MM"; a card from yesterday (30-day retention) reads as today.
10. The legacy dashboard fallback is unreachable in the shipped tree: src/agentdesk/server/app.py:2287-2296 serves the SPA whenever src/agentdesk/server/static/spa/index.html exists (it does), so src/agentdesk/server/pages.py:934-1053 runs only in a build-less checkout or tests; the two renderers already drifted (finding 1).
11. Wizard points at a "Plugins surface" that no longer exists: src/agentdesk/server/wizard_view.py:52; /plugins 302s to /marketplace/installed (src/agentdesk/server/app.py:1470-1484).
12. Plugin empty state takes a redirect hop: frontend/src/dashboard/PluginCardView.tsx:362,365 links /plugins -> 302.

Verdict: keep the six-card morning path; cut Peers outright, collapse the two dashboard renderers to one, make the action label and destination one object with context, and make dismissal recoverable in place.
Lean: -650 to -950 lines (peers view 259 + peers API/routes/tests est. 400 + legacy dashboard/decisions renderers ~125 + /activity redirect/vocab ~35).
Unverified: no fresh browser run at 6bb5bbb; F1/F2 pixel measurements are from the b2a1d51 audit, re-verified structurally in source and shipped CSS. Did not read peers_api.py or marketplace API bodies.
