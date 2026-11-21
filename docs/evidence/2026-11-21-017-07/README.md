# Evidence: spec 017 workstream 7 (unknown routes), ticket #227

Captured 2026-11-21 against this branch, from a real server booted with a
fresh temp `AGENTDESK_DATA` (no existing user data), then driven by a real
browser over the normal token exchange (`GET /auth/<token>`).

## skill-md-404-page.png

Playwright screenshot. `GET /skills/abc/skill.md` (a stale link) answers
`404 Not Found` with the not-found page: "Nothing here. No skill lives at
this address." Before the fix this address crashed with a 500.

## skill-md-404-transcript.txt

The same request with curl: status line `HTTP/1.1 404 Not Found` and the
full page body.

## wizard-unknown-action-404-page.png

Playwright screenshot. A browser form post (the no-JS path) to
`POST /wizard/wiz-missing/approve`, an address whose session no longer
exists, answers `404 Not Found` with the store's own cause: "no wizard
session wiz-missing". Before the fix this was the generic "Something
broke. Try again; if it repeats, restart the app." page.

## wizard-unknown-action-404-transcript.txt

The same form post with curl: status line `HTTP/1.1 404 Not Found` and the
full page body.
