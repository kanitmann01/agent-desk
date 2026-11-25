# Spec 029: Nexuus Bot, the agent face

**Status:** ready-for-agent (2026-11-24).
`GLOSSARY.md` is the vocabulary.
Builds on Spec 026 (text that fits every screen) and Spec 027 (one true home screen, and feedback on every wait).
Supersedes Spec 017 workstream 8a for the agent's name only: the product remains **Agent Desk**, and **Nexuus Bot** is the agent's name.
One `FaceProvider` and deterministic `brain` seam on the client; existing `agentloop`, `dashboard_state`, and `brand_naming` seams in Python; isolated browser walk for whole-feature verification.

## Problem Statement

Spec 026 made text fit every screen, and Spec 027 gave every control and async region honest per-wait feedback. What the desk still lacks is one calm, continuous presence showing what the agent itself is doing across foreground asks, background passes, and interactive setup flows.

Today, the navigation rail's brand row shows only plain text ("Agent Desk"), the browser tab has no agent mark, and background agent activity is visible only as a timestamp line on the home screen. When a manager types in the command bar, runs a skill, asks for an explanation, opens an agent-assisted modal such as plugin description or tracker setup, or has a background pass or fatal desk check in flight, there is no unified visual cue for the agent's state.

At the same time, Agent Desk's design language bans decorative motion, enforces strict token-only styling, and carries a brand-naming test born of Spec 017 workstream 8a that bans the string `nexuus` everywhere on live surfaces because it was once the retired working product name. Introducing an animated face for **Nexuus Bot** without clear boundaries would risk product-name confusion, stylesheet drift, background CPU waste, accessibility noise, or visual clutter on mobile strips and confirmation dialogs.

## Solution

Give **Nexuus Bot** a minimal, token-driven face that lives in one shared place at a time and tells the truth about what the agent is doing:

- **Name and brand split:** The product stays **Agent Desk** everywhere (rail wordmark, titles, copy, prompts, packages). **Nexuus Bot** is strictly the agent's own name, defined on exactly one line of one canonical client module (`name.ts`) and documented in `GLOSSARY.md`, exposed in the face's native hover tooltip (`title`) and the dev-only review sheet. This supersedes Spec 017 workstream 8a for the agent's name only, enforced by an explicit narrowing of the brand-naming guard.
- **Visual design:** A rounded square filled with the active theme's heading ink and two capsule eyes in the theme's canvas colour, with no mouth, no gradients, no shadows, and zero hardcoded hex values. Default size is 32px (plus a 24px compact size).
- **Eight moods with strict priority:** `idle`, `listening`, `thinking`, `reading`, `working`, `waiting`, `blocked`, and `done`. Active requests outrank `done`, which outranks `blocked`, `waiting`, background `pass`, `listening`, and `idle`.
- **Written exceptions to the design rules:** The design language limits normal UI transitions to 120ms on colour and background only and bans filled icon tiles. The agent face carries two explicit, documented exceptions: (1) shape motion inside the face's box, driven by a single frame-by-frame exponential ease-out curve with no overshoot that stops when settled or hidden and freezes to one static pose per mood under `prefers-reduced-motion: reduce`; and (2) the face as the one filled mark in the chrome (while the static tab icon is an image asset with fixed colours).
- **Autonomous and interactive life:** At rest, the face blinks every 3 to 6 seconds, drifts its gaze every 2 to 4 seconds, and occasionally shows a curious look. It subtly tracks nearby pointer movement, turns toward the command bar while the user types, and performs a playful squash (and nothing else) when clicked.
- **Honest states ("blocked means broken"):** `blocked` is reserved for genuinely broken states (fatal desk checks, failed or refused model calls, broken loop/source states), never for an unconfigured or empty fresh desk.
- **Where it appears (and where it does not):**
  - Expanded and collapsed desktop navigation rail brand row (32px beside the Agent Desk wordmark when expanded; centered when collapsed).
  - Browser tab icon (`favicon`), showing the static idle face.
  - Opt-in modal dialogs where the agent is actively working (plain-English plugin description and workbook tracker setup). While an opt-in modal holds the face, the rail face hides so only one face is visible on screen, and only that modal's work drives it.
  - **Excluded in v1:** Nothing is added to the mobile phone strip (`.phone-bar`), non-agent modals (consent/permission reviews, uninstall, rollback, purge confirmations) do not mount the face, server-rendered pages keep their existing layout as a follow-up, and v1 changes zero product copy or LLM prompts.

## User Stories

1. As a manager using Agent Desk, I want to see a small, calm face for Nexuus Bot in the navigation rail beside "Agent Desk", so that the desk feels alive without distracting from my tiles.
2. As a manager, I want the product to remain named Agent Desk everywhere while the agent's own tooltip names Nexuus Bot, so that I know both what the app is and who is doing the work.
3. As a manager, I want the face to be a rounded square with two capsule eyes and no mouth in my current theme's ink and canvas colours, so that it belongs to Unkey, Coforge, and Momentuum equally.
4. As a manager using the Momentuum theme, I want the expanded rail brand row to fit the 32px face beside the Montserrat 700 "Agent Desk" wordmark without awkward wrapping, so that the rail header stays clean.
5. As a manager who collapses the navigation rail, I want the face to stay centered in the collapsed brand slot while the wordmark hides, so that I keep agent status at a glance in compact mode.
6. As a manager on a narrow phone screen, I want the phone top strip to stay clean with no face icon squeezed beside the section name and menu button, so that mobile navigation stays uncluttered.
7. As a manager with multiple browser tabs open, I want the browser tab icon to show the static idle face, so that I can spot my Agent Desk tab quickly.
8. As a manager looking away from the screen for a moment, I want the idle face to blink naturally every 3 to 6 seconds, drift its gaze every 2 to 4 seconds, and occasionally cast a curious look, so that the desk feels subtly present rather than frozen.
9. As a manager moving my cursor near the face, I want its eyes to follow my pointer gently within bounds, so that the face feels responsive to my presence.
10. As a manager clicking the face out of curiosity, I want a brief playful squash and nothing else, so that clicking does not trigger unexpected navigation or side effects.
11. As a manager typing a question into the command bar, I want the face to shift to `listening` and look toward the command bar, so that I know the desk is ready for my ask.
12. As a manager waiting for a research answer or a saved skill run, I want the face to show `working` while the request runs, `done` briefly (about 1.6 seconds) when the answer arrives, and then return to calm `idle`, so that I have immediate peripheral confirmation of completion.
13. As a manager pressing "Explain this range" or drafting a reply on a tile, I want the face to reflect that active reading or drafting work and finish with `done`, so that card-level AI actions feel connected to the same agent.
14. As a manager re-testing a source or plugin card, I want the face to show active work while the check runs and reflect completion or breakage afterward, so that manual checks share the same feedback loop.
15. As a manager whose action fails or hits a broken endpoint, I want the face to switch to `blocked` with flat lids and a clear tooltip status, so that broken states look distinctly stuck rather than idle.
16. As a manager opening a fresh, unconfigured desk with Sample data or empty sources, I want the face to stay `idle` rather than `blocked`, so that "not set up yet" never looks broken.
17. As a manager while the supervised agent loop runs a background pass, I want the face to show `working` (at lower priority than any foreground request I start), so that I can tell the desk is doing background work on its own.
18. As a manager when a background pass finishes cleanly, I want the face to acknowledge completion without interrupting an active foreground ask, so that my own interaction always wins.
19. As a manager with decisions or inbox items waiting on my input, I want the face to show `waiting` (eyes looking toward me) when nothing higher-priority is running, so that I notice something needs my attention.
20. As a manager when a fatal desk check or broken agent loop step exists, I want the face to show `blocked` even at rest, so that real desk breakage stays visible until resolved.
21. As a manager opening "Describe a plugin in plain English", I want the face to move beside the modal heading and reflect listening while I type, thinking/working while the AI fills choices, `done` when filled, and `blocked` if the fill fails, so that my attention stays inside the dialog.
22. As a manager opening the workbook tracker setup dialog, I want the face to appear beside the modal heading and step its focus cleanly while the AI suggests columns and chart choices, so that I see the agent working on my workbook.
23. As a manager while an opt-in modal holds the face, I want the rail face to hide, so that I never see two faces on screen at once.
24. As a manager when another background poll finishes while an opt-in modal is open, I want only that modal's work to drive the face, so that background activity never hijacks the dialog's mood.
25. As a manager closing an opt-in modal, I want the face to return immediately to the rail without losing global state, so that the handoff is seamless.
26. As a manager opening a permission review, uninstall, rollback, or purge confirmation dialog, I want no modal face inside those dialogs and the rail face left alone, so that non-agent confirmations stay purely procedural.
27. As a manager hovering the face, I want a native browser tooltip showing "Nexuus Bot" and the current mood/status when non-idle, so that I can verify what the face is expressing without visual clutter.
28. As a screen-reader or keyboard user, I want the face to remain decorative (`aria-hidden="true"`, never in Tab order, and never altering modal focus traps or Escape behavior), so that keyboard navigation and assistive announcements stay clean.
29. As a user with `prefers-reduced-motion: reduce` enabled in my OS or browser, I want every mood to render as one distinct, readable still pose with zero frame-by-frame animation, so that motion sensitivity is respected without losing mood clarity.
30. As a laptop user on battery, I want the animation loop to stop completely whenever the face has settled into a steady pose or when the browser tab is hidden, so that the face consumes zero idle CPU.
31. As a manager who relies on existing wording and AI behavior, I want v1 to change zero desk copy and zero model prompts, so that existing workflows and tested strings remain unchanged.
32. As a designer or developer reviewing the face, I want a dev-only review sheet excluded from the production bundle that lets me inspect all 8 moods, all 3 themes, both sizes, reduced-motion poses, interactive pointer/command-bar/click behaviors, and rail/modal header compositions side by side, so that visual quality can be checked without booting the whole app.
33. As a maintainer, I want a single `FaceProvider` and deterministic `brain` seam with an injectable clock so unit tests can assert exact style properties frame-by-frame without flaky `getComputedStyle` timers.
34. As a maintainer, I want the design-language document and token contract test suite to record and bound the motion-rule exception explicitly, so that future UI components cannot use the face as an excuse to re-introduce arbitrary animations or drift colours.
35. As a maintainer, I want the brand-naming test suite to allow only the single canonical agent-name constant (`Nexuus Bot`) while still failing if `nexuus` leaks into product strings, HTML templates, build metadata, or ops docs, so that Spec 017's product-naming guarantee holds.
36. As a security and privacy reviewer, I want zero new runtime dependencies, zero network calls, and an isolated Playwright browser walk proving the full feature against a temporary data folder and loopback mock model.

## Implementation Decisions

### Name and brand boundary

- One canonical client constant on one line of one module defines the agent's name (`Nexuus Bot`), and `GLOSSARY.md` adds the Nexuus Bot entry. No HTML shell (including the dev-only review sheet HTML), server template, package manifest, or product copy embeds the string literally.
- Product naming remains **Agent Desk** across all screens, titles, rail labels, settings, docs, and AI prompts. No copy or prompt changes ship in v1 beyond the face's native hover tooltip (`title`) and the dev-only review sheet.
- This spec supersedes Spec 017 workstream 8a strictly for the agent's own name. The Python brand-naming test enforces this boundary by allowing the name on exactly one line of that one canonical client file (and asserting that line exists), skipping the committed static bundle, scanning the dev-only review sheet HTML, and continuing to reject any appearance of the retired name elsewhere in source, frontend, tools, scripts, or ops docs.

### Geometry, tokens, and written exceptions

- The face renders as a rounded square (`32px` default, `24px` compact) filled with the theme's heading ink token and two vertical capsule eyes in the theme's canvas token, with no mouth. All colours derive strictly from existing semantic CSS custom properties; zero hex values appear in face styles or components.
- Face CSS resides in one dedicated section of the main SPA stylesheet and avoids `@keyframes`, `999px` radii, `transition: all`, shadows, gradients, or blur.
- **Written exceptions in `docs/design-language.md` and `DESIGN.md`:** Both design documents name the two narrow exceptions for Nexuus Bot: (1) shape motion inside the face's box, driven via inline transforms/dimensions computed by a single animation engine (`brain`) using frame-by-frame exponential ease-out with zero overshoot, and frozen to one distinct static pose per mood under `prefers-reduced-motion: reduce`; and (2) the face as the one filled mark in the UI (the browser tab icon is a standalone SVG image asset with fixed colours).

### The eight moods and priority resolution

- The eight moods are: `idle`, `listening`, `thinking`, `reading`, `working`, `waiting`, `blocked`, and `done`.
- Mood resolution follows one deterministic priority order:
  1. Active foreground request (`request`: `working`, `reading`, `thinking` from user actions or the active modal)
  2. Transient completion (`done`, held for roughly 1.6 seconds before decaying)
  3. Broken state (`blocked`, representing fatal desk checks, broken loop/source states, or failed/refused requests; never unconfigured/empty states)
  4. User attention needed (`waiting`, e.g., pending decisions or inbox items waiting on the user)
  5. Active background pass (`pass`, e.g., supervised agent loop currently running)
  6. Input engagement (`listening`, e.g., typing in the command bar or describing a plugin)
  7. Default rest state (`idle`)
- Every non-idle mood produces a concise native `title` tooltip pairing the agent's name with its status, while `idle` exposes the agent's name alone.

### Animation brain, autonomous behaviors, and lifecycle

- One pure TypeScript animation controller (`brain`) owns all state transitions, pose targets, interpolation math, and timers.
- Interpolation uses exponential ease-out toward target eye height, eye width, vertical offset, horizontal offset, lid flattening/arc, and body squash/tilt, with zero overshoot.
- Autonomous idle behaviors trigger only in `idle`:
  - Blink every 3 to 6 seconds.
  - Gentle gaze drift every 2 to 4 seconds.
  - Occasional curious look (subtle head/eye shift).
- Interactive behaviors:
  - Pointer proximity subtly shifts eye gaze toward the cursor when within range.
  - Typing in the command bar activates `listening` and aims gaze toward the command bar's coordinates.
  - Clicking the face triggers a brief playful squash and performs no navigation, state mutation, or network call.
- Per-mood poses and animations:
  - `idle`: calm open capsule eyes with autonomous blink/drift/curious look.
  - `listening`: slightly widened eyes oriented toward the active input field.
  - `thinking`: eyes angled upward with slow lateral glances.
  - `reading`: rhythmic horizontal line-scanning eye motion.
  - `working`: focused eyes with subtle rhythmic cadence; supports optional row-stepping focus (used during tracker setup column/row selection).
  - `waiting`: eyes directed upward toward the user.
  - `blocked`: flattened lids signalling an error or broken dependency.
  - `done`: happy upward eye arcs held for ~1.6 seconds before returning to the next active or idle mood.
- Power and visibility lifecycle:
  - When all interpolated values converge within epsilon of their targets and no periodic animation is active (or under reduced motion), the `requestAnimationFrame` loop stops completely (sleeps) until a state change, pointer event, or next scheduled blink/drift timer wakes it.
  - When `document.visibilityState === 'hidden'`, scheduled timers and animation frames pause immediately and resume cleanly when visible again.
- Determinism seam: the `brain` accepts an injectable clock and frame-stepping interface so unit tests drive exact millisecond timestamps and assert resulting DOM style properties without relying on wall-clock timers or `getComputedStyle`.

### Single coordination seam (`FaceProvider`, `FaceSlot`, `useFaceActivity`)

- `FaceProvider` wraps the SPA root and holds the global activity registry, pointer/target tracking, and active modal lock.
- `useFaceActivity` registers scoped activity entries (with mood, optional label, priority scope, and optional step index) and cleans up automatically on unmount so cancelled or closed flows never leave stale moods behind.
- `FaceSlot` mounts the face into named slots (`'rail'` or `'modal'`).
- Modal takeover contract: when a `'modal'` slot is mounted and active, `'rail'` slots hide (`null` / unmounted face), ensuring at most one face appears on screen. While a modal holds the face, only activities scoped to that modal drive the face; global background passes or dashboard polls cannot override it until the modal closes.

### Placement, backend signals, and exclusions

- **Rail brand row:** Mounted inside the desktop navigation rail's `.brand` header at 32px beside the "Agent Desk" wordmark when expanded, and centered when the rail is collapsed. Layout spacing ensures the Momentuum Montserrat 700 wordmark does not wrap awkwardly beside the face.
- **Phone strip:** The mobile `.phone-bar` keeps its existing layout with no face mounted.
- **Tab icon:** A static idle-face SVG favicon image asset (with fixed colours) is wired in the SPA HTML shell.
- **Opt-in modals:** Only dialogs where the agent actively assists (`DescribePlugin` and `TrackerSetup`) mount a `modal` `FaceSlot` beside their heading. In `DescribePlugin`, writing is `listening`, filling is `working` with eyes stepping down rows as fields fill, completion is `done`, and failure is `blocked`. In `TrackerSetup`, choosing columns is `thinking`, a ready proposal is `done`, failure is `blocked`, and missing AI model is `idle` with a hint. Consent/permission reviews, uninstall, rollback, purge, and memory-removal dialogs do not opt in. All existing dialog focus traps, `Escape` handling, and Tab order remain unchanged because the face is `aria-hidden="true"` and non-focusable.
- **User-driven waits:** Command-bar typing, research asks, skill runs, tile press actions ("Explain this range", reply draft), and source/plugin re-tests report their lifecycle through `useFaceActivity`.
- **Background loop signal:** The supervised `agentloop` tracks `currentStep` and `lastOk` (set around `step.run` under the state lock and cleared in `finally`, never holding the lock across `step.run`) and exposes them alongside `running`, `lastRunTs`, `nextRunTs`, and `enabled` through `dashboard_state` onto `/api/dashboard` and `GET /api/agent-loop`. While a pass is actively running, the dashboard follows `GET /api/agent-loop` on a 2-second cadence. Active passes drive `working` (`pass` priority), pending decisions or waiting inbox items drive `waiting`, fatal desk checks or broken loop/source states drive `blocked`, and `done` fires only when `lastRunTs` advances between two visible polls and `lastOk` is true.
- **Dev-only review sheet:** A standalone HTML entry and React mount outside the production build configuration renders all 8 moods, all 3 themes, both sizes (32px and 24px), reduced-motion static poses, interactive pointer/command-bar/click demos, and expanded/collapsed rail and modal header compositions. It is never included in the shipped static SPA bundle.

## Testing Decisions

A good test verifies observable DOM output, mood priority, and backend payload behavior through public seams without testing private math internals or relying on `getComputedStyle` in jsdom:

1. **Deterministic `brain` and provider unit tests (Vitest + jsdom):**
   - Inject a synthetic clock and step the brain deterministically across millisecond boundaries to assert exact DOM inline style properties (`transform`, eye dimensions/positions) for all 8 moods, exponential ease-out convergence without overshoot, blink (3-6 s) and gaze drift (2-4 s) intervals, pointer tracking, click squash, `prefers-reduced-motion` static poses (including safe fallback when `matchMedia` is absent in jsdom), sleep when settled, and pause when `document.visibilityState === 'hidden'`.
   - Test `FaceProvider`, `FaceSlot`, and `useFaceActivity` for priority ordering (`request -> done -> blocked -> waiting -> pass -> listening -> idle`), automatic cleanup on unmount, and modal takeover/isolation (rail hides when modal mounts, background activity ignored while modal holds face, rail resumes on close).
   - Prior art: `frontend/src/test/button-pending.test.tsx`, `frontend/src/test/useBusy` fake-timer boundary tests.
2. **SPA integration tests (`@testing-library/react`):**
   - Verify the rail brand row (expanded, collapsed, and phone-bar exclusion), command-bar typing gaze/listening, research/skill/press/re-test wait transitions, background poll mood mapping (broken vs unconfigured), and modal opt-in (`DescribePlugin` row-stepping `working`, `TrackerSetup` `thinking`/`done`/`blocked`/`idle`, non-agent dialogs excluded, focus trap preserved).
   - Prior art: `frontend/src/test/shell.test.tsx`, `frontend/src/test/feedback-dashboard.test.tsx`, `frontend/src/test/describe-plugin.test.tsx`, `frontend/src/test/tracker-setup.test.tsx`.
3. **Design-system and bundle contract tests (`tokens.test.ts`):**
   - Assert face CSS uses only semantic tokens (zero hex colours), obeys banned-effect rules, avoids `999px` and `transition: all`, honors `prefers-reduced-motion`, excludes the dev review sheet from the committed bundle, pins the written exceptions, and asserts bundle markers proving the shipped static build carries the face.
   - Prior art: `frontend/src/test/tokens.test.ts`.
4. **Backend seams (pytest):**
   - Test `agentloop` and `dashboard_state` seams to confirm `running`, `currentStep`, `lastOk`, and broken-state signals reach the dashboard payload accurately without breaking existing wire contracts, including a deadlock test where a running step calls `status()`.
   - Test `tests/test_brand_naming.py` to verify `Nexuus Bot` is allowed on exactly one line of one canonical client file (asserting that line exists), skips the committed bundle, scans `face-sheet.html`, and fails on any leakage into product surfaces, server code, tools, or ops docs, while keeping the em-dash ban enforced.
   - Prior art: `tests/test_server_agentloop_api.py`, `tests/test_brand_naming.py`.
5. **Isolated browser walk:**
   - Boot an isolated desk (temporary data folder, file-backed keychain, loopback mock model) in Playwright across all 3 themes, 1024 and 1280 layout audit before/after checks, collapsed/mobile widths, user waits, background moods, opt-in modals, and reduced-motion emulation, recording screenshots per mood and theme under `docs/evidence/nexuus-face/`.
   - Prior art: `tools/layout_audit.py` and Spec 026/027 evidence packs.

## Out of Scope

1. **Server-rendered pages:** Mounting the live or animated face on server-rendered HTML pages (`/inbox`, `/assistant`, `/agents`, `/settings`, `/memory`, `/mail`, `/peers`, `/wizard`, and legacy `/`) is deferred to a follow-up wave.
2. **Copy or prompt changes:** Updating existing UI copy, greetings, or LLM system prompts to refer to or speak as Nexuus Bot is out of scope for v1.
3. **Phone strip or conversational chrome:** Adding the face to the narrow mobile `.phone-bar` strip or adding speech bubbles, badges, or sound around the face is excluded.
4. **Streaming loop telemetry:** Adding WebSocket/SSE streaming for per-step agent loop progress beyond the existing polling payload is out of scope.

## Further Notes

### Risks and mitigations

- **Motion-rule and filled-mark drift:** Other contributors might copy inline animation patterns or filled icon tiles into normal UI controls. *Mitigation:* Record both face exceptions (shape motion inside its box, and the face as the one filled mark, with the tab icon as a fixed-colour image asset) in `docs/design-language.md`, `DESIGN.md`, and `tokens.test.ts` while keeping the `transition: all`, `@keyframes`, and filled-tile guards strict elsewhere.
- **Brand-naming leakage:** Re-introducing `Nexuus` into the codebase could accidentally weaken Spec 017's product-name guard. *Mitigation:* Allowlist only the single canonical agent-name module/constant in `tests/test_brand_naming.py` and keep the case-insensitive grep active across HTML, server code, tools, scripts, and ops docs, plus keep `Nexuus` out of the dev-only HTML file.
- **Momentuum rail wordmark wrapping:** Momentuum switches headings/display text to Montserrat 700, which is wider than Geist. Adding a 32px face beside "Agent Desk" inside the 200px rail could wrap the wordmark onto two lines. *Mitigation:* Measure the `.brand` row across all three themes on the dev review sheet and in the isolated browser walk, tuning `.brand` gap/sizing on the 4px grid if needed without breaking `tokens.test.ts`.
- **Idle CPU/battery drain:** A naive `requestAnimationFrame` loop running continuously at 60fps would burn laptop battery. *Mitigation:* Make sleep-when-settled and `document.visibilityState === 'hidden'` pause first-class requirements tested with injected clocks.
- **Accessibility interference:** An interactive-looking face in the rail or modal header could hijack Tab order or disrupt `ModalSheet` focus restoration. *Mitigation:* Enforce `aria-hidden="true"`, non-focusable markup, and no keyboard handlers; verify `ModalSheet` focus tests remain green.
- **Dev review sheet shipping in production:** A second HTML entry could accidentally be bundled or exposed. *Mitigation:* Keep the review sheet outside `vite.config.ts` build inputs and assert the committed bundle excludes it.
