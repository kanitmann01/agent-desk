# Evidence: the demo-ready desk (spec 022), 2026-11-23

All artifacts on the branch tip at capture time (commit `be6e9e9`), on this
machine, with no real key spent and no real folder touched: every desk below
was booted on a temporary data folder with a file-backed stand-in keychain and
the local mock model endpoint, exactly the way `tools/demo_readiness.py` boots
its own desks.

## The machine walk

`readiness-output.txt` is the unedited output of
`python tools/demo_readiness.py` on the tip: 23 of 23 checks PASS, ending
`METRIC ready=23`, exit 0. The walk boots the real app twice over one fresh
folder (the second boot proves the key survives a restart), walks the first
ten minutes over HTTP as a browser would, and leaves nothing behind.

## The gate

`gate-transcript.txt` is the full local gate (`python tools/ci_local.py`) on
the same tip. Every gate line names its own numbers; the summary line is the
verdict. (Added after the gate run finished; see the file for the commit it
ran on.)

## The screens

Twelve screenshots at exactly 1264x805, retaken on the tip the same evening
(one desk per row of the table, each desk killed after its shots; the browser
context was closed between desks so no cookies crossed):

| File | What it shows |
| --- | --- |
| 01-home-fresh.png | A fresh desk: the Get started strip above the tiles, 0 of 3 done, "Try it with sample data" offered |
| 02-home-sample.png | The sample set on: every tile labelled, the strip offers "Hide sample data", still 0 of 3 |
| 03-settings-ai-fresh.png | Settings opens on Your AI: the key form first, no on/off switch above the fold |
| 04-home-ai-saved.png | After the key is saved: 1 of 3 done, the sample offer still present (a saved AI is not a source) |
| 05-settings-ai-saved.png | Your AI with a saved row: label, provider, model `mock-chat`, state, Test, Edit, Remove |
| 06-settings-tools.png | Your tools: workbook, calendar, mail, each with its state and one action |
| 07-settings-preferences.png | Preferences: the six personal preferences, then the three themes |
| 08-settings-advanced.png | Advanced: "The defaults are right for most people." first |
| 09-plugins.png | Plugins: Find plugins and Installed, "Describe a plugin in plain English" |
| 10-memory-explained.png | Memory: "How memory works" in plain words, the taught fact with its origin (Assistant) |
| 11-memory-forget-confirm.png | The confirm: "Forget every fact? ... It cannot be undone.", Keep my facts quiet, the destructive action red |
| 12-memory-empty.png | After the confirm: the page empty, the action recorded in the audit trail |

## How the desks were booted

`diag/evidence_desk.py` in the session scratch (a copy of the readiness
walk's boot: temporary folder, `FileKeychain` stand-in, mock endpoint on an
ephemeral port), with `--sample`, `--with-ai`, or `--with-ai --teach` per
desk. The mock's words are canned; the plumbing they ride is the product's.

## Not verified here

A real AI provider (no key was available; every model call went to the local
mock); the workbook file dialog and the calendar upload clicked in a browser
(both are proven over HTTP by the walk, R22 and R23); the founder's real
instance (its own checklist lives in `DEMO.md`, "The day before").
