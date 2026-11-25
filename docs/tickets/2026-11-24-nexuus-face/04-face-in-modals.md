# 04: The face in modals where the agent works

**What to build:** opt the agent-assisted modal dialogs (`DescribePlugin` and `TrackerSetup`) into hosting the face beside the dialog heading via `ModalSheet` and the modal `FaceSlot`, so the rail face hides while the modal is open, only that modal's work drives the face with exact per-phase moods, and non-agent confirmation or consent dialogs leave the face in the rail undisturbed.

**Blocked by:** 02: The rail brand row and user-driven waits.

**Status:** ready-for-agent

- [ ] `ModalSheet` supports an opt-in prop for hosting a `modal` `FaceSlot` beside its `h2` heading, keeping focus management, `Escape` handling, and Tab trapping completely intact.
- [ ] In `DescribePlugin`, the opt-in modal drives exact phases: `listening` while writing the description, `working` while filling with eyes stepping down rows as fields fill, `done` when filled, and `blocked` on fill failure.
- [ ] In `TrackerSetup`, the opt-in modal drives exact phases: `thinking` while choosing columns, `done` when a proposal arrives, `blocked` on suggestion/save failure, and `idle` with a hint when no AI model is configured.
- [ ] While an opt-in modal holds the face, the rail face hides so only one face is visible on screen, and background dashboard activity or global polls cannot override the modal-scoped mood.
- [ ] Closing an opt-in modal releases the modal lock and restores the rail face immediately.
- [ ] Non-agent modals (permission/consent reviews, uninstall, rollback, purge, and memory removal dialogs) do not opt in and keep the face in the rail.
- [ ] Component tests verify modal slot rendering, rail hide/restore handoff, modal activity isolation, `DescribePlugin` row-stepping `working` and `TrackerSetup` `thinking`/`done`/`blocked`/`idle` states, non-agent modal exclusion, and unchanged dialog focus traps; frontend typecheck and Vitest suite pass.
