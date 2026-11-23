# Presentation tools: an agent-facing deck plugin

Date: 2026-11-23
Repo: kanitmann01/agent-desk-core
Branch: feat/presentation-tools (from main)
Spec: specs/021-presentation-tools.md. This closes the presentation item in
wayfinder ticket #276.

## The problem

The desk could write a deck only through one path: the /agents form, an LLM
endpoint, one plan pass, one fill pass, then deliver_deck. There was no way for
an agent or a script to ask for an outline, write a deck from its own content,
read a deck back, or render previews. The presentation-starter plugin shipped
a template and a prose guide, but no callable tools.

That is the "tools that do nothing" complaint in miniature: a plugin that looks
installed but contributes no action an agent can take.

## What shipped

A declared tool surface. The plugin declares four tools in
`contributes.tools`; the host owns the schemas and executes them. No plugin
code runs.

| Tool | Input | Returns |
| --- | --- | --- |
| presentation_outline | brief, template, recipe | slide text, template metadata |
| presentation_create | brief or outline, template, recipe, variant, render | .pptx, slide count, fit notes, optional preview |
| presentation_inspect | file | slide text, notes, package problems, ok |
| presentation_render | file | renderer, pdf, images, note |

Tool ids use underscores (presentation_create, not presentation.create) because
the function-calling name rules in common harnesses do not allow dots.

Two ways to call them:

- HTTP: `GET /api/presentation/tools` for live schemas,
  `POST /api/presentation/tools` with `{"tool": "presentation_create", ...}`.
  Files come back with a `url`, `pdfUrl` and `imageUrls` under
  `/presentations/files/`.
- CLI: `python -m agentdesk.presentations.cli list|outline|create|inspect|render`.

Both are documented on the deck tools panel on /agents and in
`registry/plugins/presentation-starter/guidance/SKILL.md`.

## Why the host executes, not the plugin

A marketplace plugin is declarative (`class: declarative`, shell none). Running
plugin code would turn every template install into arbitrary code execution.
Instead the manifest says which host tool names it contributes, and
`tool_catalog()` exposes only names the host knows. `run_tool()` refuses a tool
that no shipped or installed pack declares, so the catalog cannot outrun the
pack that contributes it.

The plugin still owns the template, variants, recipes, thumbnails and guidance.
The host owns the operations. That keeps the trust model unchanged: installing
a pack grants no new executable surface beyond the four allowlisted operations.

## Safety boundaries

- Session gate and Origin/Host guard apply to every tool route like every other
  desk page. The known opaque-Origin behaviour is unchanged (spec 020).
- Input schemas are host-owned with `additionalProperties: false`; unknown
  fields are a 400, not silently ignored.
- File paths are resolved inside the presentation root only. Absolute paths,
  drive letters, `..`, and non-.pptx/.pdf/.png suffixes are refused.
- Produced decks are checked with `package_problems()` before the call returns
  success. A broken package is a 422 and writes no artifact.
- No model endpoint, network call or plugin code is needed for any tool.
- Body limit stays the server's 1 MiB JSON limit.

## Verification

- `python -m pytest -q tests/test_presentation_tools.py tests/test_server_presentation_tools.py tests/test_presentation_cli.py` -> 30 passed.
- Route table, tool, CLI and docstring gate slice after the frozen-list pin ->
  45 passed.
- Validator, pack, catalog and fresh-desk suite -> 62 passed.
- Presentation, catalog and agents server suite -> 91 passed, 1 skipped.
- Server and plugin regression slice -> 115 passed (the socket-shutdown warnings are pre-existing).
- Full `python -m pytest -q` -> 3112 passed, 2 skipped in 623.35s.
- Manual smoke: outline -> create -> inspect produced a 25,874-byte deck with
  11 slides, `ok=True`; CLI list/create/inspect worked with `PYTHONPATH=src`.
  `cli list` reports the four tools beside the starter template.
- Registry consistency: `scripts/sync_registry.py` and
  `scripts/build_catalog.py` were rerun after the manifest change; the
  committed catalog and index pins match.

## What changed

New:
- `src/agentdesk/presentations/tools.py`
- `src/agentdesk/presentations/cli.py`
- `specs/021-presentation-tools.md`
- `docs/evidence/ponytail-audit-2026-11-23/presentation-tools-2026-11-23.md`
- `tests/test_presentation_tools.py`
- `tests/test_server_presentation_tools.py`
- `tests/test_presentation_cli.py`

Edited:
- `registry/plugins/presentation-starter/manifest.json`
- `registry/plugins/presentation-starter/guidance/SKILL.md`
- `registry/index.json`
- `src/agentdesk/marketplace/bundled-catalog.json`
- `src/agentdesk/server/app.py`
- `src/agentdesk/server/routes.py`
- `src/agentdesk/server/agents_view.py`

## Not checked

- No LibreOffice or PowerPoint run in this environment. `presentation_render`
  was tested through its "renderer: none" path; the real renderer path is
  unchanged from the existing run flow.
- The marketplace plugin detail page does not yet list `contributes.tools`.
  The tools are visible on /agents and through the catalog endpoint.
- Hermes cannot call the HTTP tools yet. That waits for the enterprise
  connector work in #276; today a local script or agent with the session cookie
  can call them.
- No frontend change, so no browser evidence beyond the existing deck tools
  panel text. The panel is static HTML with no script.
- Cuts from the audit are out of scope here and stay with #275.

## Follow-ups

- Validate `contributes.tools` in the plugin linter, so a malformed declaration
  is caught at install instead of being ignored by discovery.
- Show declared tools on the marketplace plugin detail page.
- Add a token-scoped tool route for Hermes so the connector does not need a
  browser session.
- Decide whether an installed pack's tools should be disabled when the plugin
  is disabled. Today discovery scans the registry and user template roots, not
  the installed-plugin state.
- Marketplace installs land under the data dir's `plugins/` tree, which
  `load_packs()` does not scan. A third-party presentation pack installed from
  the marketplace is therefore not discovered yet; only the bundled pack and
  packs under the user template root are. The bundled starter works today.
