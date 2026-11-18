# 05: The workbook card draws the reading the server draws

**What to build:** in the SPA, the workbook card renders the appended elements and the receipt line instead of only its own figure.

**Build in:** `frontend/src/dashboard/TrackerCard.tsx`, `frontend/src/dashboard/PluginCardView.tsx` (export the element view), `frontend/src/types.ts`.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] The tracker card renders every element in `payload.elements` under its figure, using the same element component the generic plugin card uses (exported, not copied).
- [ ] The receipt line renders under the elements from `payload.insight.receipts`, with the same words the server-rendered card uses.
- [ ] An unknown element kind and a missing payload render nothing rather than an empty box; an attention card (no payload) is unchanged.
- [ ] A vitest case in `frontend/src/test/tracker-cards.test.tsx` renders a card with two text elements, a checklist and receipts, and asserts the sentences and the receipt line are in the document; a second case asserts an attention card is untouched.
- [ ] `npm ci && npx tsc --noEmit && npx vitest run frontend/src/test/tracker-cards.test.tsx` is green. **This cannot be run in the current checkout**: `frontend/node_modules` is empty and `frontend/dist` is absent, so the ticket declares the command rather than a result.
