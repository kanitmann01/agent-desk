# DEMO.md: the executive walkthrough script

The presenter's script for a 12 minute demo of Agent Desk on one corporate
Windows laptop. Every click below exists in the shipped product; the whole
path is proven headless by `python tools/demo_walkthrough.py` (20 steps, run
it once before the demo to warm up). Nothing leaves the machine except
derived abstractions sent to a corporate LLM endpoint, and this demo never
needs one: the wizard runs its deterministic path with no endpoint
configured.

## Before the demo (5 minutes of prep)

1. Fresh data folder so the story starts empty. In cmd:
   `set AGENTDESK_DATA=%TEMP%\demo-desk-a` before starting Desk A below
   (or move `%USERPROFILE%\.agent-desk` aside). Nothing else to clean.
2. A registry folder the demo can publish into without touching the
   checkout: `xcopy /E /I registry %TEMP%\demo-registry`. You will paste
   this path into Settings during beat 5.
3. Optional, for the peers beat: a second terminal window ready for
   Desk B (beat 8 has the two lines it needs).

## The URL flow (how it starts)

Double-click `tools/agent-desk.cmd`. It finds Python, starts the dashboard
windowless, prints `Agent Desk is running: http://127.0.0.1:8765/auth/<one-time-token>`
and opens the browser at that link itself. The link is the session: it
becomes the cookie, there is no sign-in screen. If the browser did not
open, copy the printed link; if port 8765 was taken, the printed link
already names the port that actually opened.

SAY: one double-click, no admin rights, no terminal. The server binds
127.0.0.1 only and every request carries the session that one-time link
minted.

## The rail (the whole product in one sentence)

The left rail is the tour: `/` the dashboard, `/inbox` what the agent
initiates, `/assistant` research and the assistant, `/activity` every
decision with its audit row, `/memory` facts she keeps (recall only),
`/mail` the metadata-only mail digest (off by default), `/capabilities`
the environment gates and sources, `/plugins` the plugin lifecycle and
the registry, `/peers` peer sharing, `/settings` every switch including
the endpoint. Click through them once, fast; every page answers.

## Beat 1: the honest empty dashboard (1 minute)

CLICKS: land on `/`. The dashboard shows the built-in cards in their
designed empty states: the sales card offers `Connect a workbook`, the
commitments card says no calendar data yet, the research panel says no
company endpoint is configured. Freshness dots everywhere, no spinners.

SAY: every card tells the truth about why it is empty. Amber is a
designed state with a cause, never a fake green.

IF IT FAILS: an empty card with a cause is the shipped state; read the
cause line out loud, that is the product working.

## Beat 2: sample data on (30 seconds)

CLICKS: go to `/inbox`. The empty state offers the button
`Show me what this looks like with sample data`. Click it. Four cards
appear, each wearing a `Sample` tag and a `Sample data:` origin line.
The switch also lives in `/settings` as `Sample data` (turn it off there
later; removal takes exactly what was seeded).

SAY: labelled sample content, one switch, and turning it off removes
exactly what it added. None of it can be mistaken for live data.

IF IT FAILS: the Settings switch at `/settings` does the same thing;
the inbox button is a shortcut, not the only path.

## Beat 3: inbox actions, every one reversible (2 minutes)

CLICKS, in order on `/inbox`:

1. On `Overnight sales update, ready to walk through`: `Accept`.
2. On the brief card: edit the `Draft` box, `Save draft` (the draft
   updates, the card stays waiting).
3. On `Feature request exported to the owner queue`: pick `One hour` in
   the Snooze select, `Snooze`; then type into `What should the agent
   clarify?` and `Ask for more info` (the snooze ends early, the
   instruction rides the card).
4. On the brief: `Dismiss`; it drops to the `Dismissed` shelf at the
   bottom; click `Restore` there. The shelf says recoverable for 30 days.
5. Open `/activity`: every action above has its row (approved, edited,
   snoozed, more-info, denied, restored, sample on).

SAY: the agent initiates, the human decides, and every decision is in
the activity log. Dismissal is recovery, not deletion.

IF IT FAILS: `/activity` and `/audit/export.csv` are the same truth from
two angles; open either and read the rows.

## Beat 4: create a plugin from English, then give it its data (2.5 minutes)

CLICKS: back on `/`, click `Add plugin` in the header. The describe
screen opens (`Describe a plugin`). Type:
`Watch this workbook and show me the 24-hour change` and submit. The
questions screen appears; with no endpoint configured it says so and
asks the standard questions (radio buttons, defaults pre-selected).
Click `Ask` on each. The preview screen shows the widget on sample
rows plus the consolidated summary: what it does, what it reads (for a
workbook ask: `a workbook you pick in setup`, nothing is guessed),
what it can never do (no code, no shell, no network), how to remove
it. Click `Add widget`. The `Added` screen shows what was installed
(id, version, the Pilot badge) and offers `Set up its data`. Click it:
on the plugin's manage view, `Set up a new instance`, name it, `Open a
workbook`, pick `sample-sales.xlsx` from the sample folder, click the
`Amount` header, switch the assignment to `Row label` and click
`Deal`, select row 1 (or Select all), `Continue`, `Confirm`. The card
on `/` turns fresh: row 1's amount, the workbook's name, and the pilot
badge it earned at install.

SAY: plain English in, a validated declarative plugin out. One approval,
and it installs in pilot mode, already asking for the one thing no
wizard can know: where your data lives. No endpoint was needed for
this.

IF IT FAILS: the preview names what it would read (`a workbook you
pick in setup` for a workbook ask); if the words cannot be built
safely the wizard says so and exports the request to the inbox instead
of guessing. That dead-end is the honest path. Until a workbook is
picked and confirmed, the plugin's card says `Set up` instead of
showing numbers; Beat 7's excel-report card carries the registry
plugin's story once a workbook is connected.

## Beat 5: publish it to the registry (1 minute)

CLICKS: the `Added` screen shows the pilot badge and a
`Publish to the registry` button. First point the app at the prep
folder: `/settings`, section `Plugin registry`, paste
`%TEMP%\demo-registry` into `Registry checkout folder`, `Save path`,
then `Open the plugins page`. Now click `Publish` on the wizard plugin
(the Plugins page lists it with lifecycle actions). The
`From the registry` section lists it beside the shipped plugins, and
the origin line under it names the folder and `(from setting)`.

SAY: publishing copies the validated tree into the registry as a
digest-pinned local release, append-only, and the same CI validator
checks it. No git tag, no network.

IF IT FAILS: publish refuses by name when there is no registry
(`publish:no-registry`) or on a duplicate version; the refusal names
the fix (save a registry path in Settings).

## Beat 6: install a shipped plugin, amber with its cause (1 minute)

CLICKS: still on `/plugins`, find `excel-report` under
`From the registry`, click `Install`. It installs in pilot mode. Its
card on `/` renders amber: `no file matches ${workspace}/reports/*.xlsx`.

SAY: installs are pinned and verified (digest plus the shared
validator), and a plugin whose truth is not available yet says so in
amber with the precise cause. The shipped card plugins are
`excel-report` (this card) and `competitor-watch` (the Page watch
card); `competitor-watch` reads an outside page through a network
allowlist, so this demo leaves it out. The presentation starter is a
template, not a dashboard card.

IF IT FAILS: amber with a cause is the designed state; read the cause.

## Beat 7: connect the workbook, real numbers (1 minute)

CLICKS: open `%TEMP%\demo-desk-a\sample` in Explorer (the sample seeding
made `sample-sales.xlsx`; any .xlsx works). Copy it into
`%TEMP%\demo-desk-a\workspace\reports\`. Back on `/plugins`, click
`Re-test` on excel-report. The card turns fresh with bound numbers
(rows seen, the workbook name). Optionally, on `/`, click
`Connect a workbook` on the sales card and pick the same file: the
built-in sales widget goes live too.

SAY: the host executes the plugin's declared data source through the
built-in pipeline and binds real values into its card. The moment the
truth exists, the card shows it.

IF IT FAILS: a locked or unreadable workbook stays amber with the
cause; that honesty is the feature. Re-test is always one click.

## Beat 8: two desks, peer to peer (2 minutes)

CLICKS, Desk B first: in the second terminal (cmd):
`set AGENTDESK_DATA=%TEMP%\demo-desk-b` then
`python -m agentdesk.server`. It prints its own one-time link (its own
port) and opens a second browser window: that is Desk B.

1. On Desk A `/plugins`: click `Share with peers` on the wizard plugin.
2. On Desk A `/peers`: click `Generate a fresh code`; read the code.
3. On Desk B `/peers`: type Desk A's address `127.0.0.1:8765` and the
   code, click `Pair`. Both desks now pin each other's identity.
4. Desk B's paired list shows the shared plugin, version 0.1.0, not
   installed here; click `Install`. The card renders on Desk B's
   dashboard with the same digest verification a registry install runs.

SAY: nothing centralized: a single-use pairing code, a token-gated
read-only endpoint, digest-verified installs. When the publisher's
version bumps, this page shows update-available and one click updates
(the walkthrough script proves that bump end to end; the desk on the
LAN is discovered but the server stays loopback-only, and it says so).

IF IT FAILS: a peer that cannot be reached stays listed with its cause
(`could not be reached`); wrong pairing codes are refused by name and
are single-use.

## Beat 9: customize the dashboard (1 minute)

CLICKS: on `/`, click `Customize` in the header. Drag a card's handle
onto another (or use `Move up` / `Move down`), click `Rename` on one and
`Save title`, click `Hide` on the sales card; it drops into the
`Hidden cards` strip with a `Restore` button. Click `Restore`, then
`Done customizing`. Every change saved itself; there is no save button.

SAY: the dashboard is personal: order, titles, visibility, per desk,
and hiding is always recoverable.

IF IT FAILS: customize needs the layout endpoint; if it cannot reach
the server the panel says so and changes nothing.

## Beat 10: endpoint honesty in Settings (1 minute)

CLICKS: `/settings`, section `Connections` (endpoints and their keys
live here since spec 018; the old Endpoint form retired, and its card
keeps only the presentation timeout). Save a connection with a base URL
without a scheme (`llm.corp.example/v1`): the refusal names the rule
(it must start with http:// or https://) and saves nothing. Now save a
local (Ollama) connection pointed at the corporate SSO front-door URL
and press its `Test` button: the badge turns to `error` with the
precise cause (it answered with a web page, not an API), and `Delete`
removes it. (The edit form's own `Test connection` button makes the
same free model-list request with the saved key.) A real
OpenAI-compatible endpoint saves with its key in the machine's
keychain, only a masked hint ever shown.

SAY: configuration fails loudly and specifically. No silent saves, no
false greens, the key never rendered back after saving.

IF IT FAILS: every refusal is a named cause on the page; that is the
shipped behaviour, read it out.

## Close (30 seconds)

CLICKS: open `/what-this-touches` (the one-page statement generated
from the audit vocabulary) and mention `/audit/export.csv`.

SAY: everything ran on this machine, every outbound call is in the
audit log, and the whole demo path is a scripted regression:
`python tools/demo_walkthrough.py` runs it headless in a few seconds.
