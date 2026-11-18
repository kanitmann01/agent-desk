# 06: The SPA can press a reading too

**What to build:** in the SPA, a card carrying a press shows a button that calls the draft route and renders the answer in place, with one action to stage a drafted reply.

**Build in:** `frontend/src/dashboard/PluginCardView.tsx`, `frontend/src/dashboard/TrackerCard.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`.

**Blocked by:** 03, 05.

**Status:** ready-for-agent

- [ ] A card with `payload.insight.press` renders a secondary button with the press's label under the reading; the button is disabled while a request is in flight and re-enabled on failure.
- [ ] A successful explanation renders its text and the disclosure lines; a draft renders its text with a "Stage as a reply card" action that posts `stage: true` and then confirms with the card's id and refetches.
- [ ] A refusal renders the server's sentence verbatim (409 model off, 404 no thread, 409 ambiguous) and never a generic error.
- [ ] The disclosure lines are always shown before any stage action is offered.
- [ ] Two vitest cases cover the explanation path and the stage path against a stubbed fetch; one covers the model-off refusal rendering.
- [ ] `npm ci && npx tsc --noEmit && npx vitest run frontend/src/test/press.test.tsx` is green. **This cannot be run in the current checkout** for the same reason as ticket 05.
