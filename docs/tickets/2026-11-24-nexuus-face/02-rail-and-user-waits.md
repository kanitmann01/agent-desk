# 02: The rail brand row and user-driven waits

**What to build:** mount the face inside the desktop navigation rail's brand row (expanded and collapsed, while keeping the mobile phone strip untouched), wrap the SPA shell in `FaceProvider`, and wire every user-initiated SPA wait (command bar, research asks, saved skill runs, tile press actions, and source/plugin re-tests) into the face's priority lifecycle without changing existing product copy or prompts.

**Blocked by:** 01: The face, its brain, the review sheet, and the tab icon.

**Status:** ready-for-agent

- [ ] `FaceProvider` wraps the SPA root so dashboard and marketplace routes share one continuous face state and pointer/command-bar tracking.
- [ ] The desktop navigation rail mounts the 32px rail `FaceSlot` inside its brand row beside "Agent Desk" when expanded and centered when collapsed, across all three themes without awkward wordmark wrapping in Momentuum.
- [ ] The mobile phone strip (`.phone-bar`) remains unchanged and never renders the face.
- [ ] Typing in the command bar shifts the face to `listening` and aims its gaze toward the command bar field while active.
- [ ] User-initiated SPA waits (research questions, saved skill runs, card press actions such as "Explain this range" and reply draft, and source/plugin re-tests) drive `working` or `reading` while in flight, transition to `done` for roughly 1.6 seconds on completion, and transition to `blocked` on broken or refused failure states.
- [ ] Existing copy, labels, and model prompts across the desk remain unchanged in v1.
- [ ] SPA component and integration tests verify rail placement (expanded, collapsed, phone-bar exclusion), command-bar listening/gaze, and user-wait mood transitions; frontend typecheck and Vitest suite pass.
