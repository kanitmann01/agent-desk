# Plugin health

**Question:** which installed plugins are failing or drifting right now?

## What it reads

One `desk-state` source with selector `runtime`, supplied by the host
dashboard. No files are opened here: the runtime callback already holds
the installed-plugin state.

| Slot | Binding | Shows |
|---|---|---|
| status | `status`, `tone` | the whole installed set in one line and its tone |
| list | `healthRows` (`primary`, `secondary`, `meta`) | plugins that need attention, one row each |
| metric | `value` | how many plugins are installed |

`healthRows` rides the desk-state bindings passthrough: the host runtime
callback supplies the rows and `value`; `status` and `tone` are the
standard desk-state fields.

## What it never does

- reads no file, opens no socket, runs no shell command, calls no model
- installs, updates, disables, or uninstalls anything (view only)
- writes nothing, including under `${pluginData}`

## Sample

`sample.json` is the recorded runtime state for a twelve-plugin desk with
three plugins flagged, so the marketplace preview is complete.

## Files

`manifest.json`, `widget.ui.json`, `sample.json`, `README.md`.
