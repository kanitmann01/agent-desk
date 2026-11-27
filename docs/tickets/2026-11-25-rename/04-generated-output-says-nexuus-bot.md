# 04: Generated output and plugin descriptions say Nexuus Bot

**What to build:** the work the desk hands out carries the current brand. Probe reports open with the approved name. The document properties written into generated presentations say Nexuus Bot. The display descriptions of the bundled plugins, in the registry and the bundled catalog, say Nexuus Bot wherever they name the product. Publisher identifiers, plugin identifiers and installed plugin records do not move, and the registry sync and catalog rebuild run through their scripts, so nothing generated is hand-edited. The guard's generated-output entries leave the temporary list in the same change.

**Blocked by:** 01b: The guard that reads it.

**Status:** ready-for-agent

- [ ] Probe report headers and every product mention in probe output read `Nexuus Bot` (prior art: `tests/test_probe_report.py`), and the updated expectation fails against today's header before the change.
- [ ] The metadata written into generated presentations, the fields a reader sees in the file properties of an exported deck, read `Nexuus Bot`, and the generator tests assert it.
- [ ] The display descriptions that name the product in the registry index and the bundled catalog read `Nexuus Bot`. Publisher values, plugin ids, installed records and policy fixtures are unchanged, and the registry check, the catalog bundle test and the marketplace policy suites stay green.
- [ ] The registry sync and the catalog rebuild are run by their scripts; no generated file is hand-edited, and a second run of each script changes nothing.
- [ ] The before-and-after count for the family comes from the guard's count report: old display occurrences in the family's files are zero after the change, and both counts are recorded on the pull request.
- [ ] The generated-output family's entries are removed from that family's file of the guard's temporary list in this change, and only from that file; the guard stays green at every point.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run.
