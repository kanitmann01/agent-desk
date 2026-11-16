# Authoring the in-box plugins (manifest v2)

Every in-box plugin is declarative: a manifest, a `widget.ui.json`, a
packaged `sample.json`, a README, and the existing `skills/` folder when
the plugin already had one. No JavaScript, no HTML, no shell, no network
except the one reference network plugin. The host renders the schema and
supplies the data.

## Files per plugin

```
registry/plugins/<id>/
  manifest.json      schemaVersion 2, metadata required
  widget.ui.json     {"type": "card", "elements": [...]}
  sample.json        {"bindings": {...}, "state": "ok", "checkedAt": "2026-11-15T09:00:00"}
  README.md          what question it answers, what it reads, what it never does
  skills/...         only for the five existing ids (the four upgraded
                     plugins plus excel-report); keep untouched
```

## Manifest template

```json
{
  "schemaVersion": 2,
  "id": "revenue-vs-target",
  "name": "Revenue vs target",
  "version": "0.1.0",
  "publisher": "agent-desk",
  "class": "declarative",
  "engines": {"dashboardHost": ">=0.1.0 <2.0.0"},
  "license": "MIT",
  "category": "finance",
  "tags": ["revenue", "target"],
  "icon": "chart",
  "summary": "Are we ahead or behind the quarter?",
  "description": "Reads the revenue workbook you point it at and compares booked revenue with the quarter target. Two numbers, their gap, and the fill that shows the gap at a glance.",
  "highlights": [
    "Booked revenue and the quarter target side by side",
    "The gap in currency and as a percentage",
    "Shows the workbook path it read and when"
  ],
  "permissions": {
    "filesystem": {"read": ["${workspace}/finance/*.xlsx"], "write": []},
    "network": {"allow": []},
    "llm": {"allow": false},
    "shell": "none"
  },
  "activationEvents": ["onWidget:revenue-vs-target", "onSchedule:0 7 * * *"],
  "contributes": {
    "widgets": [{
      "id": "revenue-vs-target",
      "size": "2x1",
      "dataSource": {"type": "excel-watch", "file": "${workspace}/finance/*.xlsx",
                     "keyColumn": "Region", "valueColumn": "Booked",
                     "window": "90d", "aggregate": "sum"},
      "render": {"type": "ui-schema", "file": "widget.ui.json"}
    }]
  },
  "sample": "sample.json",
  "minHost": ">=0.1.0"
}
```

Rules:
- `category` one of finance, time, communication, research, operations, command, reference.
- `icon` one of calendar, chart, mail, book, checklist, clock, alert, folder, plugin, generic.
- exactly three `highlights`, each <= 120 chars; `summary` <= 120; `tags` lowercase slugs, <= 8; `description` <= 4000.
- permissions are minimal: read only the glob the source needs, write only `${pluginData}` when the source stores snapshots, network only for the network plugin.
- existing ids keep their id and `skills` block; bump version to 0.2.0 for the four upgraded plugins.

## Element slots (exact)

| kind | fields | binding |
|---|---|---|
| metric | label | `binding` |
| text | label, text (literal) or binding | `binding` |
| delta | label, window, directionBinding | `binding` + `directionBinding` |
| progress | label, unit, target (number) or targetBinding, tone, toneBinding | `binding` |
| list | title | `rowsBinding` rows `{primary,secondary,meta}` |
| table | title, columns [] | `rowsBinding` rows arrays |
| sparkline | label | `pointsBinding` numbers, 12..30 points |
| status | tone/toneBinding | `binding` text |
| timeline | title | `itemsBinding` items `{time,title,meta}` |
| checklist | title | `itemsBinding` items `{text,done,due}` |

## Binding vocabulary emitted by the host

- excel-watch, csv-watch: value, delta24h, addedCount, removedCount, unchangedCount, rowsSeen, windowNote, file, rows, table
- json-watch: value, count, rows, table, asOf
- markdown-watch: openCount, doneCount, nextDue, items, rows
- manual-metric: value, target, unit, lastUpdated, history, delta
- calendar-read: nextEventTitle, nextEventTime, eventsToday, upcoming, rows
- mail-digest: messages, threads, unread, topSenders, windowNote
- research-brief: summary, sourcesCount, answeredAt, sources, rows
- desk-state: value, rows, status, tone
- compare: left, right, delta, direction, rows
- aggregate: value, contributors, rows
- http-get: value, status, changed, fetchedAt, rows

Use only these names plus `target`-style literals. A missing binding must
render blank through the host, but shipped samples must bind every element
so the marketplace preview is complete.

## sample.json

`{"bindings": { ...same names as the ui slots... }, "state": "ok", "checkedAt": "2026-11-15T09:00:00"}`

Realistic numbers, no lorem ipsum, no placeholders like "N/A". For plugins
whose normal state is missing (a first run), ship the ok sample; the host
shows the blank state at runtime.

## Data source configs

- excel-watch: `{"type":"excel-watch","file":"${workspace}/finance/*.xlsx","keyColumn":"Region","valueColumn":"Booked","window":"30d","aggregate":"sum"}` (window 24h|7d|30d|90d, aggregate sum|count|latest|min|max)
- csv-watch: same shape with a .csv file.
- calendar-read: `{"type":"calendar-read"}`
- mail-digest: `{"type":"mail-digest"}`
- research-brief: `{"type":"research-brief"}`
- json-watch: `{"type":"json-watch","file":"${workspace}/...json","selectors":{"value":"$.totals.booked","rows":"$.deals[*].name"}}` (only `$.a.b` and `$.a[*].n`)
- markdown-watch: `{"type":"markdown-watch","file":"${workspace}/notes/*.md","heading":"Actions"}`
- manual-metric: `{"type":"manual-metric","unit":"USD"}`
- desk-state: `{"type":"desk-state","selector":"runtime"|"audit"|"policy"}`
- compare: `{"type":"compare","left":{...source...},"right":{...source...}}` local sources only
- aggregate: `{"type":"aggregate","over":["plugin-id"],"operation":"sum"}`; manifest also declares `"requires": ["plugin-id"]`
- http-get (only competitor-watch): `{"type":"http-get","url":"https://example.com/pricing","host":"example.com"}` plus `optionalPermissions.network: {"allow":["example.com"],"userPrompt":"..."}`; `permissions.network.allow` must stay empty because the validator rejects a mandatory network grant as over-permission; must have no filesystem read permission.

## Verification each family agent runs

```
python -m pytest -q tests/test_plugins_<family>.py
```

The family test discovers every plugin directory in its family, runs the
real validator over it (see tests/test_registry_hardening.py for the
`validate_plugin` call), and asserts `render_sample` returns status fresh
with no blank element. Also assert each ui-schema element kind is one of
the ten and each sample has a binding for every slot.

Do NOT edit registry/index.json, scripts/, docs/, or another family's
plugin folders. Do NOT commit.
