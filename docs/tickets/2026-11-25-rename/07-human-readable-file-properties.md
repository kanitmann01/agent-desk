# 07: The human-readable file properties say Nexuus Bot

**What to build:** the names a person reads in file properties and operator records agree with the product, while every name a machine matches stays as it is. The Windows product, company and file-description fields in the bundle build say Nexuus Bot. The bundle manifest product says Nexuus Bot. The AppLocker rule names, descriptions and ProductName conditions in the operator template say Nexuus Bot. Installer names, `AgentDesk.exe`, the update alias, artifact names, share names, BinaryName and the signing placeholder identity do not move. This is the last display-surface ticket: when it lands, name enforcement is fully on, no temporary exception for display text survives, and the count report records the after-count for the whole surface stage.

**Blocked by:** 02: The server-rendered surfaces say Nexuus Bot. 03: The SPA says Nexuus Bot, and the committed bundle is rebuilt. 04: Generated output and plugin descriptions say Nexuus Bot. 05: The README family and the public introduction. 06: Operator guides, dependent specs and the compatibility table.

**Status:** ready-for-agent

- [ ] The Windows product, company and file-description fields and the bundle manifest product read `Nexuus Bot`, and the update tests that pin the manifest product assert the new value (prior art: `tests/test_update_channel.py`, `tests/test_update_stage.py`, `tests/test_update_rollback.py`); each updated expectation fails against today's metadata before the change.
- [ ] The AppLocker rule names, descriptions and ProductName conditions in the distribution guide's template read `Nexuus Bot`, and `BinaryName` still reads `AgentDesk.exe`; a reading check covers the template.
- [ ] Installer names, the update alias, artifact names, bundle folder and zip names, install and update share names and the signing placeholder identity are unchanged, and the update and bundle verification tests stay green.
- [ ] SBOM metadata, licence bytes and generated notice wording are unchanged, and the guard's compliance and legal pins stay green.
- [ ] Every display family's file of the guard's temporary list is empty after this ticket: name enforcement is fully on, and the only family files still holding entries are the two package-path files that tickets 08 and 09 clear.
- [ ] The count report records the after-count for the surface stage by the R2 method: zero old display occurrences on live surfaces, zero old avatar renders, every inventory surface on the new name. The exact numbers are recorded on the pull request, not guessed.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run; bundle verification inspects artifacts and never launches the executable.
