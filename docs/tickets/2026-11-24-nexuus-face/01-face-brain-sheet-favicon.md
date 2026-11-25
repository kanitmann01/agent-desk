# 01: The face, its brain, the review sheet, and the tab icon

**What to build:** the standalone Nexuus Bot face component, its single deterministic animation brain covering all eight moods and autonomous behaviors, the single provider and slot seam that coordinates mood priority and modal takeover, the static idle browser tab icon, and a dev-only review sheet excluded from the production bundle.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] One canonical client constant defines the agent's name (`Nexuus Bot`) without changing any product copy or embedding `Nexuus` into HTML files.
- [ ] The face component renders a 32px default (plus 24px compact) rounded square in theme heading ink with two capsule eyes in theme canvas colour, no mouth, zero hex colours, `aria-hidden="true"`, never focusable or in Tab order, a native `title` tooltip naming the agent and current non-idle status, and a click handler that triggers a playful squash and nothing else.
- [ ] One CSS section in the SPA stylesheet styles the face using semantic tokens only, with zero `@keyframes`, zero hex values, no `999px` radii, no `transition: all`, and a `prefers-reduced-motion: reduce` fallback.
- [ ] The single animation brain implements exponential ease-out with zero overshoot, all eight moods (`idle`, `listening`, `thinking`, `reading`, `working`, `waiting`, `blocked`, `done`), autonomous blinks (3 to 6 s), gaze drift (2 to 4 s), occasional curious look, pointer proximity tracking, command-bar gaze, optional row-stepping focus, one static pose per mood under reduced motion (with safe fallback when `matchMedia` is absent), sleeping when settled, and pausing when `document.visibilityState === 'hidden'`.
- [ ] The `FaceProvider`, `FaceSlot`, and `useFaceActivity` seam resolves overlapping activities in priority order (`request` -> `done` -> `blocked` -> `waiting` -> `pass` -> `listening` -> `idle`), cleans up unmounted activities automatically, hides the rail slot whenever a modal slot is active, and isolates modal-held mood updates to that modal's work.
- [ ] A static idle-face SVG tab icon is created and linked in the SPA shell HTML without altering its existing theme metadata.
- [ ] A dev-only review sheet (excluded from production build inputs) renders all eight moods, all three themes (Unkey, Coforge, Momentuum), both sizes (32px and 24px), reduced-motion static poses, interactive demos (tooltip, click squash, pointer follow, command-bar typing), and header compositions (expanded and collapsed rail across all three themes including Momentuum Montserrat 700 fit, plus modal header beside `h2`).
- [ ] Frontend unit tests drive the brain with an injected clock and assert DOM style properties (not `getComputedStyle`), covering all eight moods, blink/drift timing, reduced motion, hidden-tab pause, settled sleep, priority resolution, and modal takeover; frontend typecheck and Vitest suite pass.
