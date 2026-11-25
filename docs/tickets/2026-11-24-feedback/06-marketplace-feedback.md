# 06: Feedback on the marketplace

**What to build:** every marketplace control that starts async work shows it started, every refetch keeps what the reader is looking at, and a session that has expired stops offering a Try again that cannot succeed. The admin signed-policy import, the plugin detail lifecycle buttons, the installed-row actions and the marketplace search take the shared busy state. A filter change dims the current results instead of replacing them with skeletons. A 401 becomes a session notice, not "did not load". The "cannot run on this desk" notice and the Installed page state from ticket 04 appear here too.

**Blocked by:** 01, 04.

**Status:** in progress.

- [x] The admin signed-policy file import shows the busy state while the file is parsed and verified, and a refusal keeps the chosen file and the typed state that belongs with it.
  - Verified: frontend/src/test/feedback-marketplace.test.tsx (signed-policy import busy and diff placeholder); frontend/src/marketplace/Admin.tsx keeps the parsed bundle and the chosen file until a later success.
- [x] The plugin detail lifecycle buttons (install, update, consent, disable, retest, rollback, purge, uninstall) show the F1 busy state, not only a disabled attribute.
  - Verified: frontend/src/test/feedback-marketplace.test.tsx ('names each plugin detail lifecycle action while it runs').
- [x] The installed-row actions (Enable, Disable, Share, Roll back, Purge data, Uninstall, Review update) show the F1 busy state.
  - Verified: frontend/src/test/feedback-marketplace.test.tsx ('labels the installed row action and marks the row busy while it runs').
- [x] The marketplace search submit shows the busy state or the region's placeholder from the first moment the catalog request starts.
  - Verified: frontend/src/test/feedback-marketplace.test.tsx ('disables Search and names it while the searched catalog reloads').
- [x] A filter or search change keeps the current results on screen, dimmed, instead of replacing them with skeletons; one indicator is shown for the catalog region.
  - Verified: frontend/src/test/feedback-marketplace.test.tsx ('keeps the catalog results dimmed and busy while a filter refetches...').
- [ ] A 401 becomes a session notice with the next step and no Try again that cannot succeed.
  - Not done: frontend/src/marketplace/MarketplaceApp.tsx SessionNotice still renders a Try again that calls window.location.reload(), and frontend/src/test/feedback-marketplace.test.tsx asserts it is enabled; a reload cannot renew an expired session.
- [x] Any other catalog failure still offers a Try again that can succeed and keeps the chosen filters.
  - Verified: frontend/src/marketplace/CatalogPage.tsx keeps its filter state and retries with the same filters; frontend/src/test/marketplace-discover.test.tsx ('shows the error, then recovers on retry').
- [x] The "cannot run on this desk" notice appears before install and on the Installed page, and Remove is the offered action.
  - Verified: frontend/src/test/review-marketplace.test.tsx (detail and consent notice) and marketplace-cannot-run.test.tsx (Installed Remove only).
- [x] No marketplace page blocks while a detail, pack or catalog request is in flight.
  - Verified: each page renders its shell and a shaped placeholder while a request is held (frontend/src/test/feedback-marketplace.test.tsx).
- [ ] Component tests cover the busy states, the dim-and-keep filter change, the 401 session notice and the absent Try again on 401.
  - Partly: frontend/src/test/feedback-marketplace.test.tsx covers the busy states, the dim-and-keep filter change and the 401 session notice, but its 401 test asserts a Try again is present, not absent.
- [ ] `python tools/ci_local.py` passes 7/7.
