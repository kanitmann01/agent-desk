# 06: Feedback on the marketplace

**What to build:** every marketplace control that starts async work shows it started, every refetch keeps what the reader is looking at, and a session that has expired stops offering a Try again that cannot succeed. The admin signed-policy import, the plugin detail lifecycle buttons, the installed-row actions and the marketplace search take the shared busy state. A filter change dims the current results instead of replacing them with skeletons. A 401 becomes a session notice, not "did not load". The "cannot run on this desk" notice and the Installed page state from ticket 04 appear here too.

**Blocked by:** 01, 04.

**Status:** queued.

- [ ] The admin signed-policy file import shows the busy state while the file is parsed and verified, and a refusal keeps the chosen file and the typed state that belongs with it.
- [ ] The plugin detail lifecycle buttons (install, update, consent, disable, retest, rollback, purge, uninstall) show the F1 busy state, not only a disabled attribute.
- [ ] The installed-row actions (Enable, Disable, Share, Roll back, Purge data, Uninstall, Review update) show the F1 busy state.
- [ ] The marketplace search submit shows the busy state or the region's placeholder from the first moment the catalog request starts.
- [ ] A filter or search change keeps the current results on screen, dimmed, instead of replacing them with skeletons; one indicator is shown for the catalog region.
- [ ] A 401 becomes a session notice with the next step and no Try again that cannot succeed.
- [ ] Any other catalog failure still offers a Try again that can succeed and keeps the chosen filters.
- [ ] The "cannot run on this desk" notice appears before install and on the Installed page, and Remove is the offered action.
- [ ] No marketplace page blocks while a detail, pack or catalog request is in flight.
- [ ] Component tests cover the busy states, the dim-and-keep filter change, the 401 session notice and the absent Try again on 401.
- [ ] `python tools/ci_local.py` passes 7/7.
