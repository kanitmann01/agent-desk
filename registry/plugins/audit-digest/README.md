# Audit digest

**Question:** what did plugins do to this machine this week?

## What it reads

One `desk-state` source with selector `audit`. The host audit log
supplies the event count, the rows, and the window note; the card holds
no log of its own.

| Slot | Binding | Shows |
|---|---|---|
| metric | `value` | events recorded in the audit window |
| table | `auditRows` (row arrays) | when, action, plugin, outcome |
| text | `windowNote` | the window the digest covers |

`auditRows` is table-shaped: each row is a four-cell array matching the
declared columns `When`, `Action`, `Plugin`, `Outcome`.

## What it never does

- reads the audit file directly, or any other file
- edits, retries, or deletes an event (view only)
- opens a socket, runs a shell command, or calls a model
- writes nothing, including under `${pluginData}`

## Sample

`sample.json` is a five-row slice of a 148-event week, including two
denied actions.

## Files

`manifest.json`, `widget.ui.json`, `sample.json`, `README.md`.
