# Spec 021: Agent-callable presentation tools

Status: implemented (2026-11-23) on `feat/presentation-tools`.
Related wayfinder ticket: #276 (Hermes and custom connectors). The tool
surface is the local half; a token-scoped connector route is still open.

## Problem Statement

The desk can produce a deck only through the /agents form: a person fills
the brief, the server needs a BYOK endpoint, the model plans the slides,
a second model pass fills them, and the run writes a file. That path is
fine for a person at the desk. It is not a tool.

An agent integrating with the desk has no way to ask for an outline, write
a deck from its own content, read a deck back, or render previews. The
presentation-starter plugin ships a template, three recipes and a prose
guide, but contributes no callable action. It looks installed and does
nothing an agent can invoke, which is the failure the 2026-11-23 audit
named.

Major harnesses ship deck tools as a small set of operations an agent
drives step by step. The desk should offer the same without turning a
declarative plugin into executable code.

## Solution

A host-implemented, allowlisted tool surface. A plugin declares which
host operations it offers under `contributes.tools`; the host owns the
schema, the validation and the files. Plugin code is never executed.

Four operations:

| Tool | Input | Returns |
| --- | --- | --- |
| `presentation_outline` | brief, optional template and recipe | slide text, template metadata |
| `presentation_create` | brief or outline, optional template, recipe, variant, render | .pptx, slide count, fit notes, optional preview |
| `presentation_inspect` | file | slide text, notes, package problems, ok |
| `presentation_render` | file | renderer, pdf, images, note |

Tool ids use underscores because the function-calling name rules in
common harnesses do not allow dots.

Two surfaces:

- HTTP: `GET /api/presentation/tools` for the live catalog,
  `POST /api/presentation/tools` with `{"tool": "...", ...}`.
  Files are served from `/presentations/files/`.
- CLI: `python -m agentdesk.presentations.cli list|outline|create|inspect|render`.

Both surfaces need no model endpoint for the file work. `outline_for`
and `write_deck` are deterministic; the LLM plan pass stays on the
existing /agents form.

## User Stories

1. As an agent with a one-line brief, I want an outline in JSON, so I can
   revise the slide text before writing a file.
2. As an agent with my own slide text, I want to create a valid .pptx
   from an outline, so I do not have to build OOXML or drive PowerPoint.
3. As an agent handing a deck to a person, I want to read the deck back
   as slide text and package problems, so I can check it before handover.
4. As a person reviewing a deck, I want a PDF and slide images when a
   renderer is installed, so I can see the result without opening
   PowerPoint.
5. As a plugin author, I want to declare that my pack offers a host tool,
   so my template and its tools appear together without shipping code.
6. As a security reviewer, I want every path confined to the
   presentation folder and every plugin inert, so installing a pack does
   not grant executable surface.
7. As a person on the /agents page, I want the tools and their CLI
   command named beside the form, so the feature is discoverable without
   reading source.

## Acceptance Criteria

- `GET /api/presentation/tools` lists only tools declared by an installed
  pack, with host-owned JSON schemas and `additionalProperties: false`.
- `POST /api/presentation/tools` runs a declared tool and returns JSON;
  an unknown tool, an undeclared tool and an unknown field are 404/404/400.
- `presentation_create` writes a valid package or fails with 422 and
  writes no artifact.
- `presentation_inspect` returns slide text, notes, problems and `ok`;
  a missing deck is 404 and a broken package is 422.
- Every file path is relative to the presentation root; absolute paths,
  drive letters, `..`, and suffixes outside .pptx/.pdf/.png are refused.
- `GET /presentations/files/` serves only files under that root and only
  through the session gate.
- The CLI prints JSON for every command and exits 2 on a refusal.
- The plugin manifest declares the four tool ids and its digest is synced
  in `registry/index.json` and the bundled catalog.
- `tests/test_presentation_tools.py`, `tests/test_server_presentation_tools.py`
  and `tests/test_presentation_cli.py` cover the contract.
- The docstring gate passes on the new modules.

## Out of Scope

- Editing an existing deck. The tools create, read and render; they do
  not change a package in place.
- A marketplace plugin-detail list of contributed tools. The tools are
  visible on /agents and in the catalog endpoint.
- A token-scoped route for Hermes. Today an agent on the same machine
  uses the CLI; the HTTP route needs the browser session.
- Discovering packs installed by the marketplace under the data dir.
  `load_packs()` scans the checkout registry and the user template root;
  the bundled starter works today.
- Testing a real PowerPoint or LibreOffice render. The "renderer: none"
  path is tested; the renderer path is unchanged from the existing run
  flow.

## Evidence

`docs/evidence/ponytail-audit-2026-11-23/presentation-tools-2026-11-23.md`
