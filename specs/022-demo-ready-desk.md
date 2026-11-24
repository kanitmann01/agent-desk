# Spec 022: Demo-ready desk

Status: ready-for-agent (2026-11-23). Decisions on the first screen and the
cut list are the CTO session's recommendations, not yet confirmed by the user
(see Further Notes). `GLOSSARY.md` at the repo root is the vocabulary.
Reviewed against the code by an independent advisor on 2026-11-23; its
findings are folded in (see Further Notes).

## Problem Statement

The founder's words: "everything is everywhere, it does not feel like a
finished product", "it takes users 15 minutes to find how to add their own
API key and even then it's not working", "50 on and off toggle switches in
settings", "no clear instructions about how memory works", "tools that do
NOTHING".

A live audit on 2026-11-23 (fresh data folder, the real app at 1264x805,
every screen) reproduces every complaint and finds one root: the desk hides
the one thing it needs, then denies it once it is given.

- **The first screen never asks for an AI key.** The home screen's primary
  action is "Add plugin", which opens the plugin wizard. The key form is
  4,193 pixels down a 10,394-pixel Settings page, the sixth of sixteen
  sections.
- **The founder's key is stored nowhere.** The real key store holds zero
  connections and the Windows keychain holds no entry for the app. The real
  audit log shows 24 model calls and every one failed, the last with "the
  assistant job is unbound: bind it to a connection on the Settings page,
  star a default connection, or set AGENTDESK_LLM_BASE".
- **A saved key works and the desk says it does not.** With one saved
  connection the assistant answers, and three surfaces disagree: the
  dashboard reads "Research off" and "No company endpoint configured", the
  Settings "Endpoint" card reads "NOT SET: Not configured", and "Jobs"
  reads "NONE BOUND" with seven unbound rows. One line causes the first:
  the dashboard's source status reads the pre-018 setting and never the
  connections store.
- **A saved connection sends the wrong model.** With exactly one
  connection, every call is sent with the model `gpt-4o-mini` whatever the
  provider. OpenAI accepts it; Anthropic, OpenCode Go, Groq, Gemini,
  DeepSeek, Mistral and company gateways reject it. The only fix in the
  product is to type a model into the Jobs forms.
- **Settings is an admin console.** Sixteen sections, 25 on/off buttons plus
  12 selects, the six recommendation switches rendered twice, three
  company-branded themes as the first card, and IT diagnostics (gate
  probes, registry folder, extra host names) beside everyday controls. The
  product's own principle says a better default beats a setting.
- **Memory cannot explain itself and has not learned.** The real store
  holds 8 facts, all from the sample seed, last written 18 November.
  Automatic saving is off on the founder's folder: a one-time migration
  wrote "off" for every folder that predates the build, and it was never
  switched back. With no working model there was nothing to learn with.
  The page speaks of entities, observations, excerpts and provenance.
- **Surfaces with no job in the morning loop are one click away.** The
  marketplace shows six sections (including Admin and a Trust center) for
  three plugins; the Admin page tells a non-technical user to set an
  environment variable; Capabilities opens with "Gate 2: uv bootstrap".
- **The demo script is a platform tour.** `DEMO.md` spends four of ten
  beats on plugin publishing, peers and registry, and the model never
  runs.

## Solution

One path from first run to the morning loop, and nothing on screen that has
no job in it.

1. **The home screen asks for what it needs, in order.** A Get started
   strip above the tiles lists three one-click steps: add your AI key, open
   your sales workbook, connect your calendar, with a one-click "Try it
   with sample data" beside them. It disappears when all three are done.
   "Add plugin" leaves the hero for the Plugins page; "Customize" stays
   reachable but quiet.
2. **The AI key is the first thing in Settings and it tells the truth.**
   Settings becomes six sections: Your AI (the default), Your tools,
   Memory, Preferences, Activity, Advanced. Saving a key offers the model
   in the same form, pre-filled with the provider's default, verifies it,
   and every surface then agrees that the AI is connected. Every call uses
   the model that connection chose.
3. **Memory explains itself in plain words, can be emptied in one click,
   and is switched on for the founder.**
4. **What has no job in the morning loop leaves navigation** (hidden, not
   deleted, before the demo): marketplace Admin, Trust center, Publishers
   and Studio, and the Capabilities link.
5. **The demo is one manager's morning**, scripted, rehearsed and measured
   by a frozen readiness check.

## The morning loop (proposed answer to "Decide the core morning loop")

Each morning Priya opens the desk and reads one screen: what changed in
her pipeline since yesterday (Pipeline, Moves), what is due today (Digest,
Decisions) and what is worth knowing (Tracker, Page watch). The desk
proposes what to do next as suggestion cards she accepts or dismisses in
one click. She can ask a question in plain language and the desk answers
with her dashboard as context. Everything the desk learns about her is in
Memory, visible and editable. The three inputs are one AI connection, the
sales workbook and the calendar.

Outside the loop for now: building and publishing plugins, peer sharing,
presentation packs, trust and policy administration, environment probes.

## User Stories

1. As Priya, I want the home screen to tell me the three things to connect before anything else, so that I am never left guessing why cards are empty.
2. As Priya, I want "Add your AI key" to be the first step with one click, so that I do not spend fifteen minutes looking for it.
3. As Priya, I want to try the desk with clearly labelled sample data in one click, so that I can see what it does before I connect anything.
4. As Priya, I want the strip to disappear once everything is connected, so that it never becomes clutter.
5. As Priya, I want to hide the strip if I cannot finish setup today, so that it does not block my dashboard.
6. As Priya, I want Settings to open on my AI, so that the one thing I must configure is already on screen.
7. As Priya, I want to add a key by choosing a provider and pasting the key, so that I do not need to know base URLs or headers.
8. As Priya, I want the model pre-filled with one that works for my provider, so that I am not asked for a name I have no way of knowing.
9. As Priya, I want the save to check the key and say plainly whether it works, so that I know immediately.
10. As Priya, I want the dashboard, Settings and the assistant to agree on whether my AI is connected, so that I never re-enter a key that is already saved.
11. As Priya, I want a connection's model to be the one every call uses, so that a non-OpenAI provider works the first time.
12. As Priya, I want the key kept in this machine's keychain across restarts, so that I enter it once.
13. As Priya, I want the assistant, when no key is saved, to say "Add your AI key" with a button, so that my first question is not an error about jobs and environment variables.
14. As Priya, I want the question bar to offer "Connect your AI" when no key is saved, so that I am not invited to ask before it can work.
15. As Priya, I want Settings to show a handful of controls per section, so that I am not faced with fifty switches.
16. As Priya, I want the everyday switches only, so that defaults serve me until I have a reason to change them.
17. As Priya, I want the advanced switches grouped and out of the way, so that they are there when a technical owner needs them and invisible to me otherwise.
18. As Priya, I want the three themes kept but not the first thing in Settings, so that appearance is a preference, not a task.
19. As Priya, I want each Settings section to have one obvious purpose in plain words, so that I know where to look.
20. As Priya, I want one place to see what the desk did (Activity), so that I am not sent between three screens.
21. As Priya, I want the Memory page to explain in plain sentences what it remembers, how it learns and that I control it, so that I trust it.
22. As Priya, I want the desk to learn by itself from how I work, so that I never have to file facts by hand.
23. As Priya, I want every learned fact listed with where it came from, so that nothing is guessed in secret.
24. As Priya, I want to edit or forget one item, so that a wrong fact does not linger.
25. As Priya, I want to forget everything in one click with a clear confirmation, so that I can start clean.
26. As Priya, I want to switch learning off, so that nothing new is saved when I do not want it.
27. As Priya, I want the left navigation to contain only what I use, so that every entry has a job.
28. As Priya, I want the Plugins page to offer "Find plugins" and "Installed", so that I am not shown administration for three plugins.
29. As Priya, I want the plugin wizard reachable from Plugins, so that describing a plugin stays possible without being the home screen's main action.
30. As Priya, I want to keep the card controls that only Customize has today (check off a commitment, re-test a source, run a skill), so that simplifying the home screen loses nothing that works.
31. As Priya, I want the workbook, calendar and mail each to show whether they are connected with one action to connect, so that sources are one screen.
32. As the founder, I want a demo script that tells one manager's morning, so that tomorrow's demo is a story and not a tour.
33. As the founder, I want a mechanical readiness check that boots the real app and walks the first ten minutes, so that "it works" is a number and not a claim.
34. As the IT reviewer, I want every change the desk makes by itself still recorded in Activity, so that the audit story is unchanged.
35. As the technical owner, I want the hidden surfaces still reachable by address, so that nothing is lost before the deletion pass.

## Implementation Decisions

**One truth for "is the AI connected".** The dashboard's source status and
the Settings AI section both ask the existing per-job resolution hub whether
it can serve the assistant job. The pre-018 endpoint rows remain one of the
hub's legs and nothing else reads them for status. The old "Endpoint"
Settings card is retired; its presentation timeout moves to Advanced under
its existing anchor.

**A connection carries its model.** The connections store gains a model
column, added by a guarded `ALTER TABLE` so existing stores upgrade on
boot. The connection form gains a Model field, pre-filled with the
provider's default model: a list when the save-time model check returns
one, a text field otherwise. Each preset records one default model, taken
from the provider's own documentation on 2026-11-23. The resolver's
precedence, the same on every leg: the job's own model if one is set, then
the serving connection's model, then the environment's model. Nothing that
works today changes: a connection saved before this spec has no model and
keeps the environment's. A connection without a model is shown with
"Model: (default)" so the state is visible. The create and update
endpoints accept the field; the JSON listing returns it.

**Settings has six sections.** A section bar under the heading links to
Your AI, Your tools, Memory, Preferences, Activity and Advanced. With
scripting the page shows one section; without it every section renders in
bar order and the bar is an index. The default section is Your AI.

The anchor map (every existing address keeps working and opens the
section that holds it):

| Section | Section id | Cards and anchors inside it |
| --- | --- | --- |
| Your AI | `ai` | `connections`, `jobs` |
| Your tools | `tools` | `sources` (workbook, calendar, mail) |
| Memory | `memory` | `learned`, the Learn automatically switch, Forget everything |
| Preferences | `preferences` | the six preferences (id unchanged), `appearance` |
| Activity | (its own page) | the activity trail, the questions log, the CSV export |
| Advanced | `advanced` | `desk`, `agent`, `desk-check`, `updates`, `registry`, `machine`, `record`, `skills`, `questions`, `endpoint` (timeout only), the computer check |

- **Your AI**: status first, then each saved connection as a row (label,
  provider, model, state, Test, Edit, Remove), then "Add an AI" with
  provider, key and model. Label, base URL, extra headers and the default
  star sit behind a "More options" disclosure. Under it, "What uses your
  AI" states in one sentence which connection serves everything, and the
  seven per-job forms sit behind a disclosure labelled "Use a different
  model for one of these". The words "job", "binding", "bound" and "NONE
  BOUND" do not appear.
- **Your tools**: the workbook, the calendar and the mail folder, each with
  its live state and one action.
- **Memory**: the plain-language explanation, a link to the Memory page,
  "Learn automatically", the two "learn from my asks" switches, and
  "Forget everything".
- **Preferences**: the six personal preferences, then the three themes.
- **Activity**: the existing activity page, reached from the section bar.
- **Advanced**: the remaining cards in their current order. Its first line
  reads: "The defaults are right for most people. Change these only if you
  know why." The six recommendation switches are rendered once (the copy
  in the Agent card is removed). The computer check is linked from here
  only, labelled "Computer check (for IT)".

**The home screen.** The dashboard payload gains a `setup` object: three
steps in order (`ai`, `workbook`, `calendar`), each with a title, a
reason, an address and a done flag. A sample source does not make a step
done. The strip renders above the tiles while any step is open, offers
"Try it with sample data" while no source is connected, "Not now"
(remembered in the browser, replaced by a small "Finish setup" link in the
header), and names the sample data with a "Hide sample data" action while
it is in use. "Add plugin" leaves the header for a "Describe a plugin in
plain English" button on the Plugins page. "Customize" stays in the
header as a quiet secondary button, because it is the only place the
commitment check-off, source re-test and skill-run controls exist.
Without an AI the question bar's button becomes "Connect your AI".

**Memory.** The Memory page leads with "How memory works" (under 90 words,
plain language) in a block with the id `how-memory-works`, then what it
learned with origin and Forget per item, then a "Forget everything" form
posting to `/memory/forget-all`, with a confirmation that says it cannot
be undone. The action removes every fact and everything derived from
facts through the removal machinery the page already uses, is recorded in
the audit log as `memory.forget_all`, and leaves the encryption key and
the settings alone. The page offers the form only once there is a fact
to forget. Learning is on for a new folder and stays on across restarts
(corrected 2026-11-23): the boot that creates a folder now stores the
explicit "on" value, because the older rule that wrote "off" for any
folder that already existed took a new folder's second start for an old
folder and switched learning off by itself. A folder from an earlier
build keeps "off", and the founder's folder, which already holds that
row, is switched on by hand during demo setup.
Maintenance tools (the graph, the sweep, encryption) stay behind one
disclosure.

**Navigation.** The rail is unchanged: Dashboard, Inbox, Assistant, Agents,
Memory, Mail (only while the mail digest is on), Plugins and Settings.
"Marketplace" is renamed "Plugins" in both rails (the React one and the
server-rendered one); its own navigation offers "Find plugins" and
"Installed", and "Find plugins" carries the "Describe a plugin in plain
English" button. Publishers, Studio, Admin and the Trust center keep their
addresses and lose their links. No other navigation changes tonight.

**Copy.** On-screen language follows `GLOSSARY.md` and PRODUCT.md's voice:
no "job", "binding", "endpoint", "provider", "capture", "retain" or
environment variable names where a user reads. The unbound sentence becomes
"Add your AI key" with the Settings address. Desk health's row "Research"
is labelled "AI".

**Workstreams and order.** One integration branch carries this spec as one
pull request. Sub-branches land on it in this order: (1) status truth and
the `setup` object, (2) a connection's model, (3) Settings sections, (4)
the home screen strip and Plugins navigation, (5) Memory, (6) the demo
pack and the readiness tool, (7) evidence and the review pass. (1)
precedes (4); (2) precedes (3); everything else is independent.

## Testing Decisions

A good test drives the product the way a browser does and asserts on what
a user can see or do: a page's words and controls, an HTTP status, a
payload field, a row in the audit log. It does not assert on helper
functions, CSS literals or component internals.

**Seams.** One new seam and two existing ones.

- **New: `tools/demo_readiness.py`**, stdlib only and hermetic. It boots the
  real app in-process on an ephemeral port over a fresh temporary folder,
  with a file-backed stand-in keychain (so a restart can read the key
  back) and the local mock model endpoint. It walks the first ten minutes
  over HTTP exactly as the browser does, prints one PASS or FAIL line per
  check and ends with `METRIC ready=<passed>`. The list below is frozen:
  a check may be reworded, never removed, and a new one is a new number.
- **Existing: the server harness** in `tests/` (page renderers, routes,
  the resolution hub) for unit-level behaviour.
- **Existing: vitest with Testing Library** for what the React home screen
  and the Plugins navigation render.

**The frozen readiness list (22 HTTP checks and 2 browser-render checks).**

| # | Check | Passes when |
| --- | --- | --- |
| R01 | Fresh desk is honest | `/api/dashboard` has `sample: false`, workbook and calendar `not_connected`, and `setup` offers a way to try sample data |
| R02 | Fresh desk says the AI is not connected | `research-endpoint` status is `not_connected` |
| R03 | Setup steps exist | `setup.steps` has ids `ai`, `workbook`, `calendar` in order, none done |
| R04 | Settings opens on the AI | in `/settings`, the key form (`id="connection-form"`) precedes every on/off button (`button[data-setting]`) |
| R05 | The everyday sections are short | at most 4 on/off buttons precede `id="settings-advanced"` in `/settings` |
| R06 | Settings never says "NONE BOUND" | the string is absent from `/settings` |
| R07 | Assistant without an AI says what to do | `/assistant` links to `/settings#ai` with the words "Add your AI key", and has neither "unbound" nor "AGENTDESK_" |
| R08 | Asking without an AI is honest | `POST /assistant/ask` is not a 5xx and the page shown says "Add your AI key" |
| R09 | Memory explains itself | `/memory` has `id="how-memory-works"` with 200+ characters of text (reworded 2026-11-23: the form moved to R20, because the page offers it only once a fact exists) |
| R10 | Learning is on by default | in `/settings`, the switch `button[data-setting="memory_auto_approve"]` reads "On" for a fresh folder |
| R11 | The rail is short and whole | every rail link on `/inbox` is 200, there are at most 8, and none is to Peers, Activity or Capabilities |
| R12 | IT-only surfaces are not offered | in `/settings`, the computer check's link appears only after `id="settings-advanced"`, and no rail page links to `/peers`, `/marketplace/admin`, `/marketplace/trust`, `/marketplace/publishers` or `/marketplace/studio` |
| R13 | A key can be saved with its model | the create form answers 303 and the JSON listing carries the model |
| R14 | The desk reports the AI connected | `research-endpoint` is `connected` and the `ai` step is done |
| R15 | Settings agrees | the Your AI section has neither "NOT SET" nor "Not configured" and shows the model name |
| R16 | The chosen model is the model used | after one assistant turn, the mock endpoint received the chosen name, not `gpt-4o-mini` |
| R17 | The assistant answers | the page shows the mock's reply |
| R18 | The AI survives a restart | a second boot over the same folder still reports connected and still answers |
| R19 | Learning happens by itself | after one turn stating a durable fact, `/memory` lists it with the assistant as origin |
| R20 | Forget everything works | the Memory page offers a form posting to `/memory/forget-all`; after the post, `/memory` shows zero facts and a later answer no longer carries it |
| R21 | Forgetting is recorded | the audit export gains a `memory.forget_all` row |
| R22 | A real workbook completes its step | registering a workbook from outside the sample folder makes the `workbook` step done |
| R23 | All three steps complete | after a real calendar file is connected, every step is done |
| R24 | (vitest) The home screen leads with setup | with an open step the Get started strip renders above the tiles; with all done it does not render |
| R25 | (vitest) Plugins lists two sections | its navigation has exactly "Find plugins" and "Installed" |

**Prior art.** `tools/demo_walkthrough.py` (real servers, temp folders,
HTTP as the browser), `tests/test_server_keys*.py` and `tests/test_keys*.py`
(the store, the hub, the form), `tests/test_server_job_routing.py` and
`tests/test_server_settings*.py` (page renderers and anchors),
`frontend/src/dashboard/*.test.tsx` and `frontend/src/marketplace/*.test.tsx`.

**Gates.** Each change passes the targeted tests for what it touches and
the frontend type check and tests before it lands; the integration branch
passes the full suite (`python tools/ci_local.py`) before the pull request
is marked ready. Evidence: the readiness output and screenshots at
1264x805 of every changed screen, under `docs/evidence/2026-11-23-demo-ready/`.

## Acceptance Criteria

- `python tools/demo_readiness.py` prints 23 PASS and `METRIC ready=23` on a
  clean checkout; R24 and R25 pass under vitest.
- `python tools/ci_local.py` exits 0.
- A person following `DEMO.md` on a fresh folder reaches the morning loop
  (all three steps done) in under three minutes and without opening a
  terminal or typing a path.
- At 1264x805: a fresh home screen shows the Get started strip above the
  tiles; Settings opens on Your AI with no on/off switch above the fold;
  after saving a key, no screen says the AI is not configured.
- The real instance on the founder's machine: the sample memory is purged
  (after a backup), learning is on, and the founder can add a key once.

## Out of Scope

- Loading sample data automatically on first run (rejected on review: it
  would change what every fresh test boot sees, silently, the night before
  a demo).
- Hiding Customize (rejected on review: it holds the only commitment
  check-off, source re-test and skill-run controls).
- Gating peer discovery behind a switch (rejected on review: nothing
  starts it on boot and no link reaches it, so the change would only break
  tests).
- Deleting the hidden modules and their tests (a follow-up pull request
  after the demo, per the cut list).
- Hermes as an explicit plugin, connection or entry point, and any new
  enterprise connector. That the agent system underneath is to be Hermes,
  or Hermes-like and autonomous, is the founder's direction of 2026-11-23;
  it is not part of this spec and is not yet planned (see the correction
  at the top of spec 023).
- Changing how memory extracts facts (the extraction prompts), embeddings,
  or encryption.
- A guided full-screen onboarding, product tours, tooltips.
- The inbox card's action set, the Agents page, the wizard's questions.
- Themes and the visual system (unchanged; see `DESIGN.md`).
- Autostart, packaging, the update channel.

## Further Notes

**Decisions pending the user's confirmation.** The tracker's wayfinder map
"Map: simplify Agent Desk to its core loop" carries three open decisions:
the core morning loop, the cut list, and the Hermes and connector
architecture. On 2026-11-23 the user did not answer the first-round
questions, so this spec executes the session's recommendations and the
tickets stay open as proposals: the loop above; hide tonight and delete
after the demo; no Hermes runtime before the demo. The map's earlier
"Decisions so far" entries that keep Studio and the presentation plugin
were written by an earlier agent without a closed ticket; this spec hides
Studio from navigation and leaves presentations untouched.

**Direction from the founder (2026-11-23).** "I want the underlying system
of agents to work like hermes and grok bot, making automatic connections
between what already exists and what the plugins bring. Plugins are just
data aggregators and connectors." Nothing in this spec adds a Hermes
plugin, connection or entry point, and the "Hermes (local)" connection
this session was about to propose is withdrawn. The decision is recorded
on #276; the first slice is spec 023.

Later the same day the founder corrected one reading: "But i want the
underlying system to be hermes (or hermes like) i just said don't make it
into an explicit plugin. The feeling should be autonomous like it's with
hermes." So "Hermes is never a runtime" was never the founder's decision;
only an explicit plugin (and a separate assistant entry point) is ruled
out. The engine question is open and is recorded at the top of spec 023.

**What the implementation corrected (2026-11-23).** Three decisions above
were changed while building, each because the product showed otherwise:

- Learning switched itself off at a desk's second start (see Memory).
- A source wired to the sample set is reported as "sample", never as
  "connected", so the source line, Desk health and the setup steps agree
  that nothing real is attached while sample data is on.
- The Settings readiness checks read attributes regardless of quote style
  (the page quotes them with single quotes). R09 and R20 were reworded:
  the Memory page offers "Forget everything" only once a fact exists, so
  the form is checked by R20. No check was removed.

**What the advisor review changed.** It removed first-run sample loading,
the Customize cut and the peers switch; added the key-store migration and
the full resolver precedence; required preset default models; defined the
anchor map and the page hooks the readiness checks read; and moved two
checks to vitest. It also flagged that the founder's stored "learning
off" row must be switched on by hand, which removing a migration cannot do.

**What the audit verified by running it.** Saving a key in a fresh folder
succeeds; killing and restarting the app returns the key from the Windows
keychain; with one saved connection the assistant, memory retain and
twelve calendar breakdowns all succeed against the local mock endpoint;
the dashboard nevertheless reports the Research source as off. The audit's
morning must-fixes (the collapsed Decisions cell, the inbox action button,
the stale workbook figure) are already fixed on `main`.

**Not verified.** A real provider (no key was available to the session);
the demo machine's own data folder beyond non-secret metadata. A restart
invalidates the browser session (sessions live in memory); the launcher
opens a fresh start link, and `DEMO.md` carries that beat.
