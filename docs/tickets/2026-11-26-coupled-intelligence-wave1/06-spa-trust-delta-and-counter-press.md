# 06: SPA trust, delta, and counter-evidence press

**What to build:** Surface Wave 1 across the React SPA tiles: render the `"delta"` block at the top of each tile (keeping the sitting's first-seen delta visible across 8-second background polls while the tile content is unchanged), render the shared expandable `<details class="w-why">` drilldown for `"why"` provenance on both generic plugin tiles and classic tracker tiles, support `"check-counter"` in `PressOffer`, and rebuild the bundled static SPA assets. The insight block kind `"delta"` is not the plugin element kind `"delta"` (`plugins/vocabulary.py` `ELEMENT_KINDS`, matched in `TrackerCard.tsx` for the Change element): the shared insight helpers must keep `InsightBlock` handling separate from plugin element handling.

**Build in:** `frontend/src/types.ts`, `frontend/src/App.tsx`, `frontend/src/dashboard/PluginCardView.tsx`, `frontend/src/dashboard/TrackerCard.tsx`, `frontend/src/index.css`, `frontend/src/test/press.test.tsx`, `frontend/src/test/tracker-cards.test.tsx`, `frontend/src/test/insight-wave1.test.tsx` (new), and rebuilt `src/agentdesk/server/static/spa/`. Do not edit `src/agentdesk/insight/`, `src/agentdesk/server/app.py`, or `src/agentdesk/server/pages.py`.

**Blocked by:** 01: Provenance contract and memory citations, 02: Last-seen snapshots and perceptual deltas, 04: Research falsification and counter-evidence press.

**Status:** ready-for-agent

- [ ] `frontend/src/types.ts` adds `InsightWhyItem`, extends `InsightBlock` (`kind: 'delta' | 'receipts' | 'note' | 'falsify'`, optional `why?: InsightWhyItem[]`), and extends `InsightPress['kind']` with `'check-counter'`.
- [ ] `PluginCardView.tsx` exports shared `DeltaBanner` and `InsightBlocks` helpers reused by `TrackerCard.tsx` (no duplicated block/why markup): `"delta"` renders at the top of each tile regardless of `fresh`/`live` state (so attention-card deltas render on the SPA too), while `"receipts"` (with optional `<details className="w-why"><summary>Why</summary>...</details>`), `"falsify"`, and `"note"` render in order below elements on live/fresh tiles.
- [ ] `App.tsx` preserves each tile's initial sitting `"delta"` block across 8-second background `/api/dashboard` polls as long as that tile's non-delta payload content has not changed, replacing or clearing it if new changes arrive.
- [ ] `PressOffer` in `PluginCardView.tsx` handles `press.kind === 'check-counter'` with clear phase, pending label, and done announcement copy following `GLOSSARY.md` (no `widget` or `Hermes`).
- [ ] `npm ci` (when `node_modules` is absent), `npm run check` (`tsc --noEmit`), `NODE_ENV=test npm test`, and `npm run build` pass, updating `src/agentdesk/server/static/spa/` cleanly.
