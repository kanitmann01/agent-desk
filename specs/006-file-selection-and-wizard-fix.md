# Spec 006: Reusable file selection, visual row picking, and the Add-plugin finish line

Status: ready-for-agent (2026-11-17). Spec issue mirrors this file; the issue body is the
live copy when the two disagree.

## Problem Statement

Three connected failures around giving plugins data:

1. **The Add-plugin wizard has no finish line.** The user clicks Add plugin, describes the
   plugin, answers the questions, previews the widget, clicks "Add widget", and lands on a
   page of raw JSON (`{"status": "installed", ...}`). Nothing tells them it worked or what
   to do next. Reproduced live on 2026-11-17 against the real server: the approve step
   answers a plain form post with a 200 JSON document instead of a redirect, so the browser
   parks on `/wizard/<id>/approve` showing the raw response body.
2. **The wizard never asks which file.** The built widget's permission is a fabricated
   `reports/*.xlsx` glob. If the user's workbook lives anywhere else, the widget shows
   nothing, and nothing in the flow helped them say where their data is.
3. **There is no reusable way to point a plugin at a file and rows.** The only real
   pick-and-configure flow (Browse a workbook, see its contents, choose the columns and the
   rows to track) exists solely for one bundled plugin. Any other plugin that needs a file
   input has to reinvent it. And inside that one flow, selecting rows means ticking
   checkboxes one at a time: no select-all, no drag across rows, slow for anything wider
   than a handful of rows.

## Solution

- The wizard's approve step ends like every other step: a proper "installed" screen that
  says what was added and links straight into pointing it at the real file. JSON responses
  remain for fetch clients; plain form posts redirect.
- The per-instance setup flow behind the workbook tracker becomes a shared capability of
  the plugin runtime: any installed plugin that declares config kinds gets the same
  instances, Browse, preview, and confirm endpoints, the same granted/confirmed read gate,
  and the same per-instance cards. No plugin code changes to use it; it is a manifest
  declaration.
- The setup modal (enterprise pattern: a Browse button backed by a native file dialog on
  the server, never a typed path) shows the file's contents and lets the user pick rows
  visually: click, drag/brush across rows, shift-click ranges, select all, clear, with a
  live count of what is tracked. Column assignment (value/label) stays header-click based,
  with the existing suggestion helper one click away.

## User Stories

1. As a desk owner, when I click Add widget on the wizard preview, I want to land on a
   clear installed screen, so that I know the plugin was actually added.
2. As a desk owner, I want that screen to offer "pick the file it reads", so that I can
   point my new plugin at real data instead of a guessed folder.
3. As a desk owner, I want the wizard to keep returning JSON to programmatic clients, so
   that scripted installs keep working while form posts get pages.
4. As a desk owner, I want any plugin that needs a file to give me the same Browse button
   pattern, so that I learn one interaction and reuse it everywhere.
5. As a desk owner, I want the file dialog to open on my machine rather than typing a
   path, so that picking a file is one native action and no path ever crosses the browser.
6. As a desk owner, I want the modal to show my workbook's real rows and headers, so that
   I can see exactly what I am pointing the plugin at.
7. As a desk owner, I want to drag across rows to select a run of them, so that selecting
   twenty rows is one gesture instead of twenty clicks.
8. As a desk owner, I want shift-click to fill the range between two clicks, so that
   keyboard-style selection works too.
9. As a desk owner, I want a Select all button (and a Clear), so that tracking a whole
   sheet, or starting over, is one click.
10. As a desk owner, I want a live count of selected rows, so that I always know the size
    of what I am confirming.
11. As a desk owner, I want to click column headers to say which column is the value and
    which is the label, so that the widget shows what I mean.
12. As a desk owner, I want a Suggest button that proposes columns and rows, so that the
    common case is one confirmation instead of configuration.
13. As a desk owner, I want my selection remembered per named instance of a plugin, so
    that two trackers over the same workbook stay independent.
14. As a plugin author, I want to declare in my manifest that my plugin takes a workbook
    configuration, so that my plugin gets the whole pick-rows flow without writing UI.
15. As a plugin author, I want my config-backed plugin to show a Set up entry on the
    manage surface, so that users can configure it after install, not only from a
    dashboard card.
16. As a desk owner, I want the runtime to refuse reading a file that was never granted
    and confirmed for that instance, so that configuring one plugin cannot leak another's
    files.
17. As a desk owner, I want an explicit acceptance step before a file outside the
    workspace is used, so that pointing a plugin at an arbitrary disk path is deliberate.
18. As a desk owner without JavaScript (or with it broken), I want the wizard and its
    approval to complete with plain form posts, so that the flow never requires the SPA.
19. As an operator, I want the instance cap and its error codes to keep working for every
    config-backed plugin, so that a hundred instances cannot accumulate silently.
20. As a desk owner, I want Esc and focus handling in the selection modal, so that it
    behaves like every other dialog on the desk.

## Implementation Decisions

1. **Approve answers by client kind.** A form-encoded POST to the wizard approve action
   gets a 303 redirect back to the wizard session page, which now has an approved state
   screen: what was installed (id, version, pilot flag), the one-line summary, and a
   primary call to action that opens the file setup for the new plugin. A JSON request
   keeps today's 200 JSON contract. The describing/answer flow already redirects and is
   unchanged.
2. **The approved screen links to setup.** The handoff target is the existing per-instance
   setup entry for the just-installed plugin (create-instance then setup), so the
   fabricated default glob remains only a pre-configuration default until the user
   confirms a real file.
3. **Instance setup becomes plugin-generic.** The per-user instance store and the setup
   flow (create, pick, stage, preview, suggest, confirm, accept-outside) stop being pinned
   to one tracker plugin id. Any installed plugin whose manifest declares config kinds
   participates: the runtime exposes instance endpoints for it, the dashboard renders one
   card per instance (card key `<plugin id>~<instance id>`, same as today's tracker), and
   the marketplace manage view of a config-backed plugin lists its instances with a Set up
   action. The alias mechanism stays as-is.
4. **The manifest declaration is the only opt-in.** No plugin code, no new permission
   class. The validator keeps enforcing that config-backed plugins do not also declare a
   data source file, and that config-backed plugins stay no-LLM.
5. **File picking stays server-owned.** The native dialog keeps running on the server side
   via the injected picker; the browser sees only the file's name. Staged paths, grants,
   workspace containment, and outside-workspace acceptance behave exactly as today. The
   suffix allowlist is unchanged (xlsx/xlsm/csv).
6. **Row selection payload.** The confirm call accepts the selected row indices explicitly
   (an ordered list of zero-based data rows). Checkbox, drag/brush, shift-click, select
   all, and clear all produce the same payload; the stored tracking document records the
   selection so the widget reads exactly those rows. A confirm without a selection keeps
   today's meaning (suggested/default rows) so existing instances and tests are untouched.
7. **The selection modal is one reusable component.** Built on the desk's existing modal
   contract (scrim, dialog role, focus trap, Escape, focus restore, busy/error slots). The
   preview grid inside it is the existing preview (headers, first rows, column
   assignment), extended with the row-selection gestures. Workbook is the kind wired in
   this wave; the component's props take a generic preview so further kinds can reuse it.
8. **Setup reachable from two surfaces.** The dashboard instance card (existing) and the
   marketplace manage view (new) both open the same modal flow against the same
   endpoints.
9. **Error vocabulary unchanged.** Existing config error codes and the HTTP envelope
   (`{error, message, details}`) carry over; no new codes except, if needed, one for a
   confirm whose selected rows fall outside the previewed file, which must reuse the
   stale-config semantics rather than invent a new failure shape.

## Testing Decisions

- **What a good test is:** external behavior only. HTTP status codes, redirect targets,
  rendered page text, and the JSON the SPA consumes. No internal method calls, no
  asserting on private helpers.
- **Seam 1, backend wizard:** the real server through the test harness with an inert
  wizard store and a stub compiler, exactly like the existing wizard HTTP tests. Form-post
  approve must 303 to the session page; the fetched page shows the approved screen; JSON
  approve stays 200 with the install document. Prior art: the existing wizard API tests.
- **Seam 2, backend instances:** the real server with the real bundled workbook plugin
  installed and an injected fake picker that returns a fixture workbook path; assert the
  pick/stage/preview/confirm chain for a config-backed plugin that is not the historical
  tracker id, and that the granted/confirmed read gate still refuses ungranted reads.
  Prior art: the existing setup HTTP tests.
- **Seam 3, frontend modal:** component tests with the testing-library user event model
  for the selection gestures (click, drag across rows, shift-click, select all, clear,
  count), column assignment, and the confirm payload; plus the modal contract (Escape,
  focus restore). Prior art: the marketplace admin and sheet component tests.
- The SPA dev-proxy scan keeps enforcing that any backend path the modal calls is proxied
  in dev; the committed SPA bundle is rebuilt and committed with the change.

## Out of Scope

- LLM-tailored wizard questions (unchanged; the endpoint-configured path is untouched).
- Row selection for kinds other than workbook (the modal is generic; wiring csv/markdown
  preview is follow-up work).
- Editing cell values, writing to workbooks, or uploading files through the browser.
- The marketplace discovery redesign and the enterprise governance wave (separate
  initiative, plan already on file).
- Changing the built-in widget vocabulary, plugin classes, or permission model.

## Further Notes

- **Testing seam decision is the open veto point:** the existing-seams cut (harness HTTP
  tests + component tests, no new seam) is what the tickets below assume. A dedicated
  picker-service seam was considered and rejected as a second abstraction for what is
  already one flow; veto here before the backend ticket starts if that is wrong.
- The approve dead-end was reproduced live on 2026-11-17 (real server, real browser):
  form-post approve returns 200 JSON and the browser shows the raw document. The answer
  step, by contrast, already redirects; the fix mirrors that.
- The wizard's default `reports/*.xlsx` permission is deliberately kept as the
  pre-configuration default (validator still requires a permitted glob); the approved
  screen's setup handoff is what makes it a default rather than a dead end.
