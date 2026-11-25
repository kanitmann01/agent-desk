# 05: Written rules and the brand guard

**What to build:** add the Nexuus Bot entry to `GLOSSARY.md`, record the agent face rules and both written exceptions in `docs/design-language.md` and `DESIGN.md`, pin the face stylesheet contract in `tokens.test.ts`, and update `tests/test_brand_naming.py` to allow the agent name on exactly one line of one file while keeping Agent Desk and the em-dash ban enforced everywhere else.

**Blocked by:** 01: The face, its brain, the review sheet, and the tab icon; 02: The rail brand row and user-driven waits; 03: Background moods and the agent loop signal; 04: The face in modals where the agent works.

**Status:** ready-for-agent

- [ ] `GLOSSARY.md` adds the Nexuus Bot entry defining it as the agent's name while Agent Desk stays the product name.
- [ ] `docs/design-language.md` and `DESIGN.md` document the agent face geometry, eight moods, placement rules, and BOTH written exceptions: (1) shape motion inside the face's box (exponential ease-out with no overshoot, reduced-motion static poses, sleep when settled) and (2) the face as the one filled mark (noting the tab icon is an image asset with fixed colours).
- [ ] `frontend/src/test/tokens.test.ts` pins the face CSS contract (semantic tokens only, zero hex values, no `@keyframes`, no `999px`, no `transition: all`, reduced-motion support) and verifies that the dev-only review sheet is not part of the production bundle.
- [ ] `tests/test_brand_naming.py` allows the name on exactly one line of one canonical client file (asserting that line exists), skips the committed bundle, scans `face-sheet.html`, and continues to fail if `nexuus` appears anywhere else across source, frontend, HTML, tools, scripts, or ops docs.
- [ ] All live files across source, frontend, tests, scripts, tools, and docstrings guide remain free of the banned em dash (U+2014).
- [ ] Full pytest and Vitest suites pass with the updated guards active.
