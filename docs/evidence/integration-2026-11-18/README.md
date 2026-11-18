# Integration evidence: land the last two days (spec 011, 2026-11-18)

Proof that the last two days' merged work is actually coupled into the desk
a user runs, and what the gaps looked like before the repair.

## Before (head = `1ecf0f5`, main on the morning of 2026-11-18)

- `before-dashboard-stale-bundle.png`: the dashboard with sample data on.
  The coupled-intelligence wave (#146) is absent: no reading lines, no press
  buttons. The committed SPA bundle predated the merge; CI's committed-bundle
  check was red on main.
- `before-dashboard-sample-data-no-press.png`: same state, wider crop.

## After (branch `fix/spec-011-land-the-last-two-days`)

- `after-dashboard-press-coupled.png`: the same desk after the bundle rebuild
  (#160), the card-shape fix (#165) and the SPA thread fix (#166), with the
  Outlook Brief plugin installed from the marketplace and reading the seeded
  sample mail folder. The card carries its press.
- `after-press-flow-honest-answer.png`: "Draft a reply" pressed. The body
  carried the nested thread, the route resolved it, and the desk answered
  with its honest model-off sentence plus the full disclosure of what the
  press sends. No LLM endpoint is configured on this desk, and none was
  invented: the refusal is the product's own behaviour for that state and
  proves the wiring end to end.
- `marketplace-outlook-detail.png`: the plugin detail page with its live
  sample render and permission review (the spec 008 install truth surface).
- `after-marketplace-installed.png`: the installed state after the consent
  sheet.
- `after-memory-page.png`: the memory page (loop capture settings, stored
  knowledge, provenance graph) on the repaired head.
- `after-settings-home.png`: the one Settings home (spec 007) with its
  toggles, including the sample-data switch used to seed this evidence.

## Gate transcripts

`gates.txt` records, from the repaired head: the docstring gate, the SBOM
build (including the `cryptography` component), the license gate, the
third-party notices check, and both test-suite summaries.

## How to reproduce the live state

1. `PYTHONPATH=src python -m agentdesk.server --no-browser --port 8765`
2. Open the start link from stdout, Settings: turn Sample data on, turn the
   Mail digest on.
3. Set `AGENTDESK_MAIL_FOLDER` in `%USERPROFILE%\.agent-desk\config.env` to
   the seeded `sample\sample-mail` folder and restart.
4. Install Outlook Brief from `/marketplace`; press "Draft a reply".
