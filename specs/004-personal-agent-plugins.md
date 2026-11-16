# Spec: personal agent plugins

Audit: `docs/plugins/audit-2026-11-16.md`. This file is the decision. Product code is out of scope for the audit pull request. PR #117 (`cursor/ui-ux-polish-51a3`, draft) owns the desk chrome. This spec uses that chrome and does not redraw it.

## Problem

Agent Desk is one person's desk. The 25 bundled plugins were written as if every desk had the same workbook, the same columns, and the same companies. They share one catalog tile, one sample shell, and, once installed, one dashboard renderer that only draws a metric. Several pairs read the same source and show it twice. Four of them cannot run, because the host never passes a desk-state callback. The samples show numbers the host cannot produce.

The built-in sales card already does the interaction this spec generalizes: a connect action, a named file, and no zero when the file is missing.

## Decision

Ship 18 jobs. Seven of today's ids become instances or sections of a survivor. A job that is "a number from a workbook" is one plugin, the Workbook tracker, installed once and configured many times. Aging, a scorecard, and a two-file reconciliation stay, because their cards are different.

The signed manifest declares the job, the source kinds it may use, and the permission ceiling. It does not declare the user's path, columns, target, or threshold. Those live in a host-owned config, written only after the user confirms them.

Two approaches were rejected.

- A settings form on each of the 25 plugins leaves the duplicate jobs in the catalog. Revenue, budget, and the sales delta would still be three plugins that sum a column.
- One workbook plugin and nothing else deletes interactions that are not a sum: buckets, a multi-row scorecard, a two-file diff, an agenda, a mail digest, a policy checklist.

## The consolidated set

Each line is one job. Two of them must not do the same thing.

| Id | Name | Job | Pattern | Absorbs |
|---|---|---|---|---|
| `excel-report` | Workbook tracker | One series from a workbook the user opens: the current value, how it moved, and an optional goal | Tracker | `sales-delta-widget`, `revenue-vs-target`, `budget-burn` |
| `ar-aging` | Aging | Balances bucketed by age | Scorecard (buckets) | — |
| `kpi-scorecard` | Scorecard | Each metric against its own target | Scorecard | — |
| `reconciliation-watch` | Reconciliation | Keys in one file and not the other | Compare | — |
| `renewal-radar` | Deadlines | Rows whose date falls in a window the user sets | Digest (dated list) | `follow-up-watch` |
| `notes-actions` | Notes | Open checkboxes under a heading the user picks | Checklist | — |
| `calendar-today` | Today | Today's agenda from the connected calendar | Agenda | — |
| `meeting-prep` | Meeting prep | A briefing for the next event | Briefing | — |
| `week-load` | Week load | Hours and the daily load for the coming days | Tracker (sparkline) | — |
| `outlook-digest` | Mail digest | How much mail arrived, and who sent it | Digest | `vip-watch` |
| `waiting-on-you` | Waiting on you | Inbound threads older than a threshold the user sets | Watcher | — |
| `research-brief` | Research brief | The latest stored answer and the sources it named | Briefing | `source-ledger` |
| `competitor-watch` | Page watch | Whether a page the user named has changed | Watcher | — |
| `audit-digest` | Audit digest | What the desk recorded | Watcher | — |
| `compliance-posture` | Compliance | The policy checks and the mode | Status | — |
| `plugin-health` | Plugin health | What is failing, and which installed plugins have a newer release | Status | `update-radar` |
| `morning-brief` | Morning brief | A short document for this morning, from the instances the user pins | Briefing | — |
| `weekly-review` | Weekly review | The same kind of document for the week | Briefing | — |

`excel-report` keeps its id so an existing install updates in place. Its catalog copy stops calling it a reference example. The Class D fixture for authors moves to `registry/examples/class-d/` and is not a catalog entry. See the migration section.

Instances: the Workbook tracker and Deadlines can be configured more than once on the same desk (a revenue instance and a budget instance; a renewals instance and a promises instance). Every other plugin has one config. The instance has a name the user types, a config, and its own card. The plugin id does not change.

## Configuration model

### What is stored

The host writes config. Plugin code does not. The file is `${pluginData}/instances/<instanceId>/config.json` for the host's plugin data directory. The manifest does not gain a write glob for this. A plugin that already writes snapshots (`${pluginData}` for the tracker) keeps that write for snapshots only.

```json
{
  "schemaVersion": 1,
  "instanceId": "revenue",
  "name": "Revenue",
  "source": {
    "kind": "workbook",
    "path": "C:/Users/me/OneDrive/finance/q4.xlsx",
    "sheet": "Booked",
    "range": "A1:F80",
    "headerRow": 1
  },
  "tracking": {
    "labelColumn": "Region",
    "valueColumn": "Booked",
    "dateColumn": null,
    "aggregate": "sum",
    "goal": { "value": 1000000, "unit": "USD", "good": "up" }
  },
  "confirmedAt": "2026-11-16T21:40:00",
  "suggested": false
}
```

`suggested` is true only when the user confirmed an AI proposal. The proposal itself is not kept as a second source of truth. The confirmed config is the source of truth.

Source kinds, and which plugins may use them:

| Kind | Picker | Plugins |
|---|---|---|
| `workbook` | The desk's existing workbook picker (the one the sales card uses). xlsx, xlsm, csv. | Tracker, Aging, Scorecard, Reconciliation (two), Deadlines |
| `markdown` | The same picker, restricted to `.md`. | Notes. Meeting prep, only after a second consent. |
| `calendar` | The calendar walkthrough. One calendar file for the desk, not a path inside the plugin. | Today, Meeting prep, Week load |
| `mailbox` | The mail folder control in Settings. One folder for the desk. | Mail digest, Waiting on you |
| `research` | No path. The card reads the local research store. | Research brief |
| `page` | A URL field. The host is extracted and shown before consent. | Page watch |
| `desk` | No path. Selectors `audit`, `policy`, `runtime`. | Audit, Compliance, Plugin health |
| `compose` | A list of instance ids the user checks. | Morning brief, Weekly review |

A plugin manifest names the kinds it accepts. The runtime rejects a config whose kind is not in that list.

### Pickers

Workbook, csv, and markdown use one picker. The first screen is the file. The second screen is the sheet (workbooks only), then the header row, then the columns the job needs, then an optional range. The user can select columns by name or by clicking a header in a preview of the first 20 rows. The preview is local. It is not sent anywhere unless the user asks for a suggestion.

Calendar and mailbox do not get a second picker inside the plugin. The card's connect action opens the walkthrough or the Settings folder control that already exists. When that connection is missing, every calendar card and both mail cards show the same empty state those screens already use.

Page watch asks for one `https` URL. The consent sheet names the host and the URL. Saving the URL is the grant.

### AI suggest

A button on the column step: "Suggest what to track". It is optional. The picker works with no endpoint configured, and the button explains that an endpoint is required.

The host calls the desk's existing LLM endpoint, through the same audited path as research. The plugin manifest stays `llm.allow: false`. The validator grows a check that Class D manifests keep it false. A plugin cannot make this call itself.

The request contains:

- the plugin's one-sentence job
- the sheet name
- the header row
- up to five data rows from the chosen range
- the column names

It does not contain the rest of the workbook, other sheets, or the file path. The cap is five rows and 8 KB of text. A larger selection is truncated and the proposal says so.

The reply is a proposed config: which columns, which aggregate, and a goal if the job has one. The user sees the proposal in the same column step, with the columns highlighted. Nothing is written until they confirm. Dismiss writes nothing. A failed call leaves the picker where it was and says the endpoint failed, with no partial config.

Suggestion is unavailable for calendar, mailbox, research, page, and desk sources. Those are not tabular.

### Grants

The signed manifest carries a ceiling, not the path.

- Workbook and markdown plugins declare `permissions.filesystem.read: []` and a new manifest field `config.kinds`. The validator accepts an empty read list when every file source is config-backed. A config-backed source must not also declare a `file` glob. That pairing is `over-permission` in reverse: a baked path and a user path at once.
- At read time the host resolves the configured path and allows it only when all of the following hold: the path is the one stored in the confirmed config, the user confirmed it (the config has `confirmedAt`), and the path is either under the desk workspace or is a single file the consent sheet accepted. A path outside the workspace reopens the existing scope-widening consent sheet. The grant records the absolute path, the time, and the decision. It is a single file, not a directory glob.
- The reader refuses a path that is not the granted file, including a sibling the old glob would have matched. `first_permitted_match` is not used for a configured plugin.
- Page watch keeps today's rule: `permissions.network.allow` is empty, the host sits in `optionalPermissions.network` with a `userPrompt` that includes the URL, and the manifest has no filesystem read. The policy `networkAllowlist` still applies. A host the policy does not allow is not fetched, and the card says the policy blocked it.
- Compare stays local. Reconciliation's two files are two workbook grants. Neither side may be `http-get`.
- Shell stays `"none"`. Render stays `ui-schema`. `template` and `html` stay rejected.
- Snapshots for the tracker stay under `${pluginData}`. That remains the only write.

Changing a configured path to a different file is a new confirmation. Narrowing (a smaller range on the same file) does not re-prompt. Widening the range on the same file does not re-prompt, because the grant is the file. Pointing at a new file does.

### Empty config

No config means the card renders its empty state and binds nothing. It does not fall back to a sample, a zero, or a glob. `render_sample` remains the marketplace preview and keeps the "Sample data" chip. An installed card never calls it.

## Card patterns

PR #117 sets the chrome: stone paper, a 2px black rule on the card, Source Serif 4 for titles and briefing prose, Source Sans 3 for UI text, IBM Plex Mono for figures, fir for a number that went up, oxide for the action and for a number that went down, no gradient, no glass, no second accent. This spec does not change the shell, the word rail, or the type scale (12, 14, 16, 20, 32, 56, 64). Patterns are the inside of the card.

The dashboard renderer must draw the pattern. Today's `PluginCardView`, which turns every non-metric into a note, is replaced for plugin cards by the same element renderers the marketplace sample uses, restyled to these patterns. The marketplace sample uses the same renderers, so a preview that lies about a table cannot ship. Array table rows render as cells. The current sample reads `row.primary` and draws an empty body for A/R Aging, Audit digest, and Source Ledger.

Manifest `size` is honored: a tracker and a briefing span 8 columns, a digest and a status card span 4, a compare and a scorecard span 8. Below the desktop breakpoint every card is one column, matching the shell's existing collapse.

| Pattern | What the card shows | Plugins |
|---|---|---|
| Tracker | One mono figure. A sparkline of 12 to 30 points. The delta in fir or oxide, in the tracked unit. The file name in the footer. An optional goal as a thin bar under the figure. | Workbook tracker, Week load |
| Digest | A ranked or dated list, at most 8 rows. A small mono count, not a hero figure. | Mail digest, Deadlines |
| Agenda | Times down the left, titles to the right. The next event is the first row, not a separate metric. | Today |
| Briefing | Serif prose, a few sentences, then the supporting list (sources, or the instances that were cited). No metric grid. | Research brief, Meeting prep, Morning brief, Weekly review |
| Watcher | A timeline: time, what happened, a one-word outcome. Oxide only on a row that needs the user. | Page watch, Waiting on you, Audit digest |
| Scorecard | A table. A row that missed its target is oxide. Aging uses the same table, one row per bucket, plus the oldest balances under it. | Scorecard, Aging |
| Compare | Two labels (the file names the user gave). The figure is the unmatched count. The list is unmatched keys only. | Reconciliation |
| Checklist | The open items. Done items are struck and follow the open ones. The next due date is a line, not a second card. | Notes |
| Status | One status sentence and the list that explains it. Health has two lists, failures and updates. | Plugin health, Compliance |

Color is fir, oxide, or the ink. A status tone maps to those: ok is ink, attention is oxide, alarm is oxide plus the status sentence. No third hue, and no filled icon well behind the plug glyph. Discover tiles use the manifest icon at 16px, in ink, with no shared green chip behind it. The tile shows the summary. That requires the catalog pin to carry `icon` and `summary`, or to stop replacing the manifest.

## First run and empty states

The empty state is the card. It names the one action and does not show a number. Copy is the voice of the built-in cards ("Connect a workbook").

| Plugin | Empty state | Action |
|---|---|---|
| Workbook tracker | "No workbook is connected, so there is nothing to track." | Open a workbook |
| Aging | "No receivables workbook is connected." | Open a workbook |
| Scorecard | "No scorecard workbook is connected." | Open a workbook |
| Reconciliation | "Both files are needed. The ledger is missing." The missing side is named. If both are missing, the ledger is named first. | Open the missing file |
| Deadlines | "No deadline file is connected." | Open a workbook or CSV |
| Notes | "No notes file is connected." | Open a markdown file |
| Today | The calendar walkthrough's existing empty cause. | Connect your calendar |
| Meeting prep | The same calendar cause. After the calendar is connected and nothing is upcoming: "Nothing upcoming to prepare." | Connect your calendar |
| Week load | The same calendar cause. | Connect your calendar |
| Mail digest | The mail setting's existing unconfigured cause. | Choose a mail folder |
| Waiting on you | The same mail cause. When the folder is connected and no thread is waiting: "Nothing is waiting on you." That sentence is allowed. It is not a zero. | Choose a mail folder |
| Research brief | "No research answer is stored yet. Ask from the research field." | Focus the research field |
| Page watch | "No page is being watched." | Add a page |
| Audit digest | "No audit events in this window." Allowed, because an empty log is a real state. A missing callback is "Audit state is not available." and is not the empty-log sentence. | None |
| Compliance | "Policy state is not available." until the callback exists. Then the checklist, including an all-clear sentence. | None |
| Plugin health | "Runtime state is not available." until the callback exists. | None |
| Morning brief | "Choose what this brief includes." until at least one instance is pinned. | Choose cards |
| Weekly review | The same, for the week. | Choose cards |

A missing column after a file is connected is not the empty state. The card names the column and offers "Change columns". It does not show zero.

Marketplace samples stay labeled "Sample data" and are generated from a fixture the host can render with the new bindings. A sample that needs a column the host does not read is a bug. Personal names and company names in samples are replaced with generic labels ("Region A", "Invoice 1042") so the preview is obviously a fixture.

## Per-plugin behavior

### Workbook tracker (`excel-report`)

The user opens one workbook, picks a sheet, a label column, and a value column. Aggregate is sum, count, latest, min, or max. Optional date column and window. Optional goal: a number, a unit, and good direction `up` or `down`. The figure is the aggregate in the unit. The sparkline is the stored snapshots, 12 to 30 points, one per successful read, not invented history. The delta is the change in the aggregate since the previous snapshot, in the unit. The footer is the file name and the sheet.

Revenue, budget, and a pipeline delta are three instances. Budget is the instance whose good direction is `down`. The old 250,000 and 1,000,000 literals are not defaults. A new instance has no goal until the user sets one.

The changed-row list from Sales 24h Delta is the optional detail under the sparkline: rows whose key appeared or disappeared since the previous snapshot, capped at 8. It requires the label column. Without one, the list is omitted, not shown empty.

### Aging (`ar-aging`)

Workbook, amount column, date column, and bucket edges. Default edges 30, 60, 90 are a starting suggestion the user can edit before confirm, not a manifest literal. The table is one row per bucket: label, amount, count. The list under it is the oldest eight: the label column, the amount, and the age in days. The figure is the sum of the amount column.

### Scorecard (`kpi-scorecard`)

Workbook, a metric-name column, an actual column, and a target column or a target the user types per metric. A row is off target when actual misses target in the direction the user set for that row (default: actual below target is off). The status sentence is "N of M off target" and is computed. There is no hero figure.

### Reconciliation (`reconciliation-watch`)

Two workbook grants, one key column each. The figure is the count of keys that appear on only one side. The list is those keys, marked with the file name they came from, capped at 8. Keys on both sides are omitted. If both files also have an amount column the user selected, a key on both sides with amounts that differ is unmatched and the row shows both amounts. Until the user selects amount columns, amount differences are not inferred.

### Deadlines (`renewal-radar`)

Workbook or CSV. A label column and a date column. The window is a number of days, default 30, confirmed by the user. A row counts when its date is today or later and within the window. Dates in the past are listed only under a separate "Passed" group, collapsed, and are not in the count. The list is label, date, and days remaining.

A promises file is a second instance. The old follow-up columns are not assumed.

### Notes (`notes-actions`)

One markdown file, or a folder if the user explicitly selects the folder (the grant is then that folder, and the card says how many files were read). The heading is chosen from the headings in the file, defaulting to the first heading that contains "Actions" when one exists, confirmed before save. Checkboxes, open count, next due date from a `due:` marker. The file is not written.

### Today (`calendar-today`)

The day view, as now: no model call, blank with the bridge's cause when the file is missing. The card is the agenda pattern. It does not also show a large event count. The count can sit in the footer as "3 today".

### Meeting prep (`meeting-prep`)

The next event only: title, time, location, and attendee names as a list of names. The host does not write "Confirm with {name}". There is no second copy of today's agenda and no checklist unless the user has consented to a notes file, in which case open checkboxes whose text contains an attendee name are listed under the briefing. That notes grant is the Notes plugin's grant, reused, not a new glob.

### Week load (`week-load`)

`weekHours` for the coming 7 days including today, and `weekPoints` for 14 days, as the bridge already computes. The card is the tracker pattern. Today's event list is removed. The footer says "Next 7 days" so the summary's "next week" is not doing silent work.

### Mail digest (`outlook-digest`)

The header digest, as now: no body, no attachment, no send. The list is senders ranked by count, capped at 8, with the count on the row. The footer states the window and that bodies are not read. An optional filter is a list of substrings the user types. With a filter, the list is the matching senders and the count is the matching messages. Without one, the list is the top senders. `vip-watch` is not a filter that ships pre-filled.

### Waiting on you (`waiting-on-you`)

The follow-up list. The threshold is a number of days on this card, default 2, confirmed on first run rather than hidden in `FOLLOW_UP_DAYS`. The self address is the one the mail watcher was given in Settings. The `employee@example.com` constant is not used once Settings has an address. The figure is the length of the waiting list. The 24-hour message count is not on this card.

### Research brief (`research-brief`)

The stored summary, the answered time, and the source strings. A title is shown only when the store record has one. "Used" is shown only when the store record has a used flag. Otherwise the row is the source string alone. No refetch, no model call on render.

### Page watch (`competitor-watch`)

One URL. The card is a timeline of fetches: time, "changed" or "unchanged", and the HTTP status. A change row can include the first 200 characters of the new body as a disclosure, not a parsed price list. Line-level HTML diff is out of scope. The policy allowlist remains the operator control. The sample is a timeline with "unchanged", not a fictional price change.

### Audit digest (`audit-digest`)

The host passes an audit callback that returns the recent audit events: time, action, plugin id, outcome. The card is a timeline, capped at 8, plus a footer with the window and the total count. The callback reads the desk audit log. It does not read a user file. A missing callback uses the empty-state sentence in the table above, not a sample.

### Compliance (`compliance-posture`)

The host passes a policy callback: the mode sentence, and the checks the policy engine already evaluates, as checklist items. The card does not ship a handwritten checklist. A missing callback uses the empty-state sentence.

### Plugin health (`plugin-health`)

The host passes a runtime callback with two lists: plugins whose last read failed or is stale, and plugins whose installed version is older than the catalog version. The card is the status pattern with both lists. Update radar's seven-day delta is dropped. The status sentence is computed from the two lists.

### Morning brief and Weekly review

Each stores the instance ids the user checked. The briefing is assembled locally from those cards' latest payloads: the next event, the waiting count, the tracker delta, deadlines inside the window, week-load hours, health's failure count. The prose is a template over those values, not a model call. A model call would put the user's numbers on the endpoint for a card that can be read without one. If a member is missing or blank, that sentence is omitted. The card is blank only when every member is blank, and then it names the first missing connection.

Morning brief's template is the day: next event, waiting threads, tracker movement since yesterday. Weekly review's template is the week: tracker movement across the stored snapshots, deadlines that passed, week-load hours, health failures. They do not mention plugin ids.

## Security

Consistent with the validator as it stands, plus the grant rules above.

- Class D only. No shell, no plugin HTML, no plugin-supplied script.
- Network stays out of `permissions.network.allow`. Page watch is the only bundled plugin with `optionalPermissions.network`, and the prompt names the URL the user entered.
- `http-get` and filesystem read remain mutually exclusive.
- Compare remains local.
- The LLM suggestion is a host call, audited with the existing outbound-call record. The payload cap is part of the audit (row count and byte count). The plugin does not receive the endpoint, the key, or the ability to set `llm.allow`.
- Config and grants are host files under the plugin data directory. Uninstall keeps the data directory, as today. Purge deletes it, including config and grants, after the existing typed confirmation.
- A configured read is logged in the desk audit as a file read with the plugin id and the file name, not the workbook contents. Page watch logs the host, not the body.
- Mail cards do not gain a body field. Calendar cards do not gain a breakdown call. Research brief does not gain an endpoint call on render.
- Samples contain no user data and are not readable as a live source.

## Migration

One release. Old ids keep resolving so an installed copy does not disappear on update.

| Old id | On update |
|---|---|
| `excel-report` | Becomes the tracker. Existing installs have no columns, so the first launch opens the picker instead of reading `reports/*.xlsx`. The old snapshot store is left in place and is not read as the new sparkline. |
| `sales-delta-widget` | Catalog flag `deprecated`. Install and update redirect to a tracker instance named "Sales". The id remains resolvable for one release, then the pack entries drop it. |
| `revenue-vs-target` | Same, instance name "Revenue". The 1,000,000 target is not copied. |
| `budget-burn` | Same, instance name "Budget", good direction `down`. The 250,000 cap is not copied. |
| `follow-up-watch` | Redirects to a Deadlines instance named "Promises". |
| `vip-watch` | Redirects to Mail digest. A VIP list is not invented. |
| `source-ledger` | Redirects to Research brief. |
| `update-radar` | Redirects to Plugin health. |
| The other ids | Stay. First launch with no config opens the picker or the existing connect screen. The old glob is not used as a silent default. |

Packs are rewritten to the survivors.

- Manager: Today, Week load, Meeting prep, Deadlines, Workbook tracker, Mail digest, Research brief, Morning brief.
- CFO: Workbook tracker, Aging, Scorecard, Reconciliation, Deadlines, Audit digest, Weekly review. The pack installs one tracker. The user adds a second instance from the card. The pack does not install three copies.
- Ops: Deadlines, Waiting on you, Notes, Plugin health, Compliance, Weekly review.

Competitor Watch stays out of every pack.

Skills: `workbook-report` and `sales-summary` become one tracker skill that reads the confirmed config's label and value, and still quotes at most two rows. `day-briefing`, `mail-overview`, and `research-recap` stay on their survivors and stop naming a glob. Deprecated plugins do not keep a skill.

The committed `bundled-catalog.json` pin must carry `icon`, `summary`, and the source kind, or `build_bundled_catalog` must merge those fields from the manifest when the pin lacks them. Until that lands, Discover will keep showing the plug glyph and an empty summary. That fix is part of this work, not a follow-up.

Authoring: `docs/design/plugin-authoring-v2.md` gains the `config.kinds` field and the rule that a personal plugin does not hard-code a user path. The reference fixture lives at `registry/examples/class-d/` and is not inserted into `registry/index.json`.

## Testing

- A tracker with no config renders the empty state and reads no file.
- A confirmed workbook path is read. A sibling that the old glob would have matched is not read.
- A path outside the workspace is refused until the consent sheet is accepted, and is then read.
- Suggest sends at most five rows and 8 KB, writes nothing on dismiss, and writes the confirmed columns on accept. With no endpoint, the button explains and the picker still saves a hand-chosen config.
- Reconciliation's figure equals the unmatched count, including amount mismatches when amount columns are set.
- Deadlines exclude past dates from the count and include a date 31 days out only when the window is at least 31.
- Meeting prep does not contain the text "Confirm with".
- Morning brief omits a missing member and does not render a plugin id.
- Audit, compliance, and health render their real callbacks. With the callback unset, the copy is the "not available" sentence, not a number from `sample.json`.
- Page watch does not fetch a host the policy allowlist rejects.
- The marketplace sample for a table fixture shows the fixture cells.
- Discover shows each manifest icon and the summary.
- An update from `sales-delta-widget` lands on a tracker instance named "Sales" and opens the picker.
- Class D checks still fail a manifest with shell permission, a mandatory network allow, plugin HTML, or `llm.allow: true`.

## Out of scope

- Editing `frontend/` on the PR #117 branch, or restyling the shell, the rail, or the marketplace chrome beyond the tile contents named above.
- A line-level HTML diff for Page watch.
- Reading mail bodies or sending mail.
- A model-written morning brief.
- Multiple calendars or multiple mailboxes.
- Auto-installing a pack's tracker more than once.

## Open questions

1. Budget as its own plugin. This spec makes it a tracker instance with good direction `down`. If "pace versus plan" needs a burn rate (spent divided by days elapsed) rather than a total against a cap, it should stay a separate plugin. The audit recommends the instance.
2. How many tracker instances are enough. This spec allows more than one. A cap of four instances per plugin would match the old pack size. No cap is specified yet.
3. Page watch and the policy allowlist. A personal desk may want a page the operator has not pre-approved. This spec keeps the allowlist as the block. If the owner should be able to approve a host without an operator, the consent sheet would need to record that, and the default policy would need a personal exception. Not assumed here.
4. Suggest and row contents. Five rows leave the machine through the company endpoint. Headers only would avoid that and would make column choice worse. This spec sends five rows, capped, and only when the user presses the button.
5. Meeting prep and notes. This spec reuses the Notes grant and matches attendee names. A broader read of the notes file is a wider grant and is not included.
6. PR #117 is still a draft. Patterns here assume its tokens land. If that pull request changes the type scale or the rule weight before merge, the patterns follow the merged tokens. The jobs and the config model do not depend on it.
