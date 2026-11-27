# 06: Operator guides, dependent specs and the compatibility table

**What to build:** the operator documentation speaks with one name without breaking a rollout, and the exceptions stop being folklore. The distribution guide's prose says Nexuus Bot while every executable, artifact, install, update and BinaryName contract keeps its exact spelling. The marketplace guide says Nexuus Bot and states two separate facts that today read as one: the runtime data root stays `.agent-desk`, and the bundle install contract stays `AgentDesk`. The licensing guide's explanatory prose says Nexuus Bot while legal instruments, the plugin-grant summary, generated notices and licence-table identifiers stay byte for byte. The compatibility table lands as an operator document naming every retained identifier, its exact context, its owner and its review trigger, read from the same structured list the guard reads. Published Specs 030 and 031 are updated before either starts. The guard's operator-guide entries leave the temporary list in the same change.

**Blocked by:** 01b: The guard that reads it.

**Status:** ready-for-agent

- [ ] The distribution guide's prose says `Nexuus Bot`; the executable name, the artifact name, the install and update shares, the bundle folder and zip names, and the AppLocker BinaryName keep their exact spellings, and a reading check confirms no instruction in the guide promises an installer or executable that does not exist. The AppLocker template's rule names, descriptions and ProductName conditions are left to ticket 07.
- [ ] The marketplace guide says `Nexuus Bot` and states the runtime data root (`.agent-desk`) and the bundle install folder (`AgentDesk`) as two separate facts; a reading check confirms the backup and recovery instructions name the right root for each purpose.
- [ ] The licensing guide's explanatory prose says `Nexuus Bot`; the licence files, the copyright lines, the plugin notices, the generated third-party notice wording, the guide's plugin-grant summary and the licence-table identifier are byte for byte unchanged, and the guard's legal pins stay green.
- [ ] The compatibility table exists as an operator document, names every retained identifier with its exact context, its owner and its review trigger, and a test fails when the table names an identifier the guard's compatibility allowlist does not contain or when an allowlist entry has no row in the table.
- [ ] Spec 030 says that both the product and the agent are Nexuus Bot, removes or narrows its conflicting copy exclusion, and records its dependency on Spec 032. Spec 031 records its dependency on Spec 032 and uses `Nexuus Bot` wherever it names the product, with its template decisions unchanged. A reading check covers each point.
- [ ] No prose in this ticket presents a compatibility identifier as the product wordmark; live prose may explain the identifiers, and the guard's display-form rejection stays green.
- [ ] The before-and-after count for the family comes from the guard's count report: old display occurrences in the family's files are zero after the change, and both counts are recorded on the pull request.
- [ ] The operator-guide family's entries are removed from that family's file of the guard's temporary list in this change, and only from that file; the guard stays green at every point.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run.
