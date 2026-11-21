# BYOK evidence pack, 2026-11-21 (spec 018, ticket #235)

The proof behind the BYOK close-out: the full local gate green, the
suite green with no OS keychain anywhere, the Nuitka smoke leg with
keyring present, and a browser walkthrough that screenshots every
user-visible flow the spec shipped. The repo owner's rule applies: a
flow without a screenshot here means that flow was not done.

## How the walkthrough ran

- Two throwaway data folders under the system temp dir
  (`%TEMP%\\byok-desk-a`, `%TEMP%\\byok-desk-b`), never the user's real
  `%USERPROFILE%\\.agent-desk`. Desk A booted fresh; Desk B's settings
  sqlite was seeded before boot with the legacy rows (`llm_base`,
  `llm_key`, `llm_model`) using the clearly fake key value
  `sk-demo-legacy-migration-0001`, so the one-boot migration ran on a
  real start. Both boots were the real app: `python -m agentdesk.server
  --port <free port> --no-browser` with `AGENTDESK_DATA` pointed at the
  throwaway folder and the `AGENTDESK_*` endpoint overrides emptied,
  entered through the printed one-time start link.
- Loopback stub endpoints (stdlib `http.server` on 127.0.0.1 free
  ports) played the provider, the same shapes
  `tests/server_harness.py` and `tests/test_server_keys_health.py`
  pin: one answered `GET /v1/models` 200 with `demo-mini` and
  `demo-large` (and a canned completion for the deeper check), one
  answered 401, and one recorded port was left dead for the transient
  case.
- Every key typed during the walkthrough was a clearly fake demo value
  (`sk-demo-byok-walkthrough-0001`, `sk-demo-bad-9999`,
  `sk-demo-dead-7777`). No screenshot shows an input holding a value:
  forms were captured before typing and after saves, where only masked
  hints render.
- Screenshots were taken with playwright-cli (Chromium, 1440x900)
  against the running desks.

## The captured gate

- `ci-local.txt`: the complete output of `python tools/ci_local.py`
  (launched detached because the run takes ~577 s). It ends:

      7/7 gates passed in 577s
      CI PASS

  pytest leg: `2743 passed, 1 skipped` over a fresh temp data dir.
  Note: the `py-grammar` leg reports `0 files parse under 3.10` because
  this worktree lives under a `.worktrees` parent the gate's walker
  deliberately skips; from a normal checkout path it scans the tree.

- `null-keyring-pytest.txt`: the full pytest suite with
  `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring` forced in the
  environment (probe printed `keyring.backends.fail.Keyring
  (priority: 0)` before the run), stderr empty, verdict
  `2741 passed, 2 skipped, 10 warnings in 570.22s`. CI parity with no
  OS keychain anywhere: connections still save (without secrets), the
  page names the state, tests inject fakes.

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
  the keychain live and no no-keychain notice.

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
| `05-test-badge-transient-dead-port.png` | (e) Test: transient | A dead port: the badge keeps its stored status (`unknown` on a fresh row, the spec's mapping for transport failures) and the inline cause names it: "the endpoint host refused the connection: nothing is listening at 127.0.0.1:61038". The frame also shows all three badge states side by side. |
| `06-models-cached-row.png` | (f) model refresh, page | The deeper-check/model block's row after the check: the model block shows "2 models cached" from the loopback stub. |
| `06-models-refresh-discovered-ids.png` | (f) model refresh, the ids | `GET /api/connections/<id>/models?refresh=1` (the refresh route re-fetches server-side) rendering the discovered ids `demo-mini`, `demo-large` with their fetched-at stamp in the browser. |
| `07-job-binding-serves-through.png` | (g) per-job picker | The assistant job bound to Demo stub with model `demo-mini`; the picker shows Demo stub as the selected option (retaken after the #235 fix) and the readback line agrees: "Serves through Demo stub, model demo-mini." |
| `08-delete-bound-jobs-warning.png` | (h) delete with bound jobs | The no-JS confirmation page a bound connection's first delete answers with: it names the bound job ("Demo stub is bound to the assistant job"), what the delete removes, and the "Keep it" exit. |
| `08-connections-after-delete.png` | (h) after confirm | The list without the deleted connection; the remaining rows (Stub rejects, Dead port) keep their badges. The binding went with the delete. |
| `09-migrated-endpoint-connection.png` | (i) migration | Desk B after a real boot over legacy settings rows: the "Migrated endpoint" connection with the Custom preset, its masked hint (`sk-...0001`), the legacy base URL verbatim, and the default star. |
| `09-migrated-default-job-bound.png` | (i) migration bound the job | The default job's readback: "Serves through Migrated endpoint, model demo-mini.", the legacy `llm_model` carried into the binding. |
| `10-theme-unkey-connections.png` | (j) theme: Unkey | The Connections card under the default dark yellow-green theme, three saved connections rendering badges, masked hints and the preset grid. |
| `10-theme-unkey-jobs.png` | (j) theme: Unkey | The Jobs card under Unkey, retaken after the #235 fix: the assistant picker shows its bound connection, the six unbound pickers show Not bound. |
| `10-theme-coforge-connections.png` | (j) theme: Coforge | The Connections card under the navy/coral theme. |
| `10-theme-coforge-jobs.png` | (j) theme: Coforge | The Jobs card under Coforge, retaken after the #235 fix (the corrected picker, `1 BOUND`). |
| `10-theme-momentuum-connections.png` | (j) theme: Momentuum blue | The Connections card under the light brand-blue theme. |
| `10-theme-momentuum-jobs.png` | (j) theme: Momentuum blue | The Jobs card under Momentuum blue, retaken after the #235 fix (the corrected picker, `1 BOUND`). |

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
state:

- `07-job-binding-serves-through.png` and the three
  `10-theme-*-jobs.png` frames were re-captured against a fresh
  throwaway desk (`%TEMP%\\byok-refresh\\desk-a`, never the real
  `%USERPROFILE%\\.agent-desk`), booted exactly like the original run:
  `python -m agentdesk.server --port <free> --no-browser` with
  `AGENTDESK_DATA` on the throwaway folder, the `AGENTDESK_*` overrides
  emptied, and the branch's `src` on `PYTHONPATH` so the desk ran this
  worktree's code. The same loopback stub (stdlib `http.server`) served
  `GET /v1/models` 200 with `demo-mini` and `demo-large`; the Demo stub
  connection was created through the real form with the clearly fake
  key `sk-demo-byok-walkthrough-0001`, and the assistant job bound to
  it through the real picker. Chromium 1440x900 via playwright-cli, the
  same viewport as the original frames. No screenshot shows an input
  holding a raw key value (the frames show the Jobs card only, where no
  key field exists).

## Keychain cleanup (the walkthrough's traces are gone)

The walkthrough used the real OS keychain on purpose (the feature under
test). Entries it created, service `agent-desk`, username `key/<id>`:

- `key/2aa13365...` (Demo stub): already removed by the app itself,
  because flow (d)'s clear-key action deletes the entry through the
  keychain wrapper.
- `key/8f7b34c5...` (Stub rejects), `key/b1e3fa92...` (Dead port),
  `key/migrated-endpoint` (Desk B's migration; the delete route
  deliberately keeps a migrated key so a restart can recover).

After the walkthrough every remaining `agent-desk` entry was enumerated
with `cmdkey /list` (3 found), deleted through the keyring API, and the
enumeration re-run: **0 agent-desk entries remain**. The throwaway data
folders and their sqlite stores were deleted with the temp run
directory at the end.

The #235 refresh pass created its own keychain traces and cleaned them
the same way: the retake's two boots (one before noticing the desk was
importing a stale installed copy, one on the worktree code) saved the
demo key twice, and the keyring backend kept the first save under its
compound target (`key/<id>@agent-desk`) when the second landed. Both
targets were enumerated (`CredEnumerateW` via the same win32 API the
keyring backend wraps, cross-checked with `cmdkey /list`: 2 found),
deleted by exact target name, and the enumeration re-run: **0
agent-desk entries remain** (confirmed by `CredEnumerateW`, `cmdkey
/list` and `keyring.get_password` returning nothing).

## Artifacts not in this folder

The walkthrough's boot/stub/cleanup scripts and server logs lived in
the temp run directory and were deleted with it; this folder holds the
durable evidence only.
