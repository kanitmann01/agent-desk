# 01b: The guard that reads it

**What to build:** the running guard. It reads the data ticket 01a defines and enforces it, and it is green on the untouched tree: the approved name and the `NB` initials are pinned on every entry of the inventory; the old display forms are rejected everywhere outside the entries of the per-family temporary list; the em dash ban is kept; tracked path names are checked; the count report prints the before numbers; the negative fixtures fail; and a planted drift in a live file fails the guard. Nothing is renamed.

**Blocked by:** 01a: The name contract as data.

**Status:** ready-for-agent

- [ ] The guard pins the approved literals `Nexuus Bot` and initials `NB` on every entry of the inventory 01a defines. The surfaces that already carry the new name on main (the README title, the face constant, the README image labels) are pinned by this ticket.
- [ ] Old display forms (`Agent Desk`, `AgentDesk`, `agentdesk`, `agent-desk`, `agent_desk`, and the uppercase prefix as display text) are rejected case-insensitively on production source and live documents, everywhere outside the entries of the per-family temporary list. The old `AD` initials are rejected in avatar contexts only. The U+2014 ban keeps its existing live-tree scope and stays enforced.
- [ ] A test proves each allowlist entry of 01a is accepted only in its documented context.
- [ ] Tracked path names are checked: an old-form path is allowed only as an alias shim, a retained launcher, a test of a retained launcher, a legal file or a dated archive, beside the temporary package-path entries.
- [ ] Four negative fixtures fail the guard: a missing new name, an old wordmark, old initials in an avatar context, and an unapproved compact identifier. An injected drift in a live file fails the guard.
- [ ] The count report implements the R2 method over tracked text and tracked paths, and its numbers on the untouched tree match the recorded baseline in the measured notes.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS` on the untouched tree, with no surface renamed.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run.
