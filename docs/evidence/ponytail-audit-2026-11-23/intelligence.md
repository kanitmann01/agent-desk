# Intelligence audit (verified at 6bb5bbb, code read by audit-intel)

MUST FIX
1. src/agentdesk/recommend/rank.py:202-206 - _learned_lines calls learned_lines on server.learned_profile, but LearnedProfileStore has no such method (memory/profile.py only has a module-level learned_lines(document)). Always returns [], so the learned profile never reaches model ranking; a user who taught the desk topics still gets cold-start scores.
2. src/agentdesk/recommend/rank.py:183-193 - audit ok and remember_input run even when parse_reply returns [] (valid JSON array with ungrounded ids, bool score, or why > 140). Next pass hits "skipped":"unchanged" at :159 forever; one malformed reply permanently disables ranking for that card set.
3. src/agentdesk/recommend/rank.py:139,153,159 - apply_scores snoozes a below-threshold card, but build_input includes snoozed cards, so the payload is unchanged and the re-rank is skipped. The card resurfaces tomorrow with the rule why, never re-scored.

SHOULD FIX
4. src/agentdesk/server/dashboard_state.py:226-232 plus src/agentdesk/agentloop/loop.py:475-476 - the full desk check runs on every GET /api/dashboard and hourly; the SPA fetches once at frontend/src/App.tsx:68 and after every card action (SalesCard.tsx:5), so the retired-plugin scan (which creates an ask card) repeats per action and a GET mutates the inbox.
5. src/agentdesk/memory/profile.py - seal/unseal arguments are accepted but unused (docstring: "stay unused: the file is plaintext today"). profile.learned.json stays readable when memory is encrypted, while Settings shows it as learned personal data (settings_view.py:306-369).
6. src/agentdesk/server/app.py:6761-6923 - profile review latches profile:last_activity_id after each pass even when profile_review.apply drops every op (over-budget/ungrounded/threat). Once the store reaches BUDGET_CHARS=1375 (memory/profile.py), new learned lines stop with no error and no UI indicator.
7. src/agentdesk/insight/digest.py:430-436 - the only six-card surface showing learned lines is the Digest prose; the full view is Settings (settings_view.py:306-369); the decision-ranking consumer is broken by #1. "Personal" reaches a paragraph, not Pipeline/Moves/Decisions.
8. tests/test_recommend_rank.py:118-221 - tests cover parse/threshold/unchanged/unavailable, but none asserts payload["learned"] comes from the store. tests/test_learned_profile.py:210-213 tests the module-level function, masking #1. No test proves one loop pass yields a real suggestion.
9. src/agentdesk/server/app.py:2454-2455 - presentations are reachable only by POST /agents/run with agent="presentation" through the server-rendered Agents page (app.py:2428-2436); no React/deck surface exists (frontend grep: only role="presentation"). Roughly 2,000 LOC for a job none of the six cards needs.

NICE TO HAVE
10. src/agentdesk/peer* - /peers is a Settings-only page (frontend/src/Rail.tsx:105 comment) and needs a second desk; no six-card job. Pairing flow not exercised, so unverified whether it works end to end.

Verdicts: 8 live (insight attach, digest, memory capture, recommend builder, rank, Settings learned, ledger undo via audit_view.py:200, skills), 2 buried (presentations, peers), 1 inert seam (rank learned-lines), 0 demo-only.
Lean: about -3,000 lines possible (presentations ~2,000: writer 605, pipeline 296, ooxml 308, packs 143, fit 148, leak 124, render 119; peers ~800; profile-review wiring ~300; the #1 fix costs one line).
Not verified: peers pairing behavior, actual per-morning LLM call counts, load timings, presentation HTML UI wiring beyond its route.
