# Spec 027: One true home screen, and feedback on every wait

**Status:** done (2026-11-24); evidence in `docs/evidence/2026-11-24-feedback/EVIDENCE.md`. Filed as #318. Tickets: #309, #310, #311, #312, #313, #314, #315, #316, #317.
`GLOSSARY.md` is the vocabulary.
The dashboard payload assembly, the shared `Button`, the one page script and the layout audit's browser probe are the seams; no new product seam.

## Problem Statement

Spec 026 made text fit its box on every screen. The founder read that work and asked a different question:

> The numbers in timeline, pipeline are overflowing too. And tracker has the same ui appearing twice, why? So the ui is not only about overflow but about how the flow is, does every button have loading animation, is the skeleton loading where needed when agent is putting details, mock up when the agent is deciding which graph to choose

Two defects sit under that ask. The home screen repeats itself, and it promises things this desk cannot do. Every wait is silent or ambiguous. A manager on a corporate laptop cannot tell what the desk has read, what it is doing, or whether the button they pressed did anything.

### The tracker card draws the same reading twice

`frontend/src/dashboard/TrackerCard.tsx:58-80` draws `TrackerFigure` (name, figure, change, chart, pace, file), then every `payload.elements` item through `ElementView`, then the resolved blocks and the press. `_tracker_payload` (`src/agentdesk/plugins/cards.py:174-225`) puts into `elements` a metric labelled "Value" (`:179-181`), a delta labelled "Change" (`:182-184`), a text labelled "Workbook" (`:185-186`), an optional "Pace" text (`:187-190`) and, with two or more points, a "History" sparkline (`:191-194`). All five restate what the tile above already draws. The insight pass then appends up to two findings, a "Chart" sentence and a checklist (`src/agentdesk/insight/service.py:43-91`; `src/agentdesk/insight/workbook.py:55-91`), plus the receipt and "Also in your desk" lines as blocks.

The tracker payload cannot change in this wave. `tests/test_insight_seam.py:64-73` pins the element order and the whole insight dict; `tests/test_plugin_setup_http.py:109,324,362` and `tests/test_plugin_config.py:408-409` pin elements; the server-rendered dashboard draws `elements` and the receipt and press with no tracker figure of its own (`src/agentdesk/server/app.py:6065-6093`). Routing cannot change either (`frontend/src/dashboard/PluginCardView.tsx:315-325`): spec 025 lets a manager choose a tracker face, and the `excel-report` id clause serves an attention card whose payload is null (a moved workbook) so it keeps its Set up button.

### The numbers overflow, and the fix is not where it looks

`cards._format_number` (`src/agentdesk/plugins/cards.py:30-40`) returns the raw integer without separators, and that same string is the value binding (`cards.py:163`). `render._number` (`src/agentdesk/plugins/render.py:77-105`) accepts digits, a sign and a decimal point only, so grouping the binding would blank progress and bar faces from 1,000 up. `tests/test_file_selection_chain.py:46,290` pins "186500". The SPA already tolerates separators (`parseFigure`, `frontend/src/dashboard/cells.tsx:151-156`).

The hero figure has about 310px at 1280 and about 167px at 1024 at 56px mono. The first wave gave `.kpi .value` a scroll well (`frontend/src/index.css:593-598`), which is not acceptable for the headline number. Per-bar labels in the stage chart sit in a `1fr` column about 59px wide (`frontend/src/dashboard/cells.tsx:51-96`; `.stage-plot` at `index.css:611`), already compact with the exact value in the aria-label. The tracker `.figure` prints the raw value at 36px (`index.css:754`).

The generic timeline is broken by a global rule: `.w-list-meta{grid-column:2;grid-row:1;white-space:nowrap}` (`frontend/src/index.css:423`) has no `.w-timeline` override. `.w-timeline li` is `44px minmax(0,1fr)` (`index.css:435`), so the title is auto-placed in the 44px column. The server sheet has no timeline or list rules at all (`src/agentdesk/server/pages.py` styles; the element markup is `src/agentdesk/plugins/html.py:209-230`).

### A plugin with no widget gets a tile that can never work

The shipped `presentation-starter` contributes tools but no widget (`registry/plugins/presentation-starter/manifest.json:38-62`). `execute.attach` returns an attention status with the cause "plugin contributes no widget" (`src/agentdesk/plugins/execute.py:332-333`; also `src/agentdesk/plugins/runtime.py:643-645`). `pluginKind` defaults an unknown plugin to the DIGEST tag (`frontend/src/dashboard/pluginKind.ts:20-34`), so the home screen shows an amber tile and a second cell tagged DIGEST. "Re-test now" on it can never succeed. Both surfaces get their cards at `src/agentdesk/server/dashboard_state.py:269`.

### Desk health counts one thing and lists another

`frontend/src/dashboard/Brief.tsx:245-288` builds three fixed rows plus one row per plugin card, while the "x/y live" counter is `data.sources.connected` over `total` (`Brief.tsx:226,288`; `dashboard_state.py:151-152,341`), which counts only the three desk sources (`src/agentdesk/server/core.py:31`). `execute._attention` stamps `checked_at` as now for a plugin that never ran (`execute.py:1334-1340`), so Desk health prints a time for a check that did not happen. Spec 022 defines Desk health as the source table (`specs/022-demo-ready-desk.md:246-247,390-391`); the plugin rows were added beside it without a matching counter.

### The desk promises a web page it cannot read

`competitor-watch` declares its `example.com` permission as an optional grant (`registry/plugins/competitor-watch/manifest.json:39-46`). Even with that grant, the source fails at transport with "The host has no HTTP transport available for this plugin." (`src/agentdesk/plugins/sources.py:1318-1320`). The transport parameter exists on the runner (`src/agentdesk/plugins/execute.py:253,296,641`), but production builds it without one (`src/agentdesk/server/app.py:7782-7783`; default at `src/agentdesk/plugins/runtime.py:189`), no setting turns it on, and the only caller that passes one is a test (`tests/test_sources_v2.py:674`). Spec 015 promises the Page watch card works on a fresh desk (`specs/015-retire-the-plugin-set.md:66-68`). The wizard still offers "A web page" (`src/agentdesk/wizard/vocabulary.py:66`) and builds a network-backed plugin (`src/agentdesk/wizard/core.py:1021-1028`).

### A malformed digest date can take the card down

`Brief.tsx:231-232` parses `event.start` with `new Date`, and `DigestList` calls `item.at.toISOString()` (`frontend/src/dashboard/cells.tsx:263`). An unreadable start throws a `RangeError` in the digest. The claim is inferred from the code.

### The waits

The single-page app has 54 controls that start async work. 26 meet the standard, 3 show nothing at all (Customize at `frontend/src/dashboard/Dashboard.tsx:568`, "Not now" on a recommendation at `frontend/src/dashboard/Brief.tsx:217`, the admin signed-policy file import at `frontend/src/marketplace/Admin.tsx:144`), and 12 are disabled-only with no visible progress (card-menu Re-test, Sales and Commitments Re-test, the marketplace detail lifecycle buttons at `frontend/src/marketplace/PluginDetail.tsx:130-136`, installed-row actions at `frontend/src/marketplace/Installed.tsx:340-386`, admin approve/reject and kill switch, "Use this path" and "Upload this file" at `frontend/src/components/InstanceWalk.tsx:340-366`, tracker Confirm at `frontend/src/dashboard/TrackerSetup.tsx:247`, marketplace search). `Button` has no pending state (`frontend/src/components/Button.tsx:8-32`).

Thirteen data loads lack a shaped placeholder. The dashboard's first load is a centered text card, not a skeleton (`frontend/src/App.tsx:132-141`); the marketplace catalog replaces content with skeletons on every filter change (`frontend/src/marketplace/CatalogPage.tsx:97-123,242-247`); a marketplace 401 becomes "did not load" plus a Try again that cannot succeed (`frontend/src/marketplace/client.ts:29-40`; `CatalogPage.tsx:250-259`).

Of the seven agent moments, the tracker setup suggestion already meets the standard (a dashed chart sketch plus "Choosing the columns", `TrackerSetup.tsx:184-211,282-353`) and the describe-plugin fill shows skeleton rows (`frontend/src/marketplace/DescribePlugin.tsx:145-182`). The research answer, the skills run, the press ("Explain this range") and the reply draft have no placeholder (`Dashboard.tsx:210-260,585-604`; `frontend/src/dashboard/PluginCardView.tsx:211-308`).

The server-rendered pages have 66 controls: 34 at the top severity, 28 medium, 4 polish. Almost all are plain form POSTs with a full page navigation. Model-backed waits with no feedback: assistant Ask (`src/agentdesk/server/research.py:144`; handler `src/agentdesk/server/app.py:2464`), Save to memory (`src/agentdesk/server/memory_api.py:1298`), Agents run (`src/agentdesk/server/agents_view.py:30`; `app.py:2870`), the Presentation run (several model calls, 30 s default timeout, `app.py:2975-3050`), memory Reflect (`memory_api.py:1412`), and the wizard's describe and answer steps (`src/agentdesk/server/wizard_view.py:269,313`). `APP_JS` has no generic submit handler (`pages.py:488` onward). Handlers at `pages.py:545,552,617,622,627,634` fetch and then reload unconditionally after a failed POST, as does the skill undo at `pages.py:771`. Several failures answer raw JSON and lose typed input: a blank fact (`memory_api.py:407,419-421`), a blank brief (`app.py:2894-2899`). The invalid timeout answers a form post with a redirect that names the cause but still loses the typed value (`app.py:3879-3886`); only the JSON call gets a 400. There is no skip link, and focus lands at the top of the document after a navigation (`pages.py:1061-1092`).

The memory islands have no pending state on "Ask AI for observations" (`frontend/src/memory/loop/MemoryLoop.tsx:612`) or on the learning switches (`:425-427`); a failed refetch replaces the whole page with an alert (`:146-151`); the first load is a text line (`:144-145`).

`tools/mock_endpoint.py` has no delay option (`tools/mock_endpoint.py:387-391`). Nothing is streamed: there is no job object and no progress endpoint for any user action.

## Solution

The wave has two halves, and both are rules rather than per-screen patches.

First, the home screen tells the truth. One tracker tile draws one reading and one face; its payload and routing stay exactly as they are. A plugin that contributes no widget gets no tile and no health row. A plugin whose source needs the network says so in reader language, offers Remove as its only action, stays off the home screen, and is named in the marketplace before install. Desk health shows the three desk sources with a counter that counts exactly those rows, then the plugins that feed a tile as a second labelled group with its own count. A plugin that never ran shows "never". Numbers a person compares are grouped for display while the value a system reads keeps its digits; a figure prints in full and the layout makes room, never a scroll well.

Second, every wait reports itself. This wave writes seven feedback rules (F1 to F7) and four number rules (N1 to N4) in `docs/design-language.md`. A shared pending state on `Button` and one `useBusy` hook carry the first second. Regions that will receive a result show a same-shape placeholder with an honest phase line. A refetch keeps what is on screen instead of flashing skeletons. The server-rendered pages obey the same rules inside their normal navigation: a busy button on every form, a placeholder in the outgoing page for a model-backed form, no disabled inputs, and every page still works with the script off.

The wave retracts spec 015's promise that Page watch works on a fresh desk. It does not turn the network on by itself. Wiring an HTTP transport for plugins and the wizard's "A web page" choice is the founder's decision, and this spec records it as one.

After the wave the pending-state audit reports zero silent and zero disabled-only controls on every page and overlay. With the mock model delayed by four seconds, every model-backed action shows a busy control and a same-shape placeholder with a phase line, photographed. The committed "long values" fixture produces zero findings on every numeric site. The tracker card shows its value once; no widget-less plugin and no plugin that cannot run on this desk has a home-screen tile; Desk health's counters match their rows. The layout audit reports zero real-string findings except the 11px class, the full gate passes 7/7, and the evidence is under `docs/evidence/2026-11-24-feedback/`.

## User Stories

1. As a manager reading a live tracker, I want the value once, so that the tile does not look like two cards stacked.
2. As a manager, I want the change once, so that I compare one number and one delta, not two copies of each.
3. As a manager, I want the workbook name once, so that the provenance line is not repeated under the figure.
4. As a manager, I want the pace and the history once, so that the goal and the chart are not drawn twice.
5. As a manager, I want the reading (the findings, the chart sentence, the "Also in your desk" line) in one separated block under the tile, so that I can tell the reading from the figure.
6. As a manager, I want the first line of that reading visible and the rest behind a disclosure, so that the card stays short until I want more.
7. As a manager, I want "Explain this range" kept, so that the new layout does not remove the action I use.
8. As a manager with a plugin that contributes no widget, I want no home-screen tile for it, so that an amber card does not ask me to fix something that cannot work.
9. As a manager, I want no Desk health row for that plugin, so that the health table lists things that can be healthy.
10. As a manager, I want its setup card to stay, so that a plugin whose setup is real can still be set up.
11. As a manager with a plugin that needs the network, I want the card to say "This desk cannot read web pages yet", so that the limit is in my language and not a transport error.
12. As a manager, I want Remove as its only action, so that I am not offered a Re-test that can never succeed.
13. As a manager, I want that plugin kept off the home screen, so that the desk does not show a tile that cannot fill.
14. As a manager browsing the marketplace, I want to know before install that a plugin cannot run on this desk, so that I do not install a dead tile.
15. As a manager, I want the Installed page to repeat that state and offer Remove, so that the place I manage plugins agrees with the card.
16. As a manager reading Desk health, I want the three desk sources and a counter that counts exactly those rows, so that "2/3 live" is about the three rows above it.
17. As a manager, I want the plugins that feed a tile in a second labelled group with its own count, so that a plugin count is not mixed into the source count.
18. As a manager, I want a plugin that never ran to say "never", so that the table does not claim a check that did not happen.
19. As a manager, I want "Re-test now" only where a re-test can change something, so that the control is not a dead end.
20. As a manager, I want an unknown plugin kind to keep its own word instead of becoming DIGEST, so that two different cells do not carry the same tag.
21. As a manager, I want one word per kind in the tags, so that a tag is a category and not a sentence.
22. As a manager, I want a malformed calendar date to leave the digest standing, so that one bad event does not crash the card.
23. As a manager, I want a page that cannot be watched to stop offering "Add a page", so that the home screen does not invite me into the same dead end.
24. As a manager, I want every number I compare grouped (9,270,950), so that I can read the size at a glance.
25. As a manager, I want the headline figure to print in full at 1024 and 1280, so that the number I opened the desk for is not cut off or scrolled.
26. As a manager, I want the stage chart to move below the figure when the figure needs the width, so that both stay readable.
27. As a manager, I want a label on a narrow bar to use compact notation with the exact value reachable, so that the chart stays legible without hiding the number.
28. As a manager, I want a time, a date or a title in a timeline to have a column that fits it, so that the title is not squeezed into 44px.
29. As a manager, I want one list's column rule not to move another list's columns, so that fixing the timeline does not break a checklist or a plain list.
30. As a manager, I want Desk health's numbers and times to fit their cells, so that the table stays a table.
31. As a manager, I want nothing to flicker when work takes under 100ms, so that a fast action does not blink.
32. As a manager, I want the control that started a 100ms to 1s wait to show it on itself, so that I know the press landed.
33. As a manager, I want a busy control to keep its size and carry the continuous verb and `aria-busy`, so that the layout does not jump and a screen reader is told.
34. As a manager, I want the region that will receive a 1s to 30s result to show a same-shape placeholder and a phase line, so that I am not looking at an empty panel.
35. As a manager waiting while the agent chooses, I want a mock-up of the outcome, so that I can see the shape that is being decided.
36. As a manager waiting longer than usual, I want the line to say so after 10 seconds and tell me I may leave, so that I am not trapped.
37. As a manager, I want the result to replace the placeholder in place, so that the page does not jump when the answer arrives.
38. As a manager, I want a success said in a status line where I am looking, so that I know it worked.
39. As a manager, I want a failure said where it happened with the next step, and my typed words kept, so that I can retry without retyping.
40. As a manager, I want a refetch to keep the content dimmed instead of replacing it with skeletons, so that the screen does not flash on every poll.
41. As a manager, I want one loading indicator per region, so that I do not see three signs of the same wait.
42. As a manager, I want the shell and the other regions at once, so that one slow region does not hold the page.
43. As a manager on a server-rendered page, I want a busy button on every form, so that a plain post also tells me it started.
44. As a manager on a server-rendered page, I want a model-backed form to show a same-shape placeholder in the outgoing page, so that the wait is visible before the navigation completes.
45. As a manager, I want the result on the new page to name its outcome in a status line, so that I know what the navigation delivered.
46. As a manager, I want a failed server post to keep my typed values and show the cause, so that a validation error is not a dead end.
47. As a manager, I want a server page to reload only after a successful post, so that a failure does not look like a success.
48. As a manager, I want the focus on the main heading after a navigation, so that the next Tab does not start from the browser chrome.
49. As a manager, I want a skip link on the server pages, so that I can reach the content without walking the rail.
50. As a manager, I want every server page to work with the script off, so that the fallback keeps its promise.
51. As a manager, I want "Ask AI for observations" to show it is working and to ignore a second click, so that I do not launch two runs.
52. As a manager, I want the learning switches to show their pending state, so that a switch that is saving does not look stuck.
53. As a manager, I want "Approve all" to show progress, so that a long review is not a frozen button.
54. As a manager, I want the memory page's first load to be a skeleton, so that the page does not start as one line of text.
55. As a manager, I want a failed memory refetch to keep the page and say so in place, so that one error does not erase my screen.
56. As a maintainer, I want a mock endpoint delay, so that a four-second wait is repeatable.
57. As a maintainer, I want a pending-state audit that presses every control while holding its request, so that "no silent controls" is measured and not asserted.
58. As a maintainer, I want a committed long-values fixture, so that a regression in number fit fails the audit.
59. As a maintainer, I want the seven feedback rules and the four number rules in the design language, so that the next surface starts from the contract.
60. As a security reviewer, I want this wave to add no runtime dependency and no network path, so that the desktop build stays offline.
61. As the founder, I want the network and web-page decision recorded as mine, so that the wave retracts the promise without quietly turning the network on.

## Implementation Decisions

### One tracker, one face

The tile owns value, change, workbook, pace and history. In `TrackerCard` the tile does not draw the elements that restate them: the metric labelled "Value", the delta labelled "Change", the text labelled "Workbook", the text labelled "Pace" and the sparkline labelled "History". The filter is by the element's own kind and label, so an unknown plugin element is still drawn. The appended reading (the two findings, the "Chart" sentence, a checklist when the density asks for one, and the "Also in your desk" note) is drawn once as one clearly separated block under the tile. Its first line is visible and the rest sits behind a disclosure that names what it holds. The press, "Explain this range", stays.

The payload does not change. `_tracker_payload` and `_tracker_bindings` are untouched. `tests/test_insight_seam.py`, `tests/test_plugin_setup_http.py` and `tests/test_plugin_config.py` stay green without edits to the wire shape. The server-rendered dashboard still draws every element, because its card has no `TrackerFigure` of its own.

Routing stays exactly as it is: `PluginCardView` still sends a card with `payload.setup`, a tracker card without a chosen face, and every `excel-report` id to `TrackerCard`, so an attention card with a null payload keeps its Set up button and a wizard-built face still draws its schema elements.

### Honest cards

The filter lands where both surfaces get their cards (`dashboard_state.py:269`), so the SPA payload and the server page cannot disagree. Setup cards stay. A plugin that contributes no widget is dropped from the tile list and from the Desk health plugin group; its setup card, if it has one, stays wherever setup is shown.

A plugin whose declared source is `http-get` cannot run on this desk. Its card says in reader language "This desk cannot read web pages yet", offers Remove as its only action, and is kept off the home screen. The marketplace reads the same fact from the catalog entry's `capabilities.sources` (`src/agentdesk/marketplace/catalog.py:122-169`) and says so on the card, the detail page and the consent sheet before install. The Installed page repeats the state and offers Remove. "Re-test now" is absent because a re-test cannot change the transport.

Desk health keeps its three source rows and its `connected` over `total` counter for those rows only. The plugins that feed a tile become a second group with a heading and their own count. A plugin that never ran shows "never"; the card's own state, not a stamped current time, decides that. The control that shows "Re-test now" appears only where a re-test can change the reading.

`pluginKind` stops defaulting an unknown plugin to `digest`. An unknown plugin keeps a neutral word of its own; each kind carries one word. The digest guards a malformed event start: the item stays, the unreadable time is not formatted, and the title and detail still render.

The Page watch placeholder, when no watch card exists, stops offering "Add a page" while this desk cannot read web pages; it keeps the wireframe and names the limit. This is the one place where the decision in the brief is extended to a desk card, and it is recorded as an open question below.

### Numbers fit

N1. Display grouping happens in the surfaces, never in `_format_number` and never in a binding. The headline figure, the tracker figure, the goal, the change, Desk health counts and every other compared value are grouped for display. `parseFigure` already tolerates the separators. The system value stays "186500" so progress, bars and the pinned chain test keep working.

N2. A figure never scrolls. The `.kpi .value` scroll well goes; the hero grid gives the figure the width it needs and moves the stage chart below the figure when the figure cannot share the row. The tracker figure and its unit print in full inside the tile at 36px. The delta chip and the goal line wrap or give way, never scroll inside their box.

N3. A bar label or a narrow track may use compact notation. The stage values keep the compact form and gain a `title` with the exact value beside the aria-label that already names it. The reading still states the exact number where the reading is.

N4. A timeline's time, date or title has a column that fits its content. The global `.w-list-meta` placement is scoped to the list rows that need it, and `.w-timeline` gets its own two-column contract (time in a fitted first column, title and meta in the second). The server sheet gains the same timeline and list rules, because it has none today. A rule written for one list does not move another list's columns.

The layout audit gains a committed "long values" fixture: the real strings are replaced, in the audit's own data, with values such as 9,270,950 and 1,234,567 on every numeric site. Zero findings on that condition is the acceptance.

### Feedback on every wait

`Button` gains `pending` and `pendingLabel`. A pending button cannot be pressed again, carries `aria-busy="true"`, shows the continuous form of its verb, and does not change its box: no padding, font or width change. A small dot pulses in colour only. `useBusy(active, delayMs = 100)` returns false before the delay and true after it, and resets when `active` falls. The stylesheet adds the pulse and freezes it under `prefers-reduced-motion`.

F1 to F7 are the contract, written in `docs/design-language.md`. The implementation follows them:

- F1: the control shows the first second. Nothing shows under 100ms.
- F2: the region that will receive the result shows a same-shape placeholder and one phase line. The dashboard's first load becomes a bento-shaped skeleton instead of the centered text card. The research answer, the skills run, the press and the reply draft each get a placeholder shaped like their result.
- F3: the tracker setup's dashed chart sketch and "Choosing the columns" line are the model for every agent choice; the press and the reply draft get the same treatment.
- F4: the phase line names only what is happening; a timer turns it into "taking longer than usual; you may leave this page" after 10 seconds.
- F5: the result replaces the placeholder in place. Success is a `role="status"` line; a failure names the cause and the next step and keeps the typed words.
- F6: a refetch dims what is on screen and keeps it; one indicator per region; the shell and the other regions render at once.
- F7: the server pages obey the same rules inside their normal navigation.

On the server pages, one delegated capture-phase `submit` listener in `APP_JS` covers every `form[method=post]`. The pressed submit button takes the busy state and keeps its size. Inputs are never disabled, because a disabled control is not posted. For a model-backed form, the listener writes a same-shape placeholder with a phase line into the region that will receive the result, inside the outgoing page, while the request is in flight; it starts the 10-second line. Because the page still navigates, the result arrives on the new page and a `role="status"` line names the outcome there.

Every handler that reloads after a POST reloads only after a success; a failure shows the cause instead. The raw-JSON dead ends (a blank fact, a blank brief) re-render the form with the cause and the typed values. The invalid timeout keeps its typed value and its named cause. After a navigation, focus moves to the main heading. Every server page gains a skip link. With the script off, every form still posts, every page still renders, and nothing depends on the placeholder.

On the memory islands, "Ask AI for observations" takes the pending state and ignores a repeat click; the learning switches show their pending state; "Approve all" shows progress; the first load is a skeleton; a failed refetch keeps the data and says so in place.

### Instruments and evidence

`tools/mock_endpoint.py` gains `--delay-ms`, default 0, so a four-second model wait is repeatable. The layout audit gains a pending-state pass: hold every non-GET request, press each control, record whether anything visible changes, and report `silent` and `disabled-only` counts per page and overlay. The same tool gains the long-values fixture. Screenshots of every pending state, the audit output, the commands and the counts land in `docs/evidence/2026-11-24-feedback/`.

The audit stays out of `tools/ci_local.py`, for the reasons spec 026 recorded. The gate's contract stays 7/7, and the audit is a tool a person runs.

### What this wave will not do

It does not swap page content on server pages without a page load. It does not wire an HTTP transport for plugins and does not remove the wizard's "A web page" choice; that is the founder's decision. It does not add a job object, a tray, completion notifications, streaming replies, real server-side progress phases or cancel. It does not change type sizes. It does not change the tracker payload, the insight pass, the card routing or the marketplace's install mechanics beyond the notice and the state it names.

## Testing Decisions

A good test asserts what a person sees and does: a control that cannot be pressed twice, a label that changes to the continuous form, a placeholder with the incoming shape, a result that replaces it in place, a page that keeps its content on a refetch, a number that prints in full or shows compact with the exact value reachable, a counter that matches its rows, a tracker value that appears once. It does not assert private helper names, a particular CSS class string beyond the declarations this wave owns, or a screenshot as the only proof.

The CSS contract suite is the model. `frontend/src/test/tokens.test.ts` reads the stylesheet source and asserts exact declarations; extend it with the pending pulse and its reduced-motion freeze, the hero grid's fallback placement, the `.w-timeline` columns, the scoped `.w-list-meta` rule, and the same timeline contract in the server sheet. The server-sheet half reads `pages.py`, so the two sheets cannot drift.

Component tests use `@testing-library/react` with role and behaviour assertions. `frontend/src/test/cards.test.tsx`, `tracker-cards.test.tsx`, `describe-plugin.test.tsx` and `brief-decisions.test.tsx` are the prior art. Extend `tracker-cards.test.tsx` to assert that a live tracker shows its value, change, workbook, pace and history once and that the remaining reading is behind a disclosure; assert that the press is still reachable. Add a busy-state test that uses fake timers around the 100ms boundary and asserts the label, `aria-busy`, the second press being ignored and the size class staying the same. Add a Desk health test with a widget-less card, a network-only card and a never-run card and assert the rows, the two counters and the word "never". Add a digest test with a malformed start and assert the card still renders.

Server tests read rendered HTML and the served script through `tests/server_harness.py`; `tests/test_server_shell.py` and `tests/test_ui_wave2.py` are the prior art. Add assertions that the served page carries the skip link, that a model-backed form's region is present for the placeholder, that the raw-JSON dead ends answer the form with the cause and the typed value, and that the page script contains the one delegated submit listener. The no-script path is tested by posting the form directly without running the script.

The payload pins are the guardrail. `tests/test_insight_seam.py:64-73`, `tests/test_plugin_setup_http.py`, `tests/test_plugin_config.py` and `tests/test_file_selection_chain.py:46,290` must pass without changing the wire shape. A test that needs to change one of those pins is a signal that the wave crossed the "display only" line.

Every fix ships with a failing-first test; the red evidence is kept in the pull request. The audit and the evidence pack are the whole-wave proof, not a unit test.

## Out of Scope

- In-place results on server pages without a page load. It needs a re-initialisation entry for the page script; the memory and settings pages are excluded first. Recorded as a follow-up.
- An HTTP transport for plugins and the wizard's "A web page" choice. This is the founder's decision. This wave retracts spec 015's promise and does not turn the network on by itself.
- A job object with a tray and completion notifications, streaming replies, real server-side progress phases, or cancel.
- Type sizes, including the 458 `tiny-type` findings from the first wave.
- A visual redesign of the bento, the marketplace, the memory pages or the server pages. This wave fixes truth and flow, not composition.
- Changing the tracker payload, the insight pass, the card routing, `_format_number` or a value binding.
- Changing the marketplace's install, signature, policy or consent mechanics beyond the "cannot run on this desk" notice and Remove action.
- Rerunning or rebaselining spec 026's text-fit audit. This wave's audit is a separate evidence run.

## Further Notes

### The Page watch placeholder

D2 keeps the network-only plugin off the home screen. The desk's own Page watch placeholder (the wireframe shown when no watch card exists, `Brief.tsx:362-383`) still offers "Add a page", which leads to the plugin that cannot run. Recommendation: retract that one action as well and let the wireframe say "This desk cannot read web pages yet". It is the same honesty rule, and it is the difference between a home screen that tells the truth and one that hides a dead end behind a desk card. Ticket 04 carries it provisionally; if the founder wants the placeholder untouched, the notice on the plugin card still tells the truth.

### The shortest visible busy state

F1 starts the busy state at 100ms. A request that finishes at 130ms would show a busy state for 30ms. Recommendation: no minimum display time in this wave. Holding a busy state after the work ends makes a fast desk feel slow, and the 100ms delay already removes the common flash. If the audit photographs a flicker that reads as a defect, a 300ms floor is a small follow-up.

### A malformed event start

The digest guard can hide the item, drop only the time, or print the title with no time. Recommendation: keep the item and drop only the time. A calendar event with a broken start is still an event the manager needs to see, and hiding it would make the digest lie by omission. The title and detail carry the meaning; the time slot says "time unreadable" when the value cannot be parsed.

### The network retraction

The durable record is the known-limitation entry and this spec. Recommendation: no application-wide banner. A banner on every desk would be noise for a limit that only touches the Page watch plugin. The marketplace notice, the plugin card, the Installed page and the known-limitations entry are enough, and the pull request and the wave report tell the founder directly.

### The two inventories

The 54 controls, the 26 that meet the standard, the 3 silent, the 12 disabled-only, the 13 data loads, the 7 agent moments and the 66 server controls (34 top, 28 medium, 4 polish) are the measured inventories from the read-only survey behind this brief. They are the baseline the pending-state audit is checked against, not a second count this spec invents.
