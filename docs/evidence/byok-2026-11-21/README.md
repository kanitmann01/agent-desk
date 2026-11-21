# BYOK evidence pack, 2026-11-21 (spec 018, tickets #231 to #235 and #241)

The proof behind the BYOK close-out: the full local gate green, the
suite green with no OS keychain anywhere, the Nuitka smoke leg with
keyring present, and a browser walkthrough that screenshots every
user-visible flow the spec shipped. The repo owner's rule applies: a
flow without a screenshot here means that flow was not done.

## How the walkthrough ran

- Throwaway data folders under the system temp dir (`%TEMP%\byok-desk-a`,
  `%TEMP%\byok-desk-b`; the merge retake used fresh ones, see below),
  never the user's real `%USERPROFILE%\.agent-desk`. Desk A booted
  fresh; Desk B's settings sqlite was seeded before boot with the
  legacy rows (`llm_base`, `llm_key`, `llm_model`) using the clearly
  fake key value `sk-demo-legacy-migration-0001`, so the one-boot
  migration ran on a real start. Both boots were the real app:
  `python -m agentdesk.server --port <free port> --no-browser` with
  `AGENTDESK_DATA` pointed at the throwaway folder and the
  `AGENTDESK_LLM_BASE` / `AGENTDESK_LLM_KEY` / `AGENTDESK_LLM_MODEL`
  overrides emptied, entered through the printed one-time start link.
- Loopback stub endpoints (stdlib `http.server` on 127.0.0.1 free
  ports) played the provider, the same shapes
  `tests/server_harness.py` and `tests/test_server_keys_health.py`
  pin: one answered `GET /v1/models` 200 with `demo-mini` and
  `demo-large` (and a canned completion for the deeper check), one
  answered 401, and one recorded port was left dead for the transient
  case.
- Every key typed during the walkthrough was a clearly fake demo value
  (`sk-demo-byok-walkthrough-0001`, `sk-demo-bad-9999`; the Dead port
  row was created on the Ollama no-key preset with no key at all). No
  screenshot shows an input holding a value:
  forms were captured before typing and after saves, where only masked
  hints render.
- Screenshots were taken with playwright-cli (Chromium, 1440x900)
  against the running desks.

## The captured gate

- `ci-local.txt`: the complete output of `python tools/ci_local.py` on
  the merged tree (launched detached because the run takes ~600 s).
  The seven leg names are unchanged by the 017 gate rework; the
  licenses leg now phrases its pass as "sbom, license gate and notices
  all clean" (the SBOM chain replaced the legacy manifest this merge
  retired). It ends:

      7/7 gates passed in 603s
      CI PASS

  pytest leg: `2802 passed, 1 skipped` over a fresh temp data dir; the
  frontend legs: `313 passed` vitest, `tsc --noEmit` clean.

- `null-keyring-pytest.txt`: the full pytest suite with
  `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` forced in the
  environment (probe printed `keyring.backends.null.Keyring (priority:
  -1)` before the run), stderr empty, verdict `2802 passed, 1 skipped,
  13 warnings in 595.50s`. CI parity with no OS keychain anywhere:
  connections still save (without secrets), the page names the state,
  tests inject fakes.

## The Nuitka smoke leg

- `nuitka-smoke.md`: the `nuitka-build-smoke` enterprise CI job run
  locally with keyring present (Nuitka 4.3.5 installed exactly as the
  job installs it), step by step with its output: build green (120
  files, unsigned), manifest verify PASS, `/health` smoke PASS, and
  the packaging note on how keyring's runtime backend discovery
  travels (the compiled keyring tree incl. `keyring.backends.Windows`
  is in `build/nuitka-report.xml`; the built exe answers
  `{"keychainAvailable": true}`). No fallback store needed, none made.
- `nuitka-built-exe-connections.png`: the built `AgentDesk.exe`
  serving the Settings Connections card (authenticated through its
  one-time start link): the packaged app renders the new surface with
  the keychain live and no no-keychain notice. The merge retake below
  did not redo this frame: the Connections card's visible content is
  unchanged by the 017 wave and the packaging surface did not change.

## Walkthrough screenshots, flow by flow

| File | Flow | What it proves |
| --- | --- | --- |
| `01-connections-empty-preset-grid.png` | (a) fresh Settings | The Connections card before any connection exists: the honest empty state and the full 12-preset grid (OpenAI through Custom, the local ones marked "no key"). |
| `02-create-form-preset-chosen-before-key.png` | (b) preset-grid create, before the key | The create form with the non-local OpenRouter preset chosen, label and stub base URL filled, captured BEFORE any key was typed (the API key field is empty). |
| `02-connections-list-masked-row.png` | (b) after save | The saved row: masked hint only (`sk-...0001`, first three and last four), the save-time free model-list check already stamped `ok` and cached 2 models. The raw key never renders. |
| `03-edit-form-empty-key.png` | (c) edit, empty-key-keeps | The edit form's key field left empty; its placeholder shows the masked hint, never the value. |
| `03-row-after-edit-same-mask.png` | (c) after save | The same masked hint (`sk-...0001`) after saving the edit with an empty key field: the stored key survived the edit. |
| `04-clear-key-checkbox.png` | (d) the clear action | The edit form with "Remove the stored key" ticked (the only action that deletes the key), key field still empty. |
| `04-row-after-clear-no-key.png` | (d) after save | The row's Key cell now reads `no key`: the clear removed the stored key and its keychain entry. |
| `05-test-badge-ok.png` | (e) Test: ok | The Test button's free model-list request against the loopback stub: badge `ok`, checked stamp, models cached. |
| `05-test-badge-error-401.png` | (e) Test: error | The stub answering 401: badge `error` with the inline cause "the endpoint rejected the API key (HTTP 401); check the key". |
| `05-test-badge-transient-dead-port.png` | (e) Test: transient | A dead port: the badge keeps its stored status (`unknown` on a fresh row, the spec's mapping for transport failures) and the inline cause names it: "the endpoint host refused the connection: nothing is listening at 127.0.0.1:50147". The frame also shows all three badge states side by side. |
| `06-models-cached-row.png` | (f) model cache, page | The Connections card after the checks: the row shows "2 models cached" from the loopback stub. |
| `06-models-refresh-discovered-ids.png` | (f) model refresh, the ids | `GET /api/connections/<id>/models?refresh=1` (the refresh route re-fetches server-side) rendering the discovered ids `demo-mini`, `demo-large` with their fetched-at stamp in the browser. |
| `07-job-binding-serves-through.png` | (g) per-job picker | The assistant job bound to the saved connection with model `demo-mini`; the picker shows the bound connection as the selected option and the readback line agrees: "Serves through OpenRouter personal, model demo-mini." |
| `08-delete-bound-jobs-warning.png` | (h) delete with bound jobs | The no-JS confirmation page a bound connection's first delete answers with: it names the bound job ("OpenRouter personal is bound to the assistant job"), what the delete removes, and the "Keep it" exit. |
| `08-connections-after-delete.png` | (h) after confirm | The list without the deleted connection; the remaining rows (Stub rejects, Dead port) keep their badges. The binding went with the delete (NONE BOUND). |
| `09-migrated-endpoint-connection.png` | (i) migration | Desk B after a real boot over legacy settings rows: the "Migrated endpoint" connection with the Custom preset, its masked hint (`sk-...0001`), the legacy base URL verbatim, and the default star. |
| `09-migrated-default-job-bound.png` | (i) migration bound the job | The default job's readback: "Serves through Migrated endpoint, model demo-mini.", the legacy `llm_model` carried into the binding. |
| `10-theme-unkey-connections.png` | (j) theme: Unkey | The Connections card under the default dark yellow-green theme, three saved connections rendering badges, masked hints and the preset grid. |
| `10-theme-unkey-jobs.png` | (j) theme: Unkey | The Jobs card under Unkey: the assistant picker shows its bound connection, the other pickers show Not bound, the readback agrees. |
| `10-theme-coforge-connections.png` | (j) theme: Coforge | The Connections card under the navy/coral theme. |
| `10-theme-coforge-jobs.png` | (j) theme: Coforge | The Jobs card under Coforge (the corrected picker, `1 BOUND`). |
| `10-theme-momentuum-connections.png` | (j) theme: Momentuum blue | The Connections card under the light brand-blue theme. |
| `10-theme-momentuum-jobs.png` | (j) theme: Momentuum blue | The Jobs card under Momentuum blue (the corrected picker, `1 BOUND`). |

The shipped theme list was taken from the page code:
`src/agentdesk/server/settings_view.py`, `_THEMES` (unkey, coforge,
momentuum); all three render the new Connections and Jobs sections
above.

## The #235 refresh pass (the job picker retake, same day)

The walkthrough's Jobs frames were captured before the #235 fix, where a
bound job's select still displayed "Not bound" (no option carried the
`selected` attribute) while the readback under the form said otherwise.
After the fix (the picker preselects its bound connection), the four
frames whose content changed were retaken so this pack shows the final
state. The merge retake below re-captured those frames again with the
final wording.

## The merge retake (2026-11-21, after merging the 017 wave)

origin/main moved 28 commits past this branch's base: the spec 017
remediation wave, including "every surface says Agent Desk" (#228),
which renamed the product chrome on every page this pack screenshots
(the sidebar brand, breadcrumbs, page titles and footers all said the
retired working name in the old frames). Every frame whose visible
content the merge touched was therefore re-captured against the merged
tree (`e0915e0`), keeping the same file names and the same flow order:
that is all frames above except `nuitka-built-exe-connections.png`
(whose Connections-card region is unchanged; see its section).

How the retake ran, same hygiene as the original:

- Three throwaway desks under `%TEMP%\byok-merge-retake\` (desk A
  fresh for the CRUD and theme flows, desk B seeded with the legacy
  `llm_base` / `llm_key` / `llm_model` rows and the fake key
  `sk-demo-legacy-migration-0001` for the migration frames, desk C
  fresh again for a clean chronological CRUD pass), booted exactly
  like the original run: `python -m agentdesk.server --port <free>
  --no-browser`, `AGENTDESK_DATA` on the throwaway folder, the
  `AGENTDESK_LLM_*` overrides emptied, entered through the printed
  one-time start link.
- The same three loopback stub shapes (200 model list, 401, dead
  port); the same clearly fake keys; no screenshot shows an input
  holding a value. Two frames are byte-identical on purpose: the
  (b)-after-save and (c)-after-save views render exactly the same
  pixels (the claim of frame (c) is that nothing visibly changed),
  and the (e)-transient and (f)-cached frames share one view where
  both stamps are visible side by side.
- Chromium 1440x900 via playwright-cli, the same viewport as the
  original frames.

## Keychain cleanup (the walkthrough's traces are gone)

The walkthrough used the real OS keychain on purpose (the feature under
test). Entries it created, service `agent-desk`, username `key/<id>`:

- The original run's entries were cleaned the same day (documented in
  the previous revision of this README: plain targets via the keyring
  API, two compound `key/<id>@agent-desk` targets by exact name).
- The merge retake's entries: the app itself deleted the flow (d)
  clear and the flow (h) bound-delete entries through the keychain
  wrapper; the compound `key/<id>@agent-desk` targets kept three
  traces (`key/70aeb2a9...`, `key/01910b73...`, and
  `key/migrated-endpoint` from Desk B's migration, which deliberately
  keeps a migrated key so a restart can recover).

After the retake every remaining `agent-desk` entry was enumerated
with `CredEnumerateW` (filters `agent-desk*` and `key/*`, cross-checked
with `cmdkey /list`: 1 plain + 3 compound found), deleted by exact
target name through `CredDeleteW`, and the enumeration re-run across
`agent-desk*`, `key/*`, `*agent*` and `*desk*` plus `cmdkey /list`:
**0 agent-desk entries remain**. The throwaway data folders, their
sqlite stores, the stub/boot scripts and the browser session were
deleted with the temp run directory at the end.

## Artifacts not in this folder

The walkthrough's boot/stub/cleanup scripts and server logs lived in
the temp run directory and were deleted with it; this folder holds the
durable evidence only.
