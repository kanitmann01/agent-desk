# Evidence: 017-04 memory bookkeeping (ticket #222)

Date: 2026-11-21. Real servers over fresh temp `AGENTDESK_DATA` dirs,
driven over HTTP the way the SPA drives them; no LLM endpoint involved
(consolidated observations are the rules' deterministic text).

- `01-merge-survivor-observation.png` (spec 017, 4b): the memory page
  after merging Globex into Acme through `POST /memory/entities/merge`.
  Both entities carried a consolidated observation before the merge
  ("2 facts about Acme", "2 facts about Globex"); after it the page
  lists exactly one observation, "4 facts about Acme. Latest, Nov 21:
  Globex opened the Berlin office. ...", and no orphaned Globex text
  remains anywhere on the page.
- `02-undo-refuses-id-reuse.txt` (4a): a removal that deletes the
  highest entity id, a new fact whose entity reuses that id inside the
  undo window, and `POST /api/memory/undo` answering 409 with "Memory
  changed since the removal, so it can no longer be undone." instead of
  wiring the restored Beta edges onto Delta Corp.
- `03-corrupt-key-locked-banner.txt` (4d): a bank sealed through the
  page's encrypt action, the server stopped, `memory.key` replaced with
  9 junk bytes, and a fresh server start on the same data dir. The
  locked banner and every memory action name "the key file exists but
  is not a valid key: <path>", not "missing".
