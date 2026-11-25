# 04: Honest cards

**What to build:** the home screen and Desk health list only what this desk can actually run. A plugin that contributes no widget has no tile and no health row. A plugin whose source needs the network says so in reader language, offers Remove as its only action, stays off the home screen, and is named in the marketplace before install and on the Installed page. Desk health shows the three desk sources with a counter that counts those rows, then the plugins that feed a tile as a second labelled group with its own count. A plugin that never ran says "never". Unknown plugin kinds stop wearing the DIGEST tag. The digest survives a malformed event date.

**Blocked by:** 01.

**Status:** done (2026-11-24).

- [x] A widget-less plugin (the shipped presentation-starter) has no home-screen tile and no Desk health row, and its setup card stays wherever setup is shown.
  - Verified: registry/plugins/presentation-starter/manifest.json has zero widgets; src/agentdesk/server/dashboard_state.py dashboard_plugin_cards drops no-widget cards; tests/test_ui_text_fit.py::test_a_plugin_with_no_widget_keeps_no_card_but_stays_installed.
- [x] A network-only plugin (the shipped competitor-watch) has no home-screen tile.
  - Verified: tests/test_ui_feedback_review.py::test_a_network_plugin_without_a_transport_gets_no_dashboard_card and tests/test_ui_text_fit.py (the card filter).
- [x] Where that plugin is reached (Plugins, detail, Installed), it says "This desk cannot read web pages yet" and offers Remove as its only action; there is no Re-test.
  - Verified: frontend/src/test/marketplace-cannot-run.test.tsx ('shows the state with Remove as the primary action and no Re-test') and the Installed row assertion.
- [x] The marketplace says before install, on the card, the detail page and the consent sheet, that the plugin cannot run on this desk.
  - Verified: frontend/src/test/review-marketplace.test.tsx (detail and consent notice) and frontend/src/test/marketplace-cannot-run.test.tsx (catalog card chip).
- [x] The Installed page repeats the state and offers Remove.
  - Verified: frontend/src/test/marketplace-cannot-run.test.tsx ('shows the state with Remove as the primary action and no Re-test').
- [x] Desk health shows the three desk sources with a counter that counts exactly those rows, and the plugins that feed a tile as a second labelled group with its own count.
  - Verified: frontend/src/test/brief-decisions.test.tsx ('counts the three desk sources and labels the plugin rows separately') and frontend/src/test/cards.test.tsx (the group's own count).
- [x] A plugin that never ran shows "never", not the current time.
  - Verified: frontend/src/test/brief-decisions.test.tsx and frontend/src/test/cards.test.tsx assert "never" for a plugin that never ran.
- [x] "Re-test now" appears only where a re-test can change the reading; it is absent from a no-widget plugin and a network-only plugin.
  - Verified: tests/test_ui_text_fit.py::test_the_legacy_plugin_card_offers_retest_only_when_it_can_change and frontend/src/test/marketplace-cannot-run.test.tsx (no Re-test).
- [x] An unknown plugin kind no longer defaults to DIGEST, each kind carries one word, and two different cells no longer carry the same tag for different reasons.
  - Verified: frontend/src/dashboard/pluginKind.ts and frontend/src/test/text-fit-dashboard.test.ts (an unknown kind is PLUGIN).
- [x] A malformed calendar event start does not throw: the digest card still renders, and the item keeps its title and detail.
  - Verified: frontend/src/dashboard/cells.tsx DigestList checks Number.isFinite; frontend/src/test/cards.test.tsx ('renders an untimed digest item instead of throwing on a bad date').
- [x] The Page watch placeholder no longer offers "Add a page" while this desk cannot read web pages; it keeps its wireframe and names the limit.
  - Verified: frontend/src/test/review-dashboard.test.tsx ('does not invite a page the desk cannot watch') and feedback-dashboard.test.tsx.
- [x] The filter that removes the two kinds of card runs once where both dashboard surfaces get their cards, so the SPA payload and the server page agree.
  - Verified: src/agentdesk/server/dashboard_state.py calls dashboard_plugin_cards once in build_dashboard_state; the API and the server page both read that state.
- [x] Component and server tests cover the filtered cards, the two health groups, the two counters, the word "never" and the marketplace notice.
  - Verified: tests/test_ui_text_fit.py, test_ui_feedback_review.py and frontend/src/test/brief-decisions.test.tsx, cards.test.tsx, review-dashboard.test.tsx, marketplace-cannot-run.test.tsx.
- [x] `python tools/ci_local.py` passes 7/7.
  - Verified: `python tools/ci_local.py` passed 7/7 on `2d00540` (127 s) and again on the head that was pushed, 7/7 in 117 s (pytest 3520 passed, 1 skipped; vitest 596).
