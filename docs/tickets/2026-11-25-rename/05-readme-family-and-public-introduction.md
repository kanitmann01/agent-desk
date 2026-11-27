# 05: The README family and the public introduction

**What to build:** the public introduction tells one story, and three wrong sentences get fixed in the same change as the naming, not in a separate pull request. The README, its provenance note, the demo script, the glossary and the frontend setup documents say Nexuus Bot. The frontend prerequisite states the minimum Node version the frontend tools need and which versions below it do not work, with the value read from the toolchain rather than guessed. The keychain sentence claims only what the code does. The screenshot capture instructions gain the step that installs the browser, so that retaking the three screenshots at the wave's closeout is one command on a clean machine with no hand work. The three screenshots, their alt text and the provenance note stay exactly as they are through this spec, pinned by the guard. The guard's README-family entries leave the temporary list in the same change.

**Blocked by:** 01b: The guard that reads it.

**Status:** ready-for-agent

- [ ] The README title, body, image labels and architecture labels say `Nexuus Bot`, and the guard's README-family pins stay green. The three screenshot images, their alt text and the provenance note are byte for byte unchanged, with their paths named on the guard's retained-media list.
- [ ] The frontend prerequisite names the minimum Node version for the frontend development tools and which versions below it do not work; the value comes from the frontend toolchain, with the source of the value recorded, and a reading check confirms the claim matches it.
- [ ] The keychain sentence says only what the code does: model keys go to the OS keychain where a usable keychain is available, no key is stored where there is none, and plaintext configuration and legacy fallback paths exist. A reading check compares the sentence with the keychain code paths.
- [ ] The screenshot capture instructions include the step that installs the browser, and a reading check confirms the documented sequence has no other missing step, so that retaking the three images at the wave's closeout is one command on a clean machine. No screenshot is retaken in this ticket.
- [ ] No README instruction promises an installer or executable that does not exist; the repository, clone folder, launcher names and data folder examples that remain are labelled compatibility contracts, and a reading check confirms each instruction points at something real.
- [ ] The demo script says `Nexuus Bot` in its spoken and written copy while every retained command keeps its exact spelling (prior art: `tests/test_demo_walkthrough_exists.py`), and the glossary's title and product definition say `Nexuus Bot` and distinguish the product name from compatibility identifiers so new copy does not imitate legacy code names.
- [ ] The frontend README and the frontend package description say `Nexuus Bot`; the package name and lockfile identity are unchanged in this ticket.
- [ ] The before-and-after count for the family comes from the guard's count report: old display occurrences in the family's files are zero after the change, and both counts are recorded on the pull request.
- [ ] The README family's entries are removed from that family's file of the guard's temporary list in this change, and only from that file; the guard stays green at every point.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run.
