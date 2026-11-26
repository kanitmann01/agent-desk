# 02: The server-rendered surfaces say Nexuus Bot

**What to build:** every page the server renders names the product once, in the approved words. The shell wordmark, the avatar title and its initials, the page titles and breadcrumbs, the startup banner, the authentication recovery sentence, the session copy, the update and error page copy, the wizard copy, and the server-side prompts and sentences that name the product all read `Nexuus Bot`, and the avatar initials read `NB`. One approved literal per runtime: a single server constant carries the name and every surface renders from it, so no page formats the name by hand. Where a retained launcher script prints the product name, it prints `Nexuus Bot`, and its filename does not change. The guard's server-family entries leave the temporary list in the same change, and the gate stays green throughout.

**Blocked by:** 01b: The guard that reads it.

**Status:** ready-for-agent

- [ ] Every server-rendered surface in the guard's server family renders `Nexuus Bot`, and the avatar initials render `NB`. The render-function tests assert it (prior art: `tests/test_ui_wave2.py`; the SPA-title pin at `tests/test_server_spa.py:36` belongs to ticket 03's family and is not changed by this ticket), and each updated expectation fails against today's copy before the change.
- [ ] The startup banner, the authentication recovery sentence, the session copy, the update and error page copy, the wizard copy, and every server-side prompt or sentence that names the product read from the one approved server constant.
- [ ] Where a retained launcher script prints the product name it prints `Nexuus Bot`; `agent-desk.cmd`, `agent-desk.command` and the existing start scripts keep their filenames, and their launcher tests stay green.
- [ ] The before-and-after count for the family comes from the guard's count report: old display occurrences in the family's files are zero after the change, and both counts are recorded on the pull request.
- [ ] The server family's entries are removed from that family's file of the guard's temporary list in this change, and only from that file; the guard stays green at every point.
- [ ] No compatibility identifier moved: the environment prefix, data folder, cookie, keychain service, health and peer identity, User-Agents, publisher identifiers and command names are unchanged, and their existing suites stay green.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run.
