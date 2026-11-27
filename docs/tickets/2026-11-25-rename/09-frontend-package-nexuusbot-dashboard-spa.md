# 09: The frontend package becomes nexuusbot-dashboard-spa

**What to build:** the frontend package identity moves, and the browser sees no difference. The private package name and the lockfile identity become `nexuusbot-dashboard-spa`. The production build lands in the canonical Python package tree, and the static mount and every browser URL stay exactly as they are. The committed bundle is rebuilt once at its new path and committed; a second build changes nothing, and the hosted workflow finds no committed-bundle diff. With this ticket the guard's temporary list is empty: every surface is on the new name and every remaining old identifier sits in the compatibility allowlist.

**Blocked by:** 08: The Python package becomes nexuusbot, with the old import path kept working.

**Status:** ready-for-agent

- [ ] The package name and the lockfile identity read `nexuusbot-dashboard-spa`, and a fresh install from the lockfile resolves.
- [ ] The production build output moves into the canonical Python package tree; the static mount and every browser URL are unchanged, and a reading check of the server mount confirms it.
- [ ] The committed SPA is rebuilt once at its new path and committed. A second production build is byte for byte identical, and the hosted workflow reports no committed-bundle diff.
- [ ] The type-check and the frontend test suite pass; the token and bundle contract tests pin the new bundle path (prior art: `frontend/src/test/tokens.test.ts`, `frontend/src/test/setup-strip.test.tsx`, `frontend/src/test/theme.test.tsx`); browser storage keys, the session cookie and the theme event are unchanged.
- [ ] The guard's inventory for the frontend package path is updated; its temporary entry is removed from that family's file of the guard's temporary list; every family file of the temporary list is empty, and every remaining old identifier is explained by one compatibility allowlist entry.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run.
