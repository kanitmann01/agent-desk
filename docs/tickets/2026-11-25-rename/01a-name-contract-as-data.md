# 01a: The name contract as data

**What to build:** the contract the guard will enforce exists first as data, and nothing is enforced or renamed yet. The inventory of live surfaces is grouped into families and names every entry with the ticket that clears it. The temporary list is stored as one file per family and names exactly the surfaces that still carry the old name on main, plus the package paths that the package stage will move. The compatibility allowlist holds one structured entry per compatibility identifier with its exact permitted context, in the spec's categories. Legal instruments, notice files and dated archive trees are excluded by name. The three README screenshots are named on a dated retained-media list. A test proves each data file is well formed and complete enough for 01b to read.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The inventory of live surfaces exists as data, grouped into families (server pages, SPA and committed bundle, generated output, README family, demo and glossary, frontend setup documents, operator guides, human-readable bundle metadata), and every entry is tagged with its family, so a missed surface is a named gap and not a memory.
- [ ] The temporary list names every surface that still carries the old display forms on main, and the package paths pending the package stage. Each entry names its family and the ticket that removes it.
- [ ] The temporary list is stored as one file per family. The guard reads every family file. A ticket that clears a family edits only that family's file of the temporary list, and no file another ticket edits, so the parallel surface tickets never merge over the same file.
- [ ] The compatibility allowlist holds one structured entry per compatibility identifier with its exact permitted context, following the spec's categories (import compatibility, data and local state, environment and tooling, browser and secrets, wire and recorded identity, commands and launchers, public distribution, compliance metadata, legal text). No spelling is allowlisted globally.
- [ ] Legal instruments, notice files and dated archive trees are excluded from the display-name scan by name and pinned as unchanged provenance.
- [ ] The three README screenshots are named on a dated retained-media list: their paths, the date, and the wave closeout retake as the review trigger. Nothing else in the guard looks at images.
- [ ] A test proves each data file is well formed and complete enough for 01b to read: every family file of the temporary list exists, every surface a search of the live trees finds is named by exactly one entry with its family and clearing ticket, and every allowlist entry carries its exact context.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`, with no surface renamed and no enforcement added.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run.
