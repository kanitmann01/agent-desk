# Agent Desk

A no-code personal agent for a locked-down corporate Windows laptop. One double-click opens a local web dashboard: what changed in the sales file overnight, today's key commitment broken into subtasks, a research panel, and plugins described in plain English that the agent builds, previews, and installs after one consolidated approval. No admin rights, no terminal, no data leaving the machine except derived abstractions sent to the corporate LLM endpoint.

Status: the walking skeleton is built (#2 probe, #8 validator CLI, #3 dashboard shell). The widget, registry and wizard tickets are next. The canonical spec lives in this repo's issue tracker (issue #1, labeled `ready-for-agent`).

## Start it

Double-click `tools/agent-desk.cmd`. It finds Python (falling back through `py`, then `uv` with the Windows trust store), starts the dashboard windowless, and opens your browser at a one-time start link that becomes your session cookie. No admin rights, no terminal. The server binds 127.0.0.1 only.

From a terminal instead: `python -m agentdesk.server` (add `--no-browser` to skip the browser open).

## Where things are

- `docs/research.md`: the full architecture research (v2, post-audit hardened). Licenses, plugin architecture, enterprise Windows mechanics, landscape. The binding decisions are in its section A9.
- `docs/PRD.md`: product requirements: personas, surfaces, the action inventory with reversibility, reachable-state matrix, phasing.
- `docs/design-language.md`: the visual contract (tokens, type, spacing, anti-slop commitments) every build consumes.
- `docs/design/dashboard.html`: the high-fidelity mockup; open it in any browser.
- `specs/`: snapshot of the spec body as published to the tracker. The issue is canonical; this file is convenience.
- `src/agentdesk/probe/`: the P0 environment probe (issue #2), run via `tools/probe.cmd`.
- `src/agentdesk/validator/`: the plugin validator CLI (issue #8), byte-identical to registry CI.
- `src/agentdesk/server/`: the hardened localhost web app (issue #3): token bootstrap, Origin/Host guard, dashboard shell, health.
- `tools/agent-desk.cmd`: the double-click launcher.

## Ground rules for anything built here

- Permissive licenses only: MIT, Apache-2.0, BSD, ISC. No copyleft, no SSPL/BSL/fair-code, no restricted licenses. Upstream LICENSE/NOTICE files ship inside the install folder.
- Class D plugins only: manifests and declarative UI schemas. The compiler never emits executable code.
- The local server binds 127.0.0.1 only, authenticates every request, and validates Origin/Host.
- No autostart persistence until Security signs off in writing.
- The UI is the log: every widget shows freshness, and failure is a designed, visible state.
