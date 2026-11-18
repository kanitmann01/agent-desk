# 06: The SPA can press a reading too

**What to build:** in the SPA, a card carrying a press shows a button that calls the draft route and renders the answer in place, with one action to stage a drafted reply.

**Build in:** `frontend/src/dashboard/PluginCardView.tsx`, `frontend/src/dashboard/TrackerCard.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`.

**Blocked by:** 03, 05.

**Status:** done (2026-11-18)
**GitHub:** issue #142

- [x] A card with `payload.insight.press` renders a secondary button with the press's label under the reading; the button is disabled while a request is in flight and re-enabled on failure.
- [x] A successful explanation renders its text and the disclosure lines; a draft renders its text with a "Stage as a reply card" action that posts `stage: true` and then confirms with the card's id and refetches.
- [x] A refusal renders the server's sentence verbatim (409 model off, 404 no thread, 409 ambiguous) and never a generic error.
- [x] The disclosure lines are always shown before any stage action is offered.
- [x] Two vitest cases cover the explanation path and the stage path against a stubbed fetch; one covers the model-off refusal rendering.
- [x] `npm ci && npx tsc --noEmit && npx vitest run frontend/src/test/press.test.tsx` is green. Green in this checkout, same command and same `NODE_ENV=test` caveat as ticket 05.
