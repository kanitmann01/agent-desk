# Spec 030: One shell everywhere, and the face on every wait

**Status:** ready-for-agent (2026-11-25). Filed as #321. Tickets: #329, #330, #331, #332, #333, #334, #335, #336
`GLOSSARY.md` is the vocabulary.
Builds on Spec 027 (one home screen, and feedback on every wait) and Spec 029 (the agent face), and takes over the parts of Spec 029 that were deferred or left unbuilt.
The shared busy primitives, the face store, the one page script, the page shell and the layout audit's pending walk are the seams. One new metric in that walk; no new product seam.

## Problem Statement

The navigation rail is drawn twice. Server-rendered pages get it from a string in Python; the single-page app gets it from React. The two copies agree on the eight entries, their order, their labels and the stored collapsed state. They disagree in five other places. The app's rail has the face and the theme control, and it marks the current page by a rule of its own. The Plugins pages always show zero waiting in Inbox. The collapse control starts in a different state, and the link colour differs. Every change to navigation has to be made twice, and the next difference is one forgotten edit away.

The agent face, which Spec 029 gave the desk, lives only in the app's rail. The pages with the longest waits have none. A manager who runs the worksheet brief or builds a deck on the Agents page waits up to a minute in front of a placeholder and a busy button, with no agent anywhere. The same holds for Memory, Inbox, Assistant, Settings and Mail. Inside the app about thirty waits never reach the face: installing, uninstalling and updating a plugin, connecting a workbook, re-testing a source, and every wait on the Memory page.

Spec 029 listed server-rendered pages as deferred. It also described the face moving into the plugin description and tracker setup dialogs, and a mood for a background pass. None of those three is on main.

Two things follow. The one calm, continuous presence that Spec 029 set out to build is missing where it would matter most. And every new wait has to remember to wire the face by hand, which is how thirty of them came to be missing.

## Solution

One shell component draws the navigation everywhere. It owns the rail with the brand row and the face, the collapse control, the count of waiting Inbox items, the theme control, the user block, and the phone bar with its menu. The app uses the component directly. Server-rendered pages mount it in the same place, so one component draws the navigation on every page and behaves the same everywhere. The server-rendered rail remains only for a browser with scripting off, so every page still works without a script.

Every wait drives the face by itself. A wait that goes through the shared busy primitives of Spec 027 reports to the face with no extra code: the phase line's label becomes the face's label, and the mood is working unless the wait says it is a model call or a read. When the wait ends, the face shows done, or blocked while a failure is on screen.

On server-rendered pages a form that declares its wait lights the same face while the request is in flight, and the face looks toward the region that will receive the result. The outcome line on the page the request lands on gives the face done or blocked.

The spec also finishes what Spec 029 promised. The face moves beside the heading of the two dialogs where the agent works. The face tells the truth about a background pass, waiting items and a broken desk, on every page.

Changing page still loads the whole page. The founder chose that for this wave: the shell is one component and its state survives the load, but it is not kept mounted across pages.

## User Stories

### The navigation

1. As a manager, I want the same navigation rail on every page, so that I never have to look for the same link twice.
2. As a manager, I want the page I am on marked the same way on every page, so that I always know where I am.
3. As a manager, I want the count of waiting Inbox items to be right on every page, including the Plugins pages, so that I do not miss a decision.
4. As a manager, I want the rail to stay collapsed when I collapsed it, whatever page I open next, so that the layout is mine to keep.
5. As a manager, I want to change the theme from the rail on any page, so that I do not have to go to Settings for it.
6. As a manager on a phone, I want the menu bar and its menu to open and close the same way on every page, so that the menu is predictable.
7. As a manager, I want the rail to hold its place when a page loads, with no second rail, no jump and no flash, so that moving between pages feels steady.
8. As a person using a browser with scripting off, I want the rail still drawn on every page and its links still working, so that I lose nothing.
9. As a screen-reader user, I want each rail link to keep its name and the current page to keep its marker on every page, so that navigation reads the same everywhere.

### The face on every page

10. As a manager on the Agents page, I want Nexuus Bot in the rail, so that the agent is present where the longest runs happen.
11. As a manager on the Memory page, I want Nexuus Bot in the rail, so that memory work feels connected to the same agent.
12. As a manager on Inbox, Assistant, Settings or Mail, I want the same face in the same place as on the Dashboard, so that the desk feels like one desk.
13. As a manager with the rail collapsed, I want the face to stay, centred in the narrow rail, so that I keep the agent's state at a glance.
14. As a manager on a phone, I want the top strip to stay as it is, with no face squeezed beside the page name, so that the strip stays clean.
15. As a manager with several tabs open, I want the tab icon unchanged, so that I can still find the desk.

### Every wait drives the face

16. As a manager pressing any control that waits, I want the face to show working with the words the phase line shows, so that the control and the agent tell me the same thing.
17. As a manager, I want nothing to change on the face for a wait shorter than a tenth of a second, so that the face never flickers.
18. As a manager starting a model call (an explanation, a draft, an ask, a description, a suggestion), I want the face to show thinking, so that I know the model is at work.
19. As a manager re-testing a source or reading data, I want the face to show reading, so that I can tell a read from a thought.
20. As a manager typing a question or a brief, I want the face to show listening and look toward my field, so that I know the desk is ready for my words.
21. As a manager whose wait ends well, I want the face to show done for about 1.6 seconds, so that I get a quiet confirmation without reading.
22. As a manager whose wait fails, I want the face to show blocked while the failure is on screen and to name the cause in its tooltip, so that a failure never looks like idle.
23. As a manager with two waits at once, I want the face to show the one I started most recently when they are of the same rank, and the one I started myself when a background pass is also running, so that my own work always wins.
24. As a manager who closes a sheet while its request is still running, I want no stale mood left on the face, so that the face never claims work that ended.
25. As a manager waiting longer than ten seconds, I want the phase line to say so and the face to keep showing the wait, so that neither pretends something changed.
26. As a manager, I want waits on the Memory page (capture, review, sweep, recall) to light the face like every other wait, so that one rule holds everywhere.
27. As a manager, I want waits in the Plugins pages (install, uninstall, update, consent, publish) to light the face, so that the longest installs show the agent at work.

### Server-rendered pages

28. As a manager pressing Run on the Agents page, I want the face to show working with the declared words ("Building your deck. This takes about a minute.") and to look toward the region that will hold the result, so that I know the run started.
29. As a manager whose run lands back on the page, I want the face to show done when the outcome line is a status and blocked while it is an alert, so that the result reaches me even before I read it.
30. As a manager, I want a form that the page script unlocks as stuck to put the face into blocked with the note's words, so that a stuck form is never mistaken for a working one.
31. As a manager who types a brief into a form on any server-rendered page, I want the face to show listening, so that the field I am in is the one it attends to.
32. As a manager who leaves a page while a form is still posting, I want nothing carried over to the next page, so that the next page starts truthful.

### Background truth

33. As a manager while a background pass runs, I want the face to show working at a lower rank than my own asks, so that I can see the desk is busy without it hiding my work.
34. As a manager, I want the face to show done once when a background pass ends well, and never while my own ask is in flight, so that my work is not interrupted.
35. As a manager with decisions waiting in Inbox, I want the face to show waiting when nothing of higher rank is running, so that I notice them.
36. As a manager whose desk has a fatal check or a broken loop, I want the face to show blocked even at rest, so that real breakage stays visible until it is fixed.
37. As a manager on a fresh, unconfigured desk, I want the face to stay idle, so that "not set up yet" never looks broken.
38. As a manager, I want the same background truth on every page, not only on the Dashboard, so that the face does not change its story when I change page.
39. As a manager with the background loop switched off or missing, I want no error mood and no repeated failing request, so that an optional feature stays quiet.

### The two working dialogs

40. As a manager describing a plugin in plain English, I want the face beside the dialog's heading: listening while I type, working while the choices fill, done when they are filled, blocked if the fill is refused, so that my attention stays in the dialog.
41. As a manager in the tracker setup dialog, I want the face beside its heading: thinking while the columns are chosen, done when a proposal is ready, blocked on failure, idle with a hint when no model is configured, so that I see the agent working on my workbook.
42. As a manager, I want the rail face to hide while one of those two dialogs holds the face, and only that dialog's work to drive it, so that I never see two faces and background work never takes a dialog over.
43. As a manager opening a consent review, an uninstall, a rollback or a purge confirmation, I want no face in that dialog and the rail face left alone, so that procedural confirmations stay procedural.

### Access and power

44. As a person with reduced motion switched on, I want each mood as one still pose, on every page, so that motion is never forced on me.
45. As a screen-reader or keyboard user, I want the face to stay decorative and out of the tab order on every page, so that nothing in navigation or in a dialog's focus changes.
46. As a manager on a laptop, I want the face's animation to sleep when it has settled and whenever the tab is hidden, on every page, so that it costs no idle battery.

### Maintainers

47. As a developer adding a wait through the shared busy primitives, I want the face to follow with no code of mine, so that I cannot forget it.
48. As a reviewer, I want a test to fail when a wait names neither its failure state nor that its end is not news, so that every wait's outcome is a decision and not an accident.
49. As a developer, I want the entries of the rail in one definition that both the component and the no-script fallback read, and a test that holds the two renderings equal, so that the rail cannot split in two again.
50. As a reviewer, I want the pending walk to record whether the face lit during each control's wait and to count the controls where it did not, so that "every wait lights the face" is a measurement and not a claim.
51. As a developer, I want the shell to carry its own small stylesheet and take its colours from either of the two token dialects, so that it needs neither the app stylesheet on a server page nor a rename of any token.
52. As a security reviewer, I want no new dependency, no request beyond the desk's own endpoints, and no change to the content security policy, so that the shell adds no new surface.

## Implementation Decisions

### One shell component

- One React component, the shell, owns the brand row (the face slot, then the wordmark), the rail entries, the collapse control, the count of waiting Inbox items, the theme control, the user block, and the phone bar with its menu. The app mounts it directly where its rail is today. It replaces the app's rail component; nothing else in the app changes.
- Server-rendered pages mount the shell as an island. The page shell still renders the page grid and the main region, and adds a mount element in the rail's position that carries the current path and the count of waiting Inbox items as data attributes. It loads one script and one stylesheet, each with a fixed name in the static bundle folder. The static bundle is the only script source the policy allows, and it already serves the Memory page's islands this way.
- The fallback for a browser without scripting is the rail markup the page shell renders today. The theme boot script, which every page already loads before first paint, marks the document as scripted. The page stylesheet then hides the fallback rail and shows the mount, which reserves the same column, wide or narrow according to the stored collapse state, so nothing shifts. Without scripting the mark never appears, the fallback shows as today, and the mount stays empty.
- The entries of the rail (address, label, the single-letter mark for the narrow rail, and their order) live in one definition that the shell component and the fallback renderer both read.
- One rule for the current page: the entry whose address is the current path, or the parent of it for nested paths. It replaces the app's rule, which knows only two pages.
- One source for the count of waiting Inbox items. The shell polls the dashboard payload itself (see Background truth) and reads the count from it. A host that already polls the same payload passes its value down instead, so the Dashboard keeps one poll. The Plugins pages stop passing zero.
- The theme control sits in the rail on every page, as it does in the app today. The theme boot script and the control share the stored theme, so a choice made anywhere applies on the next page.
- The phone bar is the app's: its state drives the open and closed menu and the expanded state it reports. It carries no face.
- The shell ships with its own stylesheet under its own class prefix. It reads each colour through a local custom property that falls back from the app's token name to the server stylesheet's token name for the same role, so the shell needs neither the app stylesheet on a server page nor a rename of any token. It carries no literal colour.
- The content security policy does not change.
- Tests that pin the page shell's exact list of scripts, and the face slot's place in the brand row, are updated to the new truth once, each in the ticket that changes that truth.

### Every wait drives the face

- The face's activity registry moves out of the React tree into a store in the shared chunk that every island on a page already loads. There is one store per page. The hooks keep their names (`useFaceActivity`, `useFaceState`, `useFaceActions`, `useFaceContext`), so the sites that use them today keep working. The provider at the app root is removed.
- The shared busy primitives (`useBusy`, `usePhase`, the phase line, the pending shape, the shared button's pending state, and the Memory islands' wait line and wait button) register an activity with the store themselves, once the wait has lasted the tenth of a second that Spec 027's first rule allows, and withdraw it when the wait ends or the component unmounts. The activity's label is the phase line's label.
- Three options, all on the primitives:
  - `mood`: `working` (the default), `thinking` for a model call, or `reading` for a read or a re-test.
  - `failed`: the failure state the component already keeps. While it is true the face shows blocked, with the component's failure text as the label, until the component clears it.
  - `quiet`: true for a wait whose end is not news (a first load, a poll, a background refresh).
- When a wait ends, and `failed` is false, and `quiet` is not set, the face shows done for the hold of 1.6 seconds that Spec 029 set.
- Rank is unchanged from Spec 029: a wait the user started outranks done, which outranks blocked, waiting, a background pass, listening and idle. Two waits of one rank resolve to the most recently started. When the winner ends, the next one shows.
- Every call site of a primitive sets `failed` or `quiet`. A contract test reads the source and fails a call site that sets neither, so each wait's outcome is written down.
- The waits that were wired to the face by hand (the research and saved asks, the press and the reply draft, the source re-test) move to the primitives: the ask and the draft pass `thinking`, the re-test passes `reading`. Their hand-written activities and their done calls go. The hook for activities stays for what is not a wait: listening, the dialog takeover, and the background truth.
- The Memory islands keep their own timeline (a button from a tenth of a second, a line from one second) and only report to the same store.

### Server-rendered pages

- The page script has one place where a declared wait becomes visible: after its delay it swaps the submit label and puts the placeholder into the region the form names. There it announces the wait: a start event carrying the label (in the script's existing order of precedence) and the placeholder's position. The shell listens, shows working, and looks toward that position.
- The wait ends when the page script restores the form after the post lands, which it already does when the page is shown again, or when its watchdog unlocks the form as stuck. The first needs nothing on the old page: the navigation replaces it. The second sends an end event with the note's words, and the face shows blocked until the note goes or the page changes.
- The outcome line that a form post lands on carries an explicit outcome, success or failure, next to its role. On load the shell reads it: success gives done for 1.6 seconds; failure holds blocked while the line is in the document.
- Typing: when a text field or a text area inside the main region has focus, the face shows listening and looks at the field. The activity ends when the field loses focus.

### Background truth, on every page

- The loop status endpoint gains the two fields that Spec 029 described and that were never built: the step running now, and whether the last step ended well.
- The shell polls the loop status and the dashboard payload while the document is visible, at the app's cadence: every eight seconds, and every two seconds while a pass is running. A host that already polls the same payload passes its values down.
- The mapping is the one Spec 029 wrote. A running pass is working, at the pass rank. Done fires once when the last run time moves forward between two visible polls and the last step ended well. Waiting decisions or Inbox items are waiting. A fatal desk check, or a broken loop or source, is blocked. A loop that is off, absent or unconfigured adds no mood and logs no error.
- The Dashboard's own poll is the host for this mapping on that page, so no page runs two polls of the same payload.

### The two working dialogs

- The plugin description dialog and the tracker setup dialog mount a dialog face slot beside their heading. The slot registers in the store, so the shell's face hides while either is open and only that dialog's activities drive the face. The scope rule of Spec 029 stays.
- Plugin description: listening while typing; working, stepping down the rows as the choices fill; done when filled; blocked when the fill is refused. Tracker setup: thinking while the columns are chosen; done when a proposal is ready; blocked on failure; idle with a hint when no model is configured.
- Consent reviews, uninstall, rollback, purge and memory-removal dialogs do not mount the slot.

### Instruments and evidence

- The pending walk records the face's mood attribute during each control's wait, between the moment the control shows busy and the moment it stops. Each control gains a face verdict: lit (a mood other than idle), idle, or absent (no face slot in the document). The run's metric line gains `face-missing`, the number of controls that met their feedback rule and whose face was not lit. The rule is zero.
- The pending pass covers every page the rail reaches, the server-rendered ones included.
- Evidence is collected in one folder of the evidence tree: one photograph per mood per theme for the rail, for a server-rendered page and for each dialog, the reduced-motion poses, the walk numbers, and the exact commands.

### Vocabulary

`GLOSSARY.md` gains: shell, rail, island, wait, phase line, mood, and the agent's name.

## Testing Decisions

A good test drives a public seam and asserts what a person can see or hear: the mood attribute and tooltip of the face slot, the words of a phase line, the markup of a page, the list of scripts a page loads. It never asserts private arithmetic, a wall-clock delay or a computed style. Time is injected, and what only a browser can show is measured by the walk.

1. The shared primitives (Vitest, fake timers): an active wait puts its mood and label on the face state after the tenth of a second and not before; `mood` is honoured; `failed` gives blocked with the failure text and holds until it is cleared; without `quiet` the end gives done for 1.6 seconds; with `quiet` it gives nothing; unmounting withdraws the activity. The Memory islands' wait line and wait button are covered through the same store. Prior art: `frontend/src/test/button-pending.test.tsx`.
2. The store and its hooks (Vitest): the rank order, the most-recent rule, the dialog takeover (the shell face hides, background activity is ignored, the shell face returns), cleanup on unmount, and two React roots in one document sharing one store. Prior art: `frontend/src/test/face.test.ts`, `frontend/src/test/face-rail.test.tsx`.
3. Contract tests: every primitive call site sets `failed` or `quiet`; the fallback rail and the shell render the same markup for the same inputs (one golden file); the navigation definition has the eight entries in order; the shell stylesheet carries no literal colour; the committed bundle carries the shell's script and markers. Prior art: `frontend/src/test/tokens.test.ts`, `frontend/src/test/shell.test.tsx`.
4. The page shell (pytest): the mount and its data attributes, the fallback rail still rendered, the hiding rule that depends on the mark, the updated list of scripts, and the outcome attribute on the outcome line; pages render with and without the mark. Prior art: `tests/test_server_shell.py`, `tests/test_server_dashboard.py`, `tests/test_ui_feedback_review.py`.
5. The server seams (pytest): the loop status carries the step running and whether the last step ended well, including while a step is running. Prior art: `tests/test_server_agentloop_api.py`.
6. The app pages (Testing Library): every wait on the Dashboard and the Plugins pages shows the mood its option names; the Plugins pages show the real count of waiting Inbox items; the two dialogs take the face over; a non-agent dialog does not. Prior art: `frontend/src/test/feedback-dashboard.test.tsx`, `frontend/src/test/feedback-marketplace.test.tsx`, `frontend/src/test/feedback-memory.test.tsx`, `frontend/src/test/describe-plugin.test.tsx`, `frontend/src/test/tracker-setup.test.tsx`.
7. The walk (Playwright): the pending pass on every rail page with `face-missing` 0, `dead` 0, `silent` 0 and `disabled-only` 0; the feedback walk exits 0; the layout matrix shows no new finding and the rail's column does not change width; the selftest gains expectations for the face verdict. The photographs and numbers go under `docs/evidence/2026-11-25-shell-face/`. Prior art: `tools/layout_audit.py --pending-audit`, `tools/feedback_walkthrough.py`.

## Out of Scope

1. Keeping the shell mounted while the page changes. Pages still load in full; swapping only the page body was considered and not taken this wave.
2. Streaming phases for a long server run. The face shows working with the declared words.
3. A face on the phone strip, and speech bubbles, badges or sound around the face.
4. Renaming either token dialect, or merging the two stylesheets.
5. Measuring phone widths in the layout audit. The audit starts at 800 pixels; phone coverage is filed as a follow-up.
6. Copy or prompt wording beyond the product name. The product and the agent are Nexuus Bot (Spec 032); this spec changes no other copy or prompt.
7. How the Dashboard and the Plugins pages are served. The app keeps its own document.

## Further Notes

### Decisions the founder took on 2026-11-25

- Pages still load in full on navigation (the smaller cut). The larger cut, a shell kept mounted by swapping the page body, stays open for a later wave.
- The theme control sits in the rail on every page.
- Every server-rendered page polls for the background truth.
- The spec finishes the three things Spec 029 promised and did not build.
- Every wait names its outcome, or says its end is not news, and a test enforces it.
- The server-rendered rail stays only as the no-script fallback, held equal to the component by a test.
- The agent's name is Nexuus Bot, and the product is Nexuus Bot too: Spec 032 renames every live surface to one name.

### What this spec depends on

- The audit of the UI wave on main closes its P0 and P1 findings before this spec starts. That audit's first ticket narrowed the brand-naming guard of its day; Spec 032 replaced it with the full-surface naming guard.
- Spec 032 completes the rename before shell and face work starts: the product and the agent are Nexuus Bot on every live surface, compatibility identifiers keep their documented names, and the naming guard holds the line.
- Spec 029 is closed by that audit's closeout, with a pointer to this spec for everything it left unbuilt.

### Risks and mitigations

- Two rails visible for a moment, or a shift at load. Mitigation: the mark is set before first paint by a script the page already loads, the mount reserves the column, and the layout matrix checks the rail's width.
- A face that pulses after every small completion. Mitigation: a call site that does not set `quiet` must stand by its done pulse, the contract test forces the choice, and the walk shows how often the face pulses on a route.
- More polling on server-rendered pages. Mitigation: only while the document is visible, the desk's own endpoints only, and no second poll where the host already polls.
- Tests that pin today's markup. Mitigation: each pin changes once, in the ticket that changes the truth it pins, and the commit says why.
- A page with scripting off. Mitigation: every Python page test runs with and without the mark, and the fallback is held equal to the component.

### Follow-ups to file

- A layout audit at phone widths.
- The larger navigation cut, if the founder wants the shell to persist across pages.
