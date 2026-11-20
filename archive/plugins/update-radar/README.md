# Update radar

**Question:** which installed plugins have a newer release waiting?

## What it reads

One `desk-state` source with selector `runtime`. The host runtime
callback supplies the rows and the pending count; this card reads no
registry index of its own.

| Slot | Binding | Shows |
|---|---|---|
| list | `updateRows` (`primary`, `secondary`, `meta`) | one row per plugin with an update |
| delta | `value`, direction from `direction` | pending count and its seven-day direction |

The meta column carries the version gap in full (`0.2.0 -> 0.3.0`), so
it is the widest text in the row and needs no tooltip to read.

## What it never does

- downloads, installs, or schedules an update (view only)
- reads the registry index, a lockfile, or the network
- writes nothing, including under `${pluginData}`

## Sample

`sample.json` is a three-release desk: two plugins behind, one current.

## Files

`manifest.json`, `widget.ui.json`, `sample.json`, `README.md`.
