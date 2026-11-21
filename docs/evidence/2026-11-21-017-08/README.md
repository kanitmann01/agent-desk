# Evidence: spec 017 workstream 8 (naming and copy), ticket #228

Captured 2026-11-21 against this branch, from a real server booted with a
fresh temp `AGENTDESK_DATA` (no existing user data), driven by curl and a
real browser over the normal token exchange (`GET /auth/<token>`).

## startup-line.txt

The server's startup line, previously "Nexuus Bot is running", now names
the product: "Agent Desk is running: http://127.0.0.1:8901/auth/...".

## 401-gate-agent-desk.png

Playwright screenshot of the session gate's refusal (an unauthenticated
`GET /`). The copy told Priya to open a product that did not exist
("Open Nexuus Bot from its shortcut"); it now says "Open Agent Desk from
its shortcut to get a fresh link."

## plugin-action-notice-transcript.txt

A no-JS plugin action (8b): curl POSTs the share action for a plugin id
that does not exist, the answer is the 303 to `/plugins?notice=...`, a GET
of that address 302s to `/marketplace/installed?notice=...` (the query no
longer drops), and the landing page (the committed SPA shell) renders the
named refusal server-side, visible with JavaScript off:
`<div class="alert" role="status" ...><p>no installed plugin
no-such-plugin</p></div>`. Before the fix the notice died in the double
redirect and the landing page carried no sentence at all.

## wizard-free-text-accessible-name.txt

The wizard questions state as the server renders it (8c), one question
carrying no options: the free-text fallback input now carries
`aria-label="Which workbook column holds the number?"`, the question text
it sits under. Before the fix the input had no accessible name.
