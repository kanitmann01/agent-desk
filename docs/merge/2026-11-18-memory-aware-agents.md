# Merge record: memory-aware agents (spec 012), 2026-11-18

**Branch:** `feat/agents-memory` (worktree `.worktrees/agents-memory`)
**Spec:** 012, issue #167; tickets #168, #169, #170, #171, #172, #173
**Base:** `main` at `1ecf0f5`, merged forward to `145bc5f` before push
**Gates:** `python tools/ci_local.py` on the final merged tree: 6/6 PASS
(py-grammar, pytest 2588 passed + 1 skipped, tsc clean, vitest 283,
licenses, registry-ci)

## What shipped

- **The agents package** (`src/agentdesk/agents/`): a registry of agent
  kinds, a runs store (SQLite, hermetic inert default in the harness),
  and a runner that owns the memory integration once for every kind:
  per-run hybrid recall through the store's own ranking, the bounded
  facts block from `memory/service` (5 facts / 500 chars, whole facts),
  one endpoint call through the effective BYOK client, honest degraded
  states with the pinned causes, and a receipt recording exactly which
  facts shaped the run (#168).
- **The `/agents` surface**: a server-rendered, no-JS page (roster, run
  forms, history with artifacts, receipts, feedback forms), routes for
  run and feedback, `agents.run` / `agents.feedback` audit rows, and the
  SPA rail link with a rebuilt bundle (#168, #172).
- **Feedback becomes memory** (#170): run feedback is stored on the run
  and offered to the memory loop on a new `agents` capture channel
  (`memory_capture_agents`, default on, listed by the memory page's
  capture surface with no client change). Review cards by default;
  acceptance stores the fact; the next run's receipt lists it. Pinned by
  an end-to-end HTTP test: run, feedback, card, accept, recall.
- **A second agent proves the layer generic** (#171): the worksheet-brief
  kind joined as a registry entry only (no runner/route/memory change),
  grounded in the live workbook status.
- **Skills recall too** (#169): the saved-ask runner gains the same
  bounded facts block through the assistant's own helper.
- **The mock BYOK endpoint** (`tools/mock_endpoint.py`) and the browser
  walkthrough evidence (#173): seven screenshots under
  `docs/evidence/2026-11-18-agents-memory/`, including the second run
  whose receipt lists the stored manager preference and whose artifact
  carries it. The evidence names the mock as the model double.

## Pre-existing failures fixed on the way (user directive)

- The docstring gate failed on clean main (65 gaps, 2 stale baseline
  lines): documented for real across `insight/*`, uploads and the
  frontend; the baseline only lost stale lines.
- Two flaky `test_server_mail_api` tests: a real race (fire-and-forget
  first poll, unsynchronized poll dedupe) fixed by serializing polls and
  running the toggle's first poll inside its response; plus a test-env
  leak where CLI wiring tests loaded the developer's real
  `~/.agent-desk/config.env` into the suite.

## Review pass and its outcomes

The binding code-review pass flagged one blocker, one major, two minors:

- *Blocker (SPA press body assembly)*: verified as pre-existing on the
  branch base and already tracked as issue #166; fixed on main by
  PRs #175/#176/#178. This branch merges that fix forward; its own
  PluginCardView diff was docstrings only.
- *Major (em dashes)*: verified as pre-existing from main's own docstring
  batch (present in the merge base, absent from this branch's added
  lines; new main has since cleaned the named files). Nothing to do here.
- *Minor (multi-line fact receipt)*: fixed; a fact whose text spans lines
  now earns its receipt, pinned by a unit test.
- *Minor (mock endpoint host flag)*: fixed; the mock refuses to bind
  anything but loopback, the same rule as the desk itself.

## Merge notes

Main advanced from `1ecf0f5` to `145bc5f` during this work. The branch
merged main forward: insight conflicts resolved toward main's press-shape
rewrites, the bundle rebuilt from the merged frontend source, and the
docstring baseline regenerated (0 lines added, 14 stale lines removed).
