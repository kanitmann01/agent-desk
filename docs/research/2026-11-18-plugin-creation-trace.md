# Plugin creation trace: Studio to a working widget

Date: 2026-11-18
Repo: D:\20-projects\Personal Agents\agent-desk (HEAD 02ea418 plus uncommitted working-tree changes; see "Working tree state" below)
Scope: READ-ONLY investigation of the "create a plugin" flow. No source, test or data files were modified by this investigation. The only file this investigation wrote is this report.
Runtime: Windows 11, Python 3.14.5, pytest, Vitest with the committed SPA build (server/static/spa).

## Verdict

The chain works further than expected, but it does not end in a working widget:

- PASS: Studio builds a valid v2 payload, /api/marketplace/validate returns {"ok": true, "failures": []}, /api/marketplace/studio/install returns 200 "installed", /api/marketplace/publish returns 202 "pending-review", and with admin mode on the publication is approved, copied to the org catalog with a tree digest, listed in Discover, and installs from Detail.
- FAIL: the dashboard card for the installed plugin is amber ("attention") with payload.elements = [], not the metric and text Studio previewed. The cause string is "The manual metric file ...\\plugin-data\\<id>\\manual.json does not exist yet."
- FIRST BROKEN HOP: H4 -> H5, install -> runtime data source attach -> dashboard card. Every install path (Studio personal install and catalog install after approval) lands here. Nothing in product code ever writes the manual-metric data file that the Studio template declares.
- SECOND BREAK, operational: in a normally launched app (AGENTDESK_MARKETPLACE_ADMIN unset) the publish branch dead-ends at approve with 403 admin:disabled. Studio's "Pending review" panel does not mention the switch, so a normal user sees a successful submission that can never appear.
- The marketplace preview is green because it renders sample.json through plugins/render.py render_sample, not the live data source. That masks the runtime failure until after install.

## Reproduction

All reproduction used throwaway booted servers from tests/server_harness.py (temp plugin/data/workspace roots under %TEMP%\\agentdesk-plugins-*), never the real ~/.agent-desk. Two standalone scripts were kept outside the repo:

- C:\\Users\\mannk\\AppData\\Local\\Temp\\studio_trace_install.py - exact Studio payload, personal install path, dashboard, data dir, retest, positive control.
- C:\\Users\\mannk\\AppData\\Local\\Temp\\studio_trace_noadmin.py - same payload with AGENTDESK_MARKETPLACE_ADMIN removed.

Commands and results:

    cd "D:\20-projects\Personal Agents\agent-desk"
    python -m pytest tests/test_marketplace_fresh_desk.py -q      -> 3 passed
    python -m pytest tests/test_studio_install.py -q              -> 2 passed
    python -m pytest tests/test_server_publish.py -q              -> 6 passed
    python -m pytest tests/test_marketplace_api.py -q             -> 51 passed
    python -m pytest tests/test_registry_publish.py -q            -> 20 passed
    cd frontend && npx vitest run src/test/marketplace-studio.test.tsx -> 2 passed
    python "C:\\Users\\mannk\\AppData\\Local\\Temp\\studio_trace_install.py" -> exit 0, transcript below
    python "C:\\Users\\mannk\\AppData\\Local\\Temp\\studio_trace_noadmin.py" -> exit 0, transcript below

## Working tree state

The trace ran against the live working tree at 2026-11-18 02:50-03:10 local time, which was HEAD 02ea418 plus uncommitted changes made by concurrent work, not by this investigation:

- Studio's personal-install path is uncommitted: frontend/src/marketplace/Studio.tsx (Install on this desk, ~58 lines), src/agentdesk/marketplace/api.py (POST /api/marketplace/studio/install, post_studio_install ~52 lines), frontend/src/test/marketplace-studio.test.tsx (+1 install test), and the new untracked tests/test_studio_install.py. HEAD does not contain /studio/install, so that endpoint is not in the last commit; the failure traced here is equally present after approval through the committed catalog install path.
- Unrelated in-flight work was also present: outlook-brief support in src/agentdesk/plugins/execute.py, sources.py, validator/lint.py, mail/core.py, mail/watcher.py, marketplace/policy.py and their tests; regenerated registry/index.json, src/agentdesk/marketplace/bundled-catalog.json and registry/plugins/outlook-digest/*; untracked demo/, docs/tickets/2026-11-18/, specs/008-plugin-truth-and-outlook-brief.md, src/agentdesk/mail/brief.py, tests/test_mail_brief.py, tools/export-outlook.ps1.

All file:line references in this report are working-tree line numbers, not HEAD line numbers. Two modifications (registry/index.json and bundled-catalog.json) predate the trace; the rest appeared while it ran.

## Hops table

| # | Hop | Code path | What was verified | Status |
|---|-----|-----------|-------------------|--------|
| H1 | Open marketplace and Studio | frontend/src/marketplace/MarketplaceApp.tsx:29, :65-66, :76-101; client.ts:36-46 | Studio route and tab render; API client maps failures to MarketApiError | works |
| H2 | Build payload from the form | frontend/src/marketplace/Studio.tsx:33-77 (dataSource :70, render :71, sample :74), :82-91 (elements :87-88), :95-108 | Valid schemaVersion 2 manifest; dataSource is {"type":"manual-metric"} with no file; the text element binds "note" | works, contract already incoherent |
| H3 | Run validator | Studio.tsx:175-192, :345-364 -> src/agentdesk/marketplace/api.py:946-980, :1135-1145, :1066-1082 -> validator/core.py -> validator/lint.py:657-722 | 200 {"ok": true, "failures": []} | works, but blind to H2's data contract |
| H4 | Install on this desk (personal path) | Studio.tsx:194-213, :366-377 -> api.py:1084-1133 (copy :1114-1118, runtime.install :1120) -> plugins/runtime.py:225-289 (empty data dir :265-266, attach :284), plugins/execute.py:254-310, plugins/sources.py:725-741 | 200 {"status":"installed"}; installed record status "attention"; cause manual.json missing | install succeeds, plugin unusable - FIRST BROKEN HOP |
| H5 | Dashboard card renders | server/app.py:960, :1015-1031, :1268; plugins/runtime.py:731-790; plugins/execute.py:383-396, :655-668, :712-738; frontend/src/dashboard/PluginCardView.tsx:76-77, :111-129 | freshness "attention", payload.elements [], amber alert with the cause, no metric or text | BROKEN |
| H6 | Publish for review | Studio.tsx:215-242, :379-396 -> api.py:1388-1441 | 202 {"status":"pending-review"}; queue does not require validation.ok | works |
| H7 | Operator approves | frontend/src/marketplace/Admin.tsx:156-186, :208-231 -> api.py:1520-1588; admin gate api.py:54, :625-636 | Normal launch: 403 admin:disabled (Admin page also 403). With env: 200, org copy, digest, org-catalog entry | BLOCKED by default launch - second break |
| H8 | Catalog and Detail | api.py:180-201, :421-458; marketplace/catalog.py:195-241, :402, :430, :452; plugins/render.py:526-551 | Org entry appears in Discover (26 entries total), eligible; Detail returns a green sample preview | works, but the preview is sample data, not runtime data |
| H9 | Install from Detail | frontend/src/marketplace/PluginDetail.tsx:71-118, :337-371 -> api.py:905-918, :920-942, :991-1027 | 200 installed, digest pinned and re-verified | works mechanically; H5 breaks the same way |
| H10 | Save locally to the registry (alternative path) | server/app.py:4110-4136 (deprecated dispatch), :4496+ _publish_plugin; registry/publish.py publish_to_registry | Headless only: no SPA string calls it; requires an installed record; writes registry/index.json and registry/plugins/<id>/<version> | not reachable from the shipped UI |

Definition used for "first broken hop": the earliest hop where the user-visible goal ("plugin appears as a working widget/card") stops being true even though the HTTP call reports success. That is H4 -> H5. H7 is earlier in the publish branch only, and is an operational gate rather than a defect in the created plugin.

## Hop detail and evidence

### H1-H2: what Studio actually sends

Studio's blank template (Studio.tsx:33-77) is a fixed shape. The data source is hard-coded at Studio.tsx:70 as {"type":"manual-metric"} with no file. The widget schema at Studio.tsx:82-91 asks for a metric bound to "value" and a text bound to "note". The sample at Studio.tsx:102-108 supplies {"value":0,"note":"This is the plugin sample."}. The on-screen preview at Studio.tsx:95-100 is a third, separate shape: it hard-codes value "0" and uses the form summary for the text, so the preview does not exercise either the sample or the data source.

The two bindings and the sample form a closed loop for validation, because the validator only checks that the sample exists, is a JSON object under 32 KB, and has a bindings object (validator/lint.py:657-722). It never compares those bindings with the data source's output vocabulary. So a manifest whose widget can never be populated by its own data source passes validation.

### H3: validator result

POST /api/marketplace/validate -> 200 {"ok": true, "failures": []}.

The validator does check that manual-metric is a known source type (validator/lint.py:28-42) and deliberately does not require a file for it: it treats a relative "file" value as a display hint while a host-owned default is read (validator/lint.py:44-53, :195-208). That is the exact assumption that fails at runtime, where the host-owned default does not exist.

### H4: personal install succeeds mechanically

POST /api/marketplace/studio/install (api.py:1084-1133) writes the inline plugin to a temp dir, validates it, copies it to marketplace/studio/<id>/<version> (api.py:1114-1118), then calls runtime.install(target, source="studio") (api.py:1120). runtime.install (plugins/runtime.py:225-289) validates again, copies to plugins/<id>/<version>, creates the data directory with mkdir only (runtime.py:265-266), and attaches the runner (runtime.py:284).

attach (plugins/execute.py:254-310) takes the first widget's dataSource, sees manual-metric as a known source, and reads it once for status. sources.py:725-741 then does:

    declared = source.get("file") or "${pluginData}/manual.json"
    ...
    if not path.exists():
        return _blank("missing-file", "The manual metric file {path} does not exist yet.", ...)

nothing in the product writes that file. The only writers to plugin state are workbook config (plugins/config.py:189-191, instance config under the config workspace), watch state (plugins/sources.py:1198), tracker history (plugins/tracker.py:112), and the wizard's inline writer (server/app.py:5366-5368). A repo-wide search for manual.json / manual-metric / pluginData found readers only: sources.py, validator/lint.py, wizard/core.py, Studio.tsx:70, Sample.tsx:105.

Observed transcript (personal path, no admin env):

    A. GET /api/marketplace/installed before: 200
    B. POST /api/marketplace/validate -> 200 {"ok": true, "failures": []}
    C. POST /api/marketplace/studio/install -> 200 {"id":"team-notes","version":"0.1.0","status":"installed","validation":{"ok":true,"failures":[]},"source":"studio"}
    D. GET /api/marketplace/installed -> 200
       status: {"status":"attention","cause":"The manual metric file ...\\plugin-data\\team-notes\\manual.json does not exist yet.", ...}
    E. GET /api/dashboard -> 200
       card: {"id":"team-notes","title":"Team Notes","version":"0.1.0","pilot":true,"state":"enabled",
              "freshness":"attention","cause":"The manual metric file ... does not exist yet.",
              "payload":{"elements":[],"status":"attention","cause":"...","source":{"type":"manual-metric","state":"blank","reason":"missing-file",...}}}
    F. GET /api/plugins/team-notes -> 200
       data_source: {"type":"manual-metric","state":"blank","reason":"missing-file","status":"attention", ...}
       versions: [{"version":"0.1.0","dir":"...\\plugins\\team-notes\\0.1.0", ...}]
    G. data_dir: ...\\plugin-data\\team-notes exists: True files: []
    H. marketplace/studio copy: ...\\workspace\\marketplace\\studio\\team-notes\\0.1.0 exists: True
    I. POST /api/plugins/team-notes/retest -> 200, still "attention", still missing-file
    J. GET /api/dashboard after retest: unchanged, payload.elements []
    K. manual.json seeded by hand ({"value":7,"target":10,"unit":"USD","note":"hand-written note","updatedAt":"2026-11-18T03:10:00-05:00"}) ->
       card freshness "fresh", payload.elements [{"kind":"metric","value":"7","label":"Value"},
       {"kind":"text","state":"blank","text":"","reason":"no value for binding note","label":"About"}]

Step K is the positive control: the only missing ingredient for a fresh card is the data file. It also proves the second half of H2's contract is impossible: manual-metric never emits a "note" binding (sources.py:725-784 emits value, unit, history, lastUpdated, count, points, file, plus optional target/delta/rows/table), and extra JSON keys are ignored. Even a hand-written data file leaves the text element blank.

### H5: dashboard card is the visible failure

runtime.widget_cards (plugins/runtime.py:731-790) reads runner.card(id) -> execute.card (plugins/execute.py:383-396) -> _render (:712-738), and _render deliberately empties elements when the data source status is not fresh:

    elements = render_elements(schema, bindings)
    if status["status"] != "fresh":
        elements = []

The SPA receives payload.elements = [] (server/app.py:1015-1031) and PluginCardView.tsx:76-77 drops elements unless freshness is "fresh"; lines 111-129 render the amber alert with card.cause and the "Re-test runs the plugin's data source again" note. So the user sees an amber card with a path, not a widget.

### H6-H9: publish branch

POST /api/marketplace/publish -> 202 {"pendingId":"pub-1f0544e8959a","validation":{"ok":true,"failures":[]},"status":"pending-review"}. The queue accepts a failing validation too (api.py:1388-1441 never checks validation.ok).

With AGENTDESK_MARKETPLACE_ADMIN=1:

    POST /api/marketplace/admin/publications/pub-1f0544e8959a/approve -> 200 {"ok":true,"decision":"approve","pluginId":"team-notes","version":"0.1.0","catalogSource":"org","validation":{"ok":true,"failures":[]}}
    GET /api/marketplace/catalog?source=org -> 200, 1 entry (team-notes), eligible true
    GET /api/marketplace/catalog -> 200, 26 entries (25 bundled + team-notes)
    GET /api/marketplace/plugin/team-notes -> 200, digest 42b1a864..., installed null,
        sample preview: [{"kind":"metric","value":"0","label":"Value"},{"kind":"text","text":"This is the plugin sample.","label":"About"}], status "fresh"
    POST /api/marketplace/install {"id":"team-notes","version":"0.1.0"} -> 200 {"status":"installed", ...}
    GET /api/dashboard -> the same amber card with payload.elements []

The org catalog entry has no sample field (api.py:_approved_release :1597-1633 does not copy it), so the card-level sampleAvailable is false while the source folder does contain sample.json. Detail still renders the preview because get_plugin (:421-458) reads the sample from the plugin folder when the catalog entry has none (plugins/render.py render_sample :526-551). This is why the marketplace looks healthy while the installed card is not.

Without admin mode (normal launch):

    POST /api/marketplace/publish -> 202 (queued)
    GET /api/marketplace/admin -> 403 {"error":"admin:disabled","message":"the marketplace admin surface is disabled; set AGENTDESK_MARKETPLACE_ADMIN=1 and reload the server","details":{"env":"AGENTDESK_MARKETPLACE_ADMIN"}}
    POST /api/marketplace/admin/publications/<id>/approve -> same 403
    GET /api/marketplace/catalog -> 25 entries, team-notes absent
    GET /api/marketplace/plugin/team-notes -> 404 {"error":"catalog:not-found", ...}

No launcher, script or packaging file sets AGENTDESK_MARKETPLACE_ADMIN; the only references are README.md:48, docs/ops/marketplace-operator.md:33 and :208, docs/known-limitations.md:15-16, the API code, and tests. So the default desktop launch cannot complete the publish branch at all.

### H10: the local registry path

The old POST /api/plugins/<id>/publish action (server/app.py:4110-4136) calls _publish_plugin -> registry.publish.publish_to_registry and writes registry/index.json plus registry/plugins/<id>/<version>. It is marked deprecated for one release and no frontend string calls it. The wizard's separate "Publish to the registry" step (src/agentdesk/server/wizard_view.py:383, DEMO.md:127-132) is a different, server-rendered creation path with a workbook setup step (wizard_view.py:370) that does turn a card fresh. The marketplace Studio has no equivalent setup step for manual-metric.

## Root cause (RCA 5-Why)

1. Why is the created plugin's dashboard card amber with no elements?
   Because execute._render empties elements when the data source status is not fresh (execute.py:712-738), and manual-metric reports blank/missing-file (sources.py:725-741).
2. Why is the manual metric file missing?
   Because runtime.install creates the plugin data directory as an empty mkdir (runtime.py:265-266) and no install, setup, or UI path ever writes manual.json. manual-metric's default path is "${pluginData}/manual.json" (sources.py:725-726).
3. Why does nothing write it?
   Because the only host-owned setup mechanism is the config.kinds branch (execute.py:254-310; plugins/config.py:108 has only "kind": "workbook"), and Studio never emits config.kinds. There is no manual-metric setup kind, no setup sheet, and no endpoint.
4. Why did the blank template get this shape?
   Because Studio hard-codes the dataSource (Studio.tsx:70) and hard-codes a widget that binds "value" and "note" (Studio.tsx:87-88), while the sample (Studio.tsx:102-108) satisfies both bindings only inside the validator. The source's real vocabulary (sources.py:760-784) has no "note".
5. Why did validation and tests not catch it?
   Because validator/lint.py only checks sample presence/shape (:657-722) and never checks element bindings against the declared data source; the preview renders sample.json (plugins/render.py:526-551); and the tests stop at publish or at install-record existence, never at the dashboard card (see next section).

Primary root cause statement: the Studio template declares a manual-metric widget with no data-entry path, so validation passes and install succeeds, but the runtime has nothing to read. A secondary contract bug makes one of the two widget elements impossible to satisfy even after adding data. The operational admin gate is a separate flow blocker for the publish branch.

## Why the existing tests are green

| Test | Result | What it asserts | Gap |
|------|--------|-----------------|-----|
| tests/test_studio_install.py (2 tests, docstring "create, validate, install, usable") | 2 passed | install returns 200; record exists and is not uninstalled; active dir contains widget.ui.json (:71-84) | never calls /api/dashboard; a plugin can be "installed" and unusable |
| tests/test_marketplace_fresh_desk.py::test_the_studio_blank_template_validates_and_publishes (:131-143) | passed | validate 200 ok; publish 202 pending-review | stops before approve, install, dashboard |
| tests/test_marketplace_api.py | 51 passed | admin, publish, approve, install, policy, audit edge cases | no test drives a Studio-created manual-metric plugin to a card |
| tests/test_server_publish.py | 6 passed | registry publish path | no SPA/Studio path |
| tests/test_registry_publish.py | 20 passed | registry publish_to_registry | not the marketplace Studio |
| frontend vitest marketplace-studio.test.tsx | 2 passed | sends inline manifest; widget elements use type not kind; publish request shape | does not model dashboard freshness or the manual-metric contract |

There is no test anywhere that asserts freshness == "fresh" and payload.elements non-empty for a plugin created through Studio. That is exactly the user goal, and it is the uncovered segment.

## Docs vs reality

- README.md:40 calls Studio "the create-to-publish path" and README.md:46 describes publish -> approve -> org catalog. It does not mention the personal install path or that the created widget has no data until something writes it.
- README.md:48 and docs/known-limitations.md:15-16 say admin mode is off unless the server starts with AGENTDESK_MARKETPLACE_ADMIN=1, and while off admin endpoints answer 403. The Studio UI does not repeat this: its pending panel (Studio.tsx:268-281) says only that an operator reviews it. The Admin page does explain the switch, but only after the user navigates there (Admin.tsx:208-231).
- docs/known-limitations.md:34-40 lists Studio limits (no folder import, no share, pending review only, no draft list, T1 default) but not the data gap. That missing bullet is the one that matters.
- docs/design/plugin-authoring-v2.md:92 says manual-metric emits value, target, unit, lastUpdated, history, delta; :105-111 says shipped samples must bind every element. The Studio template obeys the second sentence and violates the first.
- scripts/marketplace_walkthrough.py seeds a data.json inside the plugin source folder (line ~135) and never asserts a dashboard card. That is also not the runtime path: sources.py resolves a relative file against the workspace, not the plugin folder (sources.py:156-188).
- The prior fix 0f8d007 (Tue Nov 17 2026) fixed two real Studio blockers (kind -> type; stale registry pins) and added the validate+publish regression. The regression stops at 202, so the current break was invisible to it.

## Minimal fix plan (not implemented)

The goal: a plugin created in Studio must either show honest "setup needed" or show a fresh card after one real data step. Do not quietly render sample data as live.

P0, pick one primary contract:

Option A (recommended minimal, one release):
1. Give the manual metric a writer. In post_studio_install (api.py:1084-1133), after runtime.install (:1120), if the active widget's dataSource is manual-metric (no explicit file), write plugin-data/<id>/manual.json seeded from the validated sample's numeric bindings.value with updatedAt = now, then retest/attach so the dashboard reads it. Audit the record as "seeded-from-sample" so the value is not mistaken for a user reading. Runtime touch point: add a small helper next to runtime.install rather than mutating runtime state from the HTTP layer.
2. Make the default widget source-coherent. Change Studio.tsx:88 to bind a real manual-metric output (for example "lastUpdated") or add a third element only if the source emits it; keep note out of the template. Alternatively admit scalar passthrough in manual-metric, but that widens the data contract.
3. Add the missing validator guard in validator/lint.py: a per-source binding vocabulary table (manual-metric -> value,target,unit,history,lastUpdated,count,points,file,delta) and a failure when a widget element or sample binding is not in it. This would have caught "note" at validate time.
4. Update docs/known-limitations.md and README.md: Studio-created manual-metric plugins are seeded from the sample until edited; and note the admin switch in the Studio pending panel with a link to /marketplace/admin.

Option B (more honest, larger):
1. Add "manual-metric" as a config kind (plugins/config.py:108 today only "workbook") with a setup_flow step and a small POST endpoint writing manual.json under the plugin data dir.
2. attach returns status "setup" (execute.py:254-310) so the dashboard renders the existing wiring "Installed, not set up" card (PluginCardView.tsx:62-71) with a Set up action.
3. Add a first-party "Set value" sheet to the manage page (field, optional target/unit) using the manual-metric vocabulary.
This avoids fabricated data but touches runtime, config, setup flow and UI. Recommend A now, B as the follow-up ticket.

P1, publish branch:
1. Studio's pending panel should state that an operator must have admin mode on and link /marketplace/admin, or the admin gate should move to a real role. At minimum, the runbook and UI should agree.
2. Consider returning a non-202/queued-but-unapprovable hint when admin is off, for example a notice in the publish 202 body that approval is unavailable. Do not silently accept a submission the same desk cannot approve.

## Proposed test cases

1. tests/test_studio_install.py::test_installed_studio_plugin_has_a_fresh_dashboard_card
   - POST /api/marketplace/studio/install with the exact Studio payload.
   - GET /api/dashboard; assert the card exists, freshness == "fresh", payload.elements has the metric (and no blank text element), cause == "".
2. tests/test_studio_install.py::test_studio_install_seeds_manual_metric_from_sample
   - After install, GET /api/plugins/<id>; assert data_source state "ok" and value 0; assert plugin-data/<id>/manual.json exists.
   - POST retest; assert still fresh.
3. tests/test_validator_lint.py::test_widget_binding_must_be_emitted_by_its_data_source
   - The current Studio widget (metric/value + text/note, dataSource manual-metric) must fail with a stable code (proposed unknown-binding or bad-sample); a widget binding value/lastUpdated must pass.
4. tests/test_marketplace_studio_roundtrip.py::test_publish_approve_catalog_install_dashboard
   - monkeypatch AGENTDESK_MARKETPLACE_ADMIN=1; validate -> publish (202) -> approve (200) -> GET catalog (entry present, eligible) -> install (200) -> GET /api/dashboard (fresh, elements non-empty).
   - Same flow with the env unset: approve 403 admin:disabled and the draft stays out of the catalog (guard against regressions in the gate).
5. tests/test_marketplace_api.py: keep the existing admin gate tests; add the explicit assertion that a queued publication cannot be approved while admin is off (if not already covered at :903-977).
6. frontend/src/test/marketplace-studio.test.tsx: assert the success copy "installed and ready on the dashboard" is only shown when the follow-up dashboard state is actually fresh, or reword it to "installed; open the dashboard to check its data source". Add a vitest that renders the amber card path for freshness "attention" with payload.elements [].
7. scripts/marketplace_walkthrough.py: after install, assert the dashboard card freshness and payload.elements; fix the seeded file location to the plugin data dir (or use an absolute declared file) so the walkthrough tests the real runtime path.

Verification after the fix (not run here):

    cd "D:\20-projects\Personal Agents\agent-desk"
    python -m pytest tests/test_studio_install.py tests/test_marketplace_fresh_desk.py tests/test_validator_lint.py -q
    python -m pytest tests/test_marketplace_api.py -q
    cd frontend && npx vitest run src/test/marketplace-studio.test.tsx

## Artifacts written by a Studio install (temp harness)

- <workspace>/marketplace/studio/<id>/<version>/ : the exact validated tree (manifest.json, widget.ui.json, sample.json)
- <plugins>/<id>/<version>/ : the runtime copy; widget.ui.json present
- <plugin-data>/<id>/ : exists and is empty (this is the defect)
- <marketplace>/pending/pub-*.json and <marketplace>/pending/pub-*/plugin/ : publish queue
- <marketplace>/org/<id>/<version>/ and <marketplace>/org-catalog.json : only after approval
