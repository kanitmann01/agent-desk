# 05: The workbook card draws the reading the server draws

**What to build:** in the SPA, the workbook card renders the appended elements and the receipt line instead of only its own figure.

**Build in:** `frontend/src/dashboard/TrackerCard.tsx`, `frontend/src/dashboard/PluginCardView.tsx` (export the element view), `frontend/src/types.ts`.

**Blocked by:** 01.

**Status:** done (2026-11-18)
**GitHub:** issue #141

- [x] The tracker card renders every element in `payload.elements` under its figure, using the same element component the generic plugin card uses (exported, not copied).
- [x] The receipt line renders under the elements from `payload.insight.receipts`, with the same words the server-rendered card uses.
- [x] An unknown element kind and a missing payload render nothing rather than an empty box; an attention card (no payload) is unchanged.
- [x] A vitest case in `frontend/src/test/tracker-cards.test.tsx` renders a card with two text elements, a checklist and receipts, and asserts the sentences and the receipt line are in the document; a second case asserts an attention card is untouched.
- [x] `npm ci && npx tsc --noEmit && npx vitest run frontend/src/test/tracker-cards.test.tsx` is green. Green in this checkout once dev dependencies are installed (`npm ci --include=dev`): `npx tsc --noEmit` exit 0 and `NODE_ENV=test npx vitest run` 24 files / 272 tests passed. `NODE_ENV` matters on this machine: it exports `production`, which loads React’s production build and fails every render test.
