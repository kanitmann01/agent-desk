# 06: Gate evidence, isolated browser walk, and pull request

**What to build:** rebuild the committed SPA bundle once from the merged source with bundle marker assertions passing in `tokens.test.ts`, run the layout audit before/after at 1024 and 1280 plus an isolated Playwright browser walk capturing screenshots per mood and theme under `docs/evidence/nexuus-face/`, pass the full local CI gate 7/7, file the three follow-up issues, and open the pull request referencing Spec 029 and all six tickets.

**Blocked by:** 05: Written rules and the brand guard.

**Status:** ready-for-agent

- [ ] The committed SPA static bundle is rebuilt once from the merged source, matches the source cleanly, excludes the dev-only review sheet, and passes new face bundle marker assertions in `frontend/src/test/tokens.test.ts`.
- [ ] The layout audit runs before and after at 1024 and 1280 with zero new layout or pending-state regressions across themes.
- [ ] An isolated browser walk (temporary data folder, file-backed keychain, loopback mock model, never touching real data or a real AI) verifies rail brand row (expanded and collapsed) in Unkey, Coforge, and Momentuum, phone strip free of the face, static idle tab icon, user waits, background moods, opt-in modals (`DescribePlugin`, `TrackerSetup`) hiding the rail face, non-agent modals leaving the rail face alone, and `prefers-reduced-motion: reduce` static poses.
- [ ] Screenshots per mood and per theme, along with exact commands, run environment, layout audit before/after counts, and test/gate counts, are committed under `docs/evidence/nexuus-face/`.
- [ ] Full local CI gate (`python tools/ci_local.py`) passes 7/7 after the final edit and bundle rebuild.
- [ ] The three follow-up issues (server-rendered pages, copy/prompt updates, and phone strip) are filed and linked, and the pull request description references Spec 029 (`specs/029-nexuus-bot-agent-face.md`) and tickets 01 through 06.
