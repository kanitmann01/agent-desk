# Compliance posture

**Question:** are the installed plugins inside the desk policy?

## What it reads

One `desk-state` source with selector `policy`. The host policy state
supplies the status line, the checklist, and the active policy mode.

| Slot | Binding | Shows |
|---|---|---|
| status | `status`, `tone` | the overall posture in one line and its tone |
| checklist | `postureItems` (`text`, `done`, `due`) | each check with its due date |
| text | `policyMode` | advisory or enforcing, in the host's words |

## What it never does

- changes policy, grants a permission, or disables a check (view only)
- reads the policy file directly, or any other file
- opens a socket, runs a shell command, or calls a model
- writes nothing, including under `${pluginData}`

## Sample

`sample.json` is a six-check posture with three open items.

## Files

`manifest.json`, `widget.ui.json`, `sample.json`, `README.md`.
