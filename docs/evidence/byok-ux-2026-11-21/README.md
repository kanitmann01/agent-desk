# BYOK settings UX evidence pack, 2026-11-21 (spec 019, tickets #255 to #259, #263, pack ticket #260)

The visual proof for the spec 019 pass: every flow the five tickets changed,
re-screenshotted under all three themes (unkey, coforge, momentuum) from the
merged code of those tickets, not mockups. The repo owner's rule applies: a
flow without a screenshot here means that flow was not done. The before-state
for every frame below is the spec 018 pack at
`docs/evidence/byok-2026-11-21/`. Ticket #263 (the provider picker becomes a
dropdown) extends the pack with the 12-* and 13-* frames below and supersedes
the 01-* radio frames.

## The checkout the pack was taken from

Branch `spec018/byok-ux`, worktree
`D:\20-projects\Personal Agents\.worktrees\byok-ux`, HEAD `c9a6d9b`, clean
tree. The five implementation tickets landed as `36a166e` (#255), `b5171b6`
(#256), `da3b614` (#257), `4b868aa` (#258) and `c9a6d9b` (#259). Nothing was
pushed. The #263 frames (12-*, 13-*) were captured in the same worktree at
the dropdown fix commit itself (`fix: the provider picker becomes a dropdown
(spec 019 #263)`, this commit), so they show the working tree that commit
records; the 01-11 frames stay pinned to the `c9a6d9b` checkout named above.

## How the walkthrough ran

- Two throwaway desks under the system temp run directory
  (`byok-ux-evidence-run\desk-a` and `\desk-b`), never the real
  `%USERPROFILE%\.agent-desk`. Both were booted from the worktree source
  (`PYTHONPATH` at the worktree's `src`; the installed site-packages copy is
  stale and was not used): `python -m agentdesk.server --port N
  --no-browser`, `AGENTDESK_DATA` on the throwaway folder, the
  `AGENTDESK_LLM_BASE` / `AGENTDESK_LLM_KEY` / `AGENTDESK_LLM_MODEL`
  overrides emptied, entered through the printed one-time start link. Desk A
  booted fresh; desk B's settings sqlite was seeded before boot with the
  legacy row `llm_base` (a loopback gateway URL) and `llm_model`
  (`demo-mini`) and `llm_key` left EMPTY, so the one-boot migration produced
  an enabled, bound, keyless connection with zero keychain writes. Both
  stderr logs were empty for the whole run.
- Loopback stubs (stdlib `http.server` on 127.0.0.1) played the provider
  with the exact response shapes `tests/server_harness.py` and
  `tests/test_server_keys_health.py` pin: port 5411 answered every GET with
  the 200 model-list envelope (`demo-mini`, `demo-large`), port 5412
  answered 401. The "Never tested" row points at an ordinary loopback
  address that was never pressed, so its stored status is the truthful
  unknown.
- Keys: three of the four connections were saved keyless (local presets,
  empty key fields). The one key typed during the whole walkthrough was the
  clearly fake demo value `sk-demo-byok-ux-2026-0001`, saved once for the
  remove-the-key story and once more for the hygiene proof below; both
  times the app's own Remove the stored key action deleted it. No
  screenshot shows an input holding a raw value: every key field in every
  frame is empty (placeholder or masked hint only), and the filled moments
  were fill-and-submit, never photographed.
- Themes: `agentdesk.theme` in the browser's localStorage (the same key the
  Appearance tiles write), page reloaded per theme. The JS-off frame runs
  the default unkey theme.
- Screenshots: playwright-cli, Chromium, 1440x900 viewport frames. File
  names are kebab, numbered by flow group, theme in the name.
- The #263 pass (frames 12-* and 13-*) ran the same way, one throwaway desk
  under the system temp run directory (`byok-ux-263-run\desk-a`), booted
  from the worktree source (`PYTHONPATH` at the worktree's `src`), the
  `AGENTDESK_LLM_*` overrides emptied, entered through the printed one-time
  start link, boot stderr 0 bytes. No key was typed at all: the one
  connection the frames show was saved keyless on the Ollama local preset
  (the select's own form post, base URL left to the preset default), so the
  keychain wrote nothing (enumerated: 0 agent-desk entries before and
  after; `cmdkey /list` agreed). The open-select frame shows the native
  dropdown of the real page; in that headless capture the popup surface
  draws with the system light scheme even under the dark themes, though the
  page declares `color-scheme` per theme: the popup is the browser's own
  control, exactly what the ticket mandates. The popup is shown scrolled to
  its last option (Custom), because the native popup's own viewport clips
  the fifteen rows; the closed frames and the markup suite pin the full
  order.

## The captured gate

`ci-local.txt`: the complete output of `python tools/ci_local.py` at this
HEAD (launched detached with stdout and stderr on explicit Windows temp
paths, polled with foreground reads). The stderr capture is 0 bytes: no
tracebacks. The seven legs pass in order (py-grammar 379 files, pytest,
frontend-check tsc clean, frontend-tests 313 vitest, licenses, registry-ci,
brand-leak), the pytest leg reading `2810 passed, 1 skipped, 13 warnings in
580.07s`. It ends:

    7/7 gates passed in 594s
    CI PASS

## Frames, flow by flow

| File | Flow | Ticket and story | Theme |
| --- | --- | --- | --- |
| `01-create-form-preset-radios-unkey.png` | fresh Settings, the add form | #255: the twelve preset radios render as circles, one checked (OpenAI, accent dot and tile border) and eleven unchecked; show-key and make-default sit as small squares; key field empty. SUPERSEDED by #263: the radio grid is gone, the select frames 12-* are the add-form proof now; the #255 control-fix proof (circles and checks drawn right) rests on the checkbox frames 02/03, which remain valid | unkey |
| `01-create-form-preset-radios-coforge.png` | same | #255 under the navy/coral theme. SUPERSEDED by #263, as above | coforge |
| `01-create-form-preset-radios-momentuum.png` | same | #255 under the light brand-blue theme. SUPERSEDED by #263, as above | momentuum |
| `02-create-form-checkboxes-ticked-unkey.png` | create form, controls ticked | #255: show-key and make-default ticked with visible checks, the checked radio moved to vLLM (no key), key field empty. This frame is connection "Loopback gateway" as it was actually saved | unkey |
| `02-create-form-checkboxes-ticked-coforge.png` | same form state | #255 under coforge (staged on the live add form, not saved) | coforge |
| `02-create-form-checkboxes-ticked-momentuum.png` | same form state | #255 under momentuum (staged on the live add form, not saved) | momentuum |
| `03-edit-form-remove-key-ticked-unkey.png` | edit form, the clear action | #255: Remove the stored key ticked with a visible check, key field empty, its placeholder the masked hint `sk-...0001` of the stored demo key, the OpenRouter radio checked | unkey |
| `03-edit-form-remove-key-ticked-coforge.png` | same | #255 under coforge (re-opened after the key was gone; placeholder reads not set) | coforge |
| `03-edit-form-remove-key-ticked-momentuum.png` | same | #255 under momentuum | momentuum |
| `03-row-after-remove-key-unkey.png` | after saving the clear | #255 with the spec 018 rule intact: the row's Key cell reads no key, the keychain entry deleted by the app | unkey |
| `04-console-disclosure-closed-unkey.png` | the Connections card's last block | #259: the hosted-preset links folded into a closed native disclosure, plain-language summary "Where to get a key" | unkey |
| `04-console-disclosure-closed-coforge.png` | same | #259 under coforge | coforge |
| `04-console-disclosure-closed-momentuum.png` | same | #259 under momentuum | momentuum |
| `04-console-disclosure-open-unkey.png` | the disclosure opened | #259: opened by a plain click, the hosted-preset anchors visible (OpenAI through Mistral) | unkey |
| `04-console-disclosure-open-coforge.png` | same | #259 under coforge | coforge |
| `04-console-disclosure-open-momentuum.png` | same | #259 under momentuum | momentuum |
| `05-connections-table-three-states-unkey.png` | the saved-connections table | #256 and #257: four compact rows in one screenful, Test, Edit and Delete on one line per row, the long gateway-shaped base URL wrapped inside its column, and the three badge states side by side, separated by color as well as word: ok (yellow-green), error (red, with the inline 401 cause), unknown (quiet ink) | unkey |
| `05-connections-table-three-states-coforge.png` | same | #256 and #257 under coforge (ok coral, error red, unknown gray) | coforge |
| `05-connections-table-three-states-momentuum.png` | same | #256 and #257 under momentuum (ok brand blue, error dark red, unknown gray) | momentuum |
| `06-jobs-card-bound-hint-unkey.png` | the Jobs card | #259 with the spec 018 binding intact: every per-picker label reads Model, the cached-lists-or-typed hint appears exactly once (card intro), the assistant job bound to Loopback gateway with `demo-mini`, picker preselected, readback agrees ("Serves through Loopback gateway, model demo-mini."), stamp 1 BOUND | unkey |
| `06-jobs-card-bound-hint-coforge.png` | same | #259 under coforge | coforge |
| `06-jobs-card-bound-hint-momentuum.png` | same | #259 under momentuum | momentuum |
| `07-delete-warning-bound-unkey.png` | the delete warning, regular variant | #258: whole sentences naming the bound job ("Loopback gateway is bound to the assistant job"), the confirm styled destructive (btn-danger), Keep it as the secondary exit | unkey |
| `07-delete-warning-bound-coforge.png` | same | #258 under coforge | coforge |
| `07-delete-warning-bound-momentuum.png` | same | #258 under momentuum | momentuum |
| `08-connections-js-off-disclosure-open-unkey.png` | the no-JS proof | #259: a Chromium context with JavaScript disabled, the disclosure opened by a plain click, anchors visible, the page fully server-rendered | unkey |
| `09-migrated-connections-unkey.png` | desk B after the migration | spec 018 #234 with #256 and #257 rendering: the legacy rows with EMPTY key values became Migrated endpoint, enabled, bound, Custom preset, Key cell "no key", legacy URL verbatim, default star, zero keychain writes | unkey |
| `09-migrated-connections-coforge.png` | same | under coforge | coforge |
| `09-migrated-connections-momentuum.png` | same | under momentuum | momentuum |
| `10-migrated-jobs-unkey.png` | desk B's Jobs card | the migration bound the default job to the migrated connection with the legacy model: picker preselected to Migrated endpoint, readback "Serves through Migrated endpoint, model demo-mini." | unkey |
| `10-migrated-jobs-coforge.png` | same | under coforge | coforge |
| `10-migrated-jobs-momentuum.png` | same | under momentuum | momentuum |
| `11-delete-warning-migrated-unkey.png` | the delete warning, migrated variant | #258: the recovery paragraph in whole sentences (the key stays in the keychain, the next start puts the connection back), destructive confirm, Keep it secondary | unkey |
| `11-delete-warning-migrated-coforge.png` | same | #258 under coforge | coforge |
| `11-delete-warning-migrated-momentuum.png` | same | #258 under momentuum | momentuum |
| `12-create-form-provider-select-unkey.png` | fresh Settings, the add form | #263: the twelve presets plus Custom render as one native select under a Provider label, OpenAI selected (the first preset, where the checked radio used to sit), the disclosure still the card's last block; no radio remains | unkey |
| `12-create-form-provider-select-coforge.png` | same | #263 under coforge | coforge |
| `12-create-form-provider-select-momentuum.png` | same | #263 under momentuum | momentuum |
| `12-create-form-provider-select-open-unkey.png` | the select opened | #263: the real dropdown open, the optgroups readable: Hosted providers (names only), Local servers, no key needed (Ollama, LM Studio, vLLM each labeled this machine, no key needed), and the Custom group last, highlight on it (the popup is scrolled to its last option; see the walkthrough note above) | unkey |
| `13-edit-form-provider-selected-unkey.png` | the edit form | #263: the saved connection's provider option carries selected, the select reads Ollama (this machine, no key needed), label and base URL prefilled, key field empty with placeholder not set (keyless save, no keychain write), the row above reading no key | unkey |
| `13-edit-form-provider-selected-coforge.png` | same | #263 under coforge | coforge |
| `13-edit-form-provider-selected-momentuum.png` | same | #263 under momentuum | momentuum |

One naming note: the 02 frames for coforge and momentuum stage the same
live add-form state (radio moved, both checkboxes ticked) rather than
re-saving a connection, because the connection they mirror was already
saved under unkey; the form, its controls and its state are the real page.
The 12/13 frames for coforge and momentuum reload the same pages under the
theme's localStorage key; the connection they show is the one keyless save
described above.

## The other consumers of the changed --bad token

The `--bad` token's reachable consumers on a local desk, and what became of
each:

- `.btn-danger` (the delete warning confirm): reachable and photographed,
  both variants, all three themes (frames `07-...` and `11-...` above).
- `.delta.down` in its `--bad` color: not photographed, and honestly so.
  That rule lives in the server pages stylesheet and renders only on the
  server-rendered dashboard, which this checkout never serves: the
  committed SPA build exists, so GET / serves the SPA, and the SPA's sales
  card draws its delta chips with each theme's own accent tokens, not
  `--bad`. Photographing the `--bad` variant would require deleting the
  committed build, that is, altering the checkout the pack must certify.
- `table.rows td.neg` (a negative table cell): the rule exists, but no
  server template emits a `neg` cell anywhere in this tree today; there is
  nothing truthful to photograph, so none was faked.

## Keychain cleanup (the walkthrough's traces are gone)

The walkthrough used the real OS keychain on purpose (the feature under
test). Entries, service `agent-desk`, username `key/<connection id>`:

- Baseline before the walkthrough: enumeration over every credential on the
  machine (`CredEnumerateW` with a NULL filter, filtered in Python for
  `agent-desk` targets and `key/` users, cross-checked with
  `cmdkey /list`): **0 agent-desk entries**.
- The desk itself wrote exactly one entry during the walkthrough, when the
  demo key `sk-demo-byok-ux-2026-0001` was saved on the OpenRouter
  connection. It was enumerated while present (1 entry, target
  `agent-desk`, user `key/fb97f4c9...`; `cmdkey /list` agreed:
  `LegacyGeneric:target=agent-desk`) and then deleted by the app's own
  Remove the stored key action (that is what frame
  `03-row-after-remove-key-unkey.png` shows). An earlier save of the same
  demo value had been removed the same way before that enumeration.
- After the remove, and again after both desks were shut down, the full
  enumeration re-ran across every credential (same NULL-filter method) plus
  `cmdkey /list`: **0 agent-desk entries remain**.
- The migration desk wrote zero keychain entries by construction: the
  legacy key rows were seeded EMPTY. The other three connections were
  keyless local presets. The throwaway data folders, the stub scripts, the
  boot logs and the browser sessions were deleted with the temp run
  directory at the end.

## Artifacts not in this folder

The walkthrough's boot/stub/enumeration scripts, desk logs and cookies
lived in the temp run directory and were deleted with it; this folder holds
the durable evidence only.
