# Spec 014: Open the workbook when the file dialog cannot open

Status: ready-for-agent (2026-11-18). File this as the spec issue with the
ready-for-agent label; once filed, the issue body is the live copy when the two disagree.

## Problem Statement

Clicking "Open a workbook" in either setup surface does one thing: it asks the server to
open the native file dialog. When that dialog cannot open, the server reports it as a
cancel, so the user is told "No file was opened." — a statement about a decision they never
made — and no other way to give the tracker its file is offered.

1. **The dialog's failure and the user's Cancel are the same value.** The Tk child
   interpreter prints the chosen path, or an empty line when the dialog is cancelled *or*
   Tk is unusable (`app.py:345-346`, `app.py:368-370`); the parent turns empty output into
   `None` (`app.py:416-417`); the setup flow turns `None` into
   `config:cancelled` / "No file was opened." (`setup_flow.py:43-44`); both surfaces print
   that message verbatim (`TrackerSetup.tsx:105`, `InstanceSetupSheet.tsx:75-77`). A
   no-display container, a Windows session with no interactive desktop, a Python build
   without Tk and a genuine Escape keypress all arrive as the same sentence.
2. **There is no recovery on the surface.** The server can already stage a path the user
   types (`app.py:4035-4039` → `setup_flow.py:51-58`), and nothing under `frontend/src`
   calls it. The server-rendered dashboard solved this years earlier with a typed-path
   field and an amber note (`sales.py:56-61`, `pages.py:485-488`); the SPA never adopted
   it, and a typed path alone cannot reach a file the user would first have to download.
3. **The only route to the bytes is a path on the server.** The calendar page already
   accepts a file from the browser (`pages.py:519-575`, `app.py:1403-1425`); the setup
   sheet has no equivalent, so a desk owner whose work lives in a web download, a mail
   attachment or a chat share cannot set up a tracker at all.
4. **It is not a container-only bug.** The product target is a locked-down Windows laptop
   launched by `tools/agent-desk.cmd`, where any Tk failure (missing Tcl, no interactive
   desktop, a locked session) takes the identical path. On a developer machine with a
   display the bug is invisible, which is why the suite passes today: the HTTP tests inject
   a fake picker (`tests/test_plugin_setup_http.py:12-39`, `server_harness.py`).

## Solution

- The picker answers three outcomes instead of two: picked, cancelled, dialog unavailable.
  Unavailable answers `503 config:picker-unavailable` with its own message; Cancelled keeps
  `400 config:cancelled`.
- Both setup surfaces gain the same recovery block on the Open step: type a path (the
  existing stage action) or choose a file in the browser (a new upload route). It is always
  reachable, and it opens itself when the pick answers unavailable — so a genuine Cancel
  also has a way forward.
- The upload route stores the copy under the plugin's data directory, stages it, and
  accepts the outside-workspace grant on the user's behalf, because the browser's own file
  picker already was the deliberate choice. The preview, the setup steps and every later
  read are unchanged.
- The native dialog stays the first choice and the fastest one; nothing about its position
  on the step changes.

## User Stories

1. As a desk owner, I want a message that distinguishes "the file dialog could not open"
   from "I cancelled", so that I stop hunting for a file I never chose.
2. As a desk owner on a machine with no working file dialog, I want to type the workbook's
   path, so that setup still finishes.
3. As a desk owner whose workbook is a browser download, I want to upload it from the setup
   sheet, so that I do not need to know where the server keeps files.
4. As a desk owner, I want both ways in on the same step as the dialog, so that a failure is
   one visible option away instead of a dead end.
5. As a desk owner who cancelled by mistake, I want the recovery block to be there anyway,
   so that I do not have to guess that the same button is the only option.
6. As a desk owner, I want the uploaded copy to be read like any other file — preview,
   columns, rows, confirm — so that the recovery costs no extra configuration.
7. As a desk owner, I want an honest refusal when my file is too large or the wrong kind, so
   that I know what happened instead of seeing a generic failure.
8. As a desk owner, I want that refusal to name the way forward, so that the error is a
   route and not a wall.
9. As a desk owner, I want the native dialog to stay the primary button, so that the fast
   path stays one click.
10. As an operator, I want the upload cap enforced on the server, so that a browser cannot
    post an unbounded body to a desk that stores what it receives.
11. As an implementer, I want the three picker outcomes pinned at the HTTP seam, so that the
    next refactor cannot silently merge them again.
12. As an implementer, I want the committed SPA bundle rebuilt with the change, so that a
    checkout with no Node installed still serves the fix.

## Implementation Decisions

1. **The picker child reports one JSON line, with three statuses.** `_PICKER_SNIPPET_TEMPLATE`
   (`app.py:350-371`) prints exactly one of:

   ```
   {"status": "picked", "path": "<absolute path>"}
   {"status": "cancelled"}
   {"status": "unavailable", "reason": "<exception class name>"}
   ```

   The template imports `json` instead of `sys`, keeps the existing parenting sequence
   (`app.py:357-366`), and replaces `except Exception: chosen = ""` (`app.py:368-369`) with a
   branch that prints the `unavailable` document. Anything that is not one of those three
   documents — empty output, a traceback, an unknown status — counts as unavailable, never
   as cancelled: a child that died before it could report must not be reported to the user
   as their own decision.
2. **The parent splits the three, and only the instance picker surfaces the third.** A new
   pure helper `_picker_outcome(stdout: str) -> str | None` reads the last non-empty line:
   a `picked` path is returned, `cancelled` returns `None`, and `unavailable` or
   unparseable output raises
   `ConfigError("config:picker-unavailable", "The file dialog could not open on this computer. Type the file's path, or upload the file instead.")`.
   `_tk_pick_file` (`app.py:400-417`) calls it and turns a spawn failure (`app.py:413-415`)
   into the same error after its existing `LOG.exception`. `tk_pick_plugin_file`
   (`app.py:430-432`) lets it propagate into the setup flow. `tk_pick_workbook` and
   `tk_pick_calendar` (`app.py:420-427`) catch it and keep returning `None`, because
   `/sources/excel-watch/pick` (`app.py:1334`) and the calendar route publish a
   `200 {"path": null}` contract that the server-rendered pages already read as "the dialog
   did not open, use the typed field" (`sales.py:56-61`, `pages.py:485-488`). Moving those
   two onto the new contract is a follow-up; this spec changes one route's behaviour.
3. **`setup_flow.pick` needs no change.** Unavailability is raised before the injected
   callable can return, so `pick_workbook()` at `setup_flow.py:42` either returns a path,
   returns `None` (cancel → `config:cancelled`, `setup_flow.py:43-44`) or raises. A picker
   injected by a test or through `create_server` (`app.py:5610-5618`) behaves identically.
4. **Setup errors carry a status.** The `ConfigError` handler in `_plugin_setup_post`
   (`app.py:4068-4070`) gains a module-level table and answers
   `_SETUP_ERROR_STATUS.get(exc.code, 400)`; `_setup_error` (`app.py:4103-4108`) uses the
   same table so both exits agree:

   ```
   _SETUP_ERROR_STATUS = {"config:picker-unavailable": 503, "config:too-large": 413}
   ```

   The resulting contract, unchanged parts stated so nothing is inferred:
   - picked: `200 {"instance": {…}, "preview": {"sheet": …, "headers": […], "rows": [[…]]}, "step": "columns"}`
     (`setup_flow.py:48`)
   - no dialog: `503 {"error": "config:picker-unavailable", "message": "The file dialog could not open on this computer. Type the file's path, or upload the file instead."}`
   - cancelled: `400 {"error": "config:cancelled", "message": "No file was opened."}` (`setup_flow.py:43-44`)
   - no picker configured: `400 {"error": "config:no-picker", "message": "The file picker is not available."}`
     (`setup_flow.py:40-41`)
5. **The Open step gains a recovery block, in both surfaces.** `TrackerSetup`
   (`TrackerSetup.tsx:244-257`) and `InstanceSetupSheet` (`InstanceSetupSheet.tsx:214-231`)
   render, below the primary "Open a workbook" button: a disclosure toggle labelled "Type a
   path or upload instead" (`<button type="button">` with `aria-expanded`), collapsed by
   default and opened automatically when the pick answers `config:picker-unavailable`;
   inside it a text field `aria-label="Workbook path"` with a "Use this path" button, and a
   file field `aria-label="Workbook file"` (`accept=".xlsx,.xlsm,.csv,.json"`) with an
   "Upload this file" button that stays disabled until a file is chosen. The primary button
   keeps its place, wording and busy state. A pick success and both recovery successes run
   one shared tail that sets the preview, selects every previewed row, clears the column
   choice and moves to the columns step (`TrackerSetup.tsx:108-113`;
   `InstanceSetupSheet.tsx:95-117` for the sheet's equivalent).
6. **A typed path is the existing stage action.** `POST /api/plugins/<pluginId>/instances/<instanceId>/stage`
   with `{"path": "<path as typed>"}` → `setup_flow.stage` (`app.py:4035-4039`,
   `setup_flow.py:51-58`). The existing refusals carry unchanged: `config:missing-file`
   (`config.py:99-100`) and `config:unsupported` (`config.py:101-105`), and the surface
   shows `message` in its error slot. No new endpoint, no new code.
7. **Upload is a new route, with the file name in the path.**
   `POST /api/plugins/<pluginId>/instances/<instanceId>/upload/<url-encoded file name>`,
   `Content-Type: application/octet-stream`, body = the file's bytes. The name travels as
   the last path segment because `_route_post` discards the query string before routing
   (`app.py:1309`), so `?name=` would vanish silently; the client percent-encodes the name
   and the handler `unquote`s it (`unquote` is already imported, `app.py:30`). Dispatch is
   the existing split (`app.py:4027-4028`): `parts[5] == "upload"`, `parts[6]` the name.
   The handler reads the bytes from `self._raw_body` (`app.py:1321`) and ignores the JSON
   `body` (`app.py:1571`), which arrives as `{}` for binary input because
   `_read_json_body` cannot decode it (`app.py:1737-1741`). Responses, all through the
   table in decision 4:
   - `200` the same `{"instance", "preview", "step": "columns"}` document as pick and stage
   - `413 {"error": "config:too-large", "message": "The file is larger than 4 MB. Save a smaller copy, or type the file's path instead."}`
   - `400 {"error": "config:unsupported", "message": "Open an .xlsx, .xlsm, .csv, or .json file."}`
   - `400 {"error": "config:unsafe-name", "message": "That file name cannot be stored. Rename the file and try again."}`
   - `400 {"error": "config:empty-upload", "message": "The upload carried no bytes. Choose the file again."}`
8. **The cap is 4 MB, and the body drain learns about it.**
   `MAX_UPLOAD_BYTES = 4 * 1024 * 1024` lives beside `_SUFFIXES` (`config.py:17`), and
   `app.py` imports it where it already imports plugin helpers (`app.py:4002`).
   `body_drain_plan` (`app.py:240-251`) and `_drain_body` (`app.py:1715-1729`) take a
   `limit` defaulting to `MAX_BODY_BYTES` (`app.py:218`); `_route_post` passes
   `MAX_UPLOAD_BYTES` when the path matches a new module-level
   `_PLUGIN_UPLOAD_PATH = re.compile(r"^/api/plugins/[^/]+/instances/[^/]+/upload/")`
   (`re` is already imported, `app.py:15`) and the old default otherwise. The handler tests
   the declared length first, from `self._content_length` (`app.py:1720`), which a
   discarded body still sets — so a 5 MB post answers `413` rather than "empty".
   `MAX_DRAIN_BYTES` (`app.py:237`) stays at eight times `MAX_BODY_BYTES`: the upload cap
   sits below it, so every upload worth answering is drained rather than closed.
9. **The copy lands in the plugin's data directory and is accepted once.** A new
   `InstanceStore.store_upload(self, plugin_id: str, instance_id: str, filename: str, raw: bytes) -> Path`
   writes `<root>/<pluginId>/uploads/<instanceId>/<filename>`, mirroring `_instance_dir`
   (`config.py:49-50`). It refuses a name that is not a bare file name — a `/`, a
   backslash or `..` → `config:unsafe-name` — refuses a suffix outside `_SUFFIXES` with the stage
   message (`config.py:17, 101-105`), refuses empty bytes (`config:empty-upload`) and
   over-cap bytes (`config:too-large`, so the store is safe on its own), creates the
   directory and writes the bytes.
   `setup_flow.upload(runtime, cap, instance_id, name, raw, filename, plugin_id)` then calls
   `store.stage_file(...)` (`config.py:97-119`) and
   `store.accept_outside(...)` (`config.py:121-128`) before reading the document and
   previewing it exactly as `stage` does (`setup_flow.py:56-58`).
   Accepting is deliberate: the copy sits under the plugin data directory, outside the
   workspace (`app.py:5915-5916`), and the outside-acceptance rule exists so that pointing a
   plugin at a file beyond the workspace is a deliberate act (Spec 006, Implementation
   Decisions 5). Choosing the file in the browser's own picker is that act; asking the user
   to accept the path of the copy the desk just made for them would be theatre. A typed path
   keeps the explicit step, and any later `stage_file` rewrites the grant with
   `outsideAccepted: false` (`config.py:117-118`), so the acceptance cannot be inherited by
   a different file.
10. **One wire helper per layer.** `frontend/src/api.ts` gains
    `postFile(url: string, file: File): Promise<ApiResult>`, posting the file with
    `Content-Type: application/octet-stream`, modelled on `postJson` (`api.ts:17-25`) and
    reusing `safeJson` (`api.ts:27-33`). `marketplace/client.ts` gains
    `postUpload<T>(pluginId: string, tail: string, file: File): Promise<T>` that calls it and
    throws through the existing `unwrap` (`client.ts:22-34`), so `InstanceSetupSheet`'s catch
    keeps one error path and branches on `err.code === 'config:picker-unavailable'`
    (`InstanceSetupSheet.tsx:146-154`). `TrackerSetup` uses `postJson` for stage
    (`api.ts:17-25`) and its existing `res.status`/`res.data` handling for everything else
    (`TrackerSetup.tsx:98-114`).
11. **The committed bundle is part of the change.** Production serves
    `src/agentdesk/server/static/spa/`, built by `npm run build` from `frontend/` and
    committed (`app.py:253-258`; `vite.config.ts` sets `build.outDir` to that folder with
    `emptyOutDir: true`). `frontend/package.json:9-13` holds `build`, `check`
    (`tsc --noEmit`) and `test` (`vitest run`). A frontend change therefore means: run
    `npm run check` and `npm run test` in `frontend/`, run `npm run build`, and commit the
    regenerated folder — vite empties it, so the previous hashed asset names disappear and
    the diff is the whole folder. No dev-proxy change is needed: `/api` is already proxied
    (`vite.config.ts:23-31`).
12. **Copy.** The sheet's existing note ("The file dialog opens on this computer; only the
    file's name comes back.", `InstanceSetupSheet.tsx:222-225`) stays true for a dialog and
    stays. The `503` path shows the server's message in the dialog's error slot and opens
    the recovery block; nothing client-side rewrites the message. A `config:cancelled`
    message stays as it is and leaves the block closed, still one click away.

## Testing Decisions

- **What a good test is:** external behaviour only — HTTP status and JSON envelope, the
  message a surface renders, the request a surface sends, the bytes that land on disk. No
  private helper is asserted except the one pure parser named below, whose inputs cannot be
  produced through HTTP without a display.
- **Seam 1 — the setup contract over real sockets.** `tests/server_harness.py` boots the
  real server; `tests/test_plugin_setup_http.py:12-39` installs the bundled
  `excel-report` plugin with an injected `pick_workbook`. New cases against that fixture:
  - a picker raising `ConfigError("config:picker-unavailable", …)` answers `503` with the
    exact envelope of decision 4, and the instance is still unconfigured (`source` null);
  - a picker returning `None` answers `400 config:cancelled` with "No file was opened."
    (no test covers this today);
  - `POST …/stage {"path": str(book)}` answers `200` with the preview headers (no test
    covers stage today);
  - `POST …/upload/q4.xlsx` with measured fixture bytes answers `200`, the stored
    `source.path` is inside the fixture's `data_dir` and outside `workspace_dir`, the
    stored bytes equal the posted bytes, and `confirm` then succeeds with no `/outside`
    call;
  - a 5 MiB upload answers `413 config:too-large`, and an ordinary request on the same
    server still answers `200` afterwards;
  - `POST …/upload/notes.txt` answers `400 config:unsupported`; `POST …/upload/..%2Fescape.xlsx`
    answers `400 config:unsafe-name` with nothing written outside the instance's upload
    directory;
  - an upload with an empty body answers `400 config:empty-upload`.
- **Seam 2 — the picker parser.** `_picker_outcome` is tested directly for the four inputs
  that cannot be produced headlessly: `picked`, `cancelled`, `unavailable`, and
  garbage/empty (both unavailable). It is the only unit-level test this spec adds, justified
  because the container's `tkinter.Tk()` raises
  `TclError: no display name and no $DISPLAY environment variable`.
- **Existing test to update:** `tests/test_server_excel_api.py:345-348` asserts the child
  contains `except Exception:` and `print(chosen)`. The template still catches broadly but
  prints a JSON document, so those assertions move to the three statuses; the
  `-topmost`/`lift`/`focus_force` assertions above them (`:340-343`) stay.
- **Seam 3 — the SPA surfaces.** Vitest with `@testing-library/react` and a mocked
  `fetch`, following `frontend/src/test/tracker-setup.test.tsx` (`jsonResponse` helper
  `:12-18`, per-URL fetch routing, the real `TrackerCard`): a `503` answer shows the
  message and expands the recovery block, and a typed path plus "Use this path" posts
  `{"path": …}` to `/stage` and reaches the columns grid; choosing a file and clicking
  "Upload this file" posts that file to `/upload/<name>` with
  `Content-Type: application/octet-stream` and reaches the columns grid; a `400` cancel
  shows "No file was opened." with the block present but collapsed. The same three run
  through `InstanceSetupSheet` in `frontend/src/test/setup-sheet-selection.test.tsx`, in
  create and manage modes, with the existing fixtures
  (`frontend/src/test/marketplace-fixtures.ts`) and the manage-view prior art
  (`frontend/src/test/marketplace-manage-instances.test.tsx:111-132`).
- The change ships with `npm run check`, `npm run test` and a rebuilt, committed
  `static/spa` bundle. The dev-proxy pin (`frontend/src/test/devproxy.test.ts`) needs no
  edit because the new route lives under `/api`.

## Out of Scope

- Moving the server-rendered dashboard and calendar pickers onto the three-outcome contract.
  Their `200 {"path": null}` shape and typed-path fallbacks keep working; the pickup is a
  follow-up.
- Any change to workspace containment or outside-acceptance rules, the suffix allowlist, the
  instance cap, or the preview and confirm payloads.
- Drag-and-drop, multiple files, paste-a-path, or reading the file in the browser.
- Installing or repairing Tk on the host, a `--headless` server flag, or detecting a desktop
  session before the click.
- CSV delimiter or encoding options beyond what `stage_file` and `preview_table` already
  do, and any new file kind.
- The marketplace discovery and install surfaces, the wizard, and the desk chrome.

## Further Notes

- **Why JSON on stdout rather than an exit code.** After a successful pick the child can
  still fail on `root.destroy()`, and after a Cancel the same call can raise; an exit status
  therefore cannot separate "picked" from "unavailable". One JSON line per child is the
  smallest protocol that can carry a path containing anything.
- **Why the file name is a path segment.** `_route_post` strips the query at `app.py:1309`
  before any handler sees the path, so `?name=` would be dropped silently; an implementer
  who reaches for a query parameter gets an upload with no name and a `config:unsafe-name`
  refusal that looks unrelated.
- **Alternative rejected: `200 {"path": null}` plus a reason field.** It keeps the envelope
  and adds no new status, but the surface would infer intent from an extra field, and the bug
  is precisely that two intents share one value. A distinct status and code is the contract
  that cannot regress silently.
- **Alternative rejected: writing the copy inside the workspace.** That would skip the
  outside-acceptance step, but every plugin's workspace read scope would then cover another
  plugin's uploads. The data directory plus the per-instance grant keeps instances isolated,
  at the price of one auto-accepted grant.
- **Alternative considered and kept:** the typed path alone. It is the cheaper fix and
  already exists on the server, but it cannot reach a file that lives only in the browser's
  download folder — exactly the locked-down-laptop case this desk is for.
- **How to reproduce before the fix:** run the server with `DISPLAY` unset (or on a Windows
  session with no interactive desktop), open a tracker's setup sheet and click "Open a
  workbook": the answer is `400 config:cancelled` and the sheet says "No file was opened."
  On a machine with a display the same click opens a dialog, which is why every existing test
  passes.
- **The visible trade-off is deliberate.** The setup step now shows a second way in, one
  disclosure below the primary button, always present so a cancel is not a dead end. Only the
  auto-open is conditional; the routes and messages do not depend on it.
