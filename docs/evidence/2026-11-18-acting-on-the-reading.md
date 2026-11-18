# Evidence: the desk acts on what it read (spec 010)

Recorded 2026-11-18 on branch `feature/coupled-intelligence`. Every claim below
was produced by a command on this checkout, not by a ticket's self-report.

## What shipped

- **Receipts on every reading (issue #137).** `InsightReading` carries `used`,
  `inputs` and `memory_notes`; `service.attach_cards` writes
  `payload["insight"]["receipts"] = {"preferences": [...], "inputs": [...]}`,
  filtered through `preferences.FIELDS` and `service.INPUT_NAMES`, and only adds
  `counts` when `memory` is a declared input with a positive `memory_notes`.
  Each family declares only what changed its own sentence: digest recomputes its
  skeleton with a key reset to its default and declares the key only when the text
  moves; calendar declares `prepMinutes` whenever it is off 15, including 0;
  workbook declares `chart` only when the stored chart is not `auto`; research
  declares none. The server-rendered card prints the same line in four forms:
  "Used: <preferences> · <inputs>.", "Used the defaults; read only this card's
  rows.", "Used the defaults; read <a> and <b>.", and nothing at all when the
  reading read nothing.

- **The press resolves its thread (issue #138).** A flat `subject`+`sender` on
  `POST /api/insight/draft` resolves by exact normalised subject (root, subject,
  or reply subject) and by sender header, display name or address. One match
  answers `thread: {"id", "to", "subject"}`; none refuses 404 naming the subject;
  two refuse 409 naming both senders; mail off, unconfigured or unreadable refuse
  503 with the existing copy. A press that nests its facts under `thread` — the
  card's own payload — still drafts with mail off, which is why resolution reads
  the flat fields only.

- **A drafted reply is staged, never sent (issue #139).** `stage: true` on a
  resolved press adds exactly one inbox suggestion card with
  `meta: {"mailDraft": {"messageId", "to", "subject", "thread"}}` — the shape
  `_write_mail_reply` already accepts — and an origin that says "Drafted by the
  model" or "Skeleton, not a model draft". Acceptance writes the `.eml` through
  the one existing outbox writer; `insight/press.py` never writes it. A repeat
  press with the same thread and text answers `staged: false` with the existing
  card id; edited text stages a second card. Press and staging are audited with
  the thread id and no message content.

- **The server-rendered card can be pressed (issue #140).** A card carrying
  `insight.press` renders `<form method="post" action="/insight/press">` with
  escaped hidden `kind`, `text`, `subject`, `sender`, `last`, `pluginId`,
  `instanceId` and the press's own label. The page shows the disclosure lines,
  then the explanation or draft, then one stage form when a thread resolved, or
  the refusal sentence verbatim. No script, no CSP change.

- **The SPA draws and presses (issues #141, #142).** TrackerCard renders
  `payload.elements` through the exported `ElementView`, then the receipt line,
  then the press; a card without a reading is unchanged. The press button posts
  the same request, shows the server's refusal verbatim, shows the disclosure
  before any stage action, and confirms staging with the card id.

## Gate truth

- `tools/ci_local.py` (with `NODE_ENV=test` and git on PATH):
  **4/6 gates passed in 406 s** — py-grammar 302 files, frontend-check exit 0,
  frontend-tests 272 passed, licenses clean; **pytest 13 failed, 2492 passed,
  1 skipped**, **registry-ci REGISTRY-CI FAILED (2)**.
- Both failing gates are pre-existing drift, not this branch. A detached worktree
  at base `daaa8d6` fails the same registry set with identical counts
  (16 failed, 71 passed, 6 errors on the seven registry/auth/ui files), and
  `tools/registry_ci.py --registry registry --plugins registry/plugins/waiting-on-you`
  answers `FAIL registry-ci:hash-mismatch:waiting-on-you@0.1.0` twice at base and
  at HEAD. The 13 pytest failures are the content-pin drift already recorded in
  spec 009's ticket 06; the branch adds **57 passing tests** and removes none.
- `tools/ci_local.py` itself has a defect worth fixing separately: it appends
  `--plugins <one path>` once per plugin, and argparse keeps only the last value,
  so the registry gate checks `waiting-on-you` alone. Fixed, the gate would check
  all six plugins; it is not fixed here because that is outside this spec and the
  gate is already red for the drift above.
- This machine exports `NODE_ENV=production`. Vitest then loads React's
  production build and every render test throws `React.act is not a function`;
  `NODE_ENV=test` is required locally and is what the numbers above use. The CI
  runner does not export it.

## What did not land

- `PreferenceStore.reset()` exists and is unused: the settings card has a save
  path and no reset action, so clearing a preference means emptying its field.
- A staged press is not notified through `_evaluate_inbox` on the JSON route
  (the route is a scriptless page and the page calls it); a JSON caller that
  stages gets the card in the inbox but no badge refresh.
- The press is one button per card. Nothing batches a workbook explanation and a
  digest draft, and nothing remembers which press was refused last.

## Routed risks

- **Staging posts no card identity.** The SPA sends `kind/text/subject/sender`
  (+ `stage`); the server form also sends `pluginId`/`instanceId`. Staging needs
  neither, so the contract is deliberately narrower on the SPA side.
- **A page press stages a reply whose subject is the reply subject** (`Re: ...`).
  Resolution accepts both spellings; a future subject-only lookup must keep doing
  so.
- **The receipt line prints on every card that carries a reading**, not the
  workbook card alone, because the line describes the reading, not the plugin.
