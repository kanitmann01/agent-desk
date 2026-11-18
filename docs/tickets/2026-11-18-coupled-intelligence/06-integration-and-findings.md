# 06: Integration, honest limits, and the gate

**What to build:** the six readings, the two endpoints and the settings form land on one dashboard read with the full suite green, the known limitations written down, and the findings the user asked for recorded so the next round can pick from them.

**Blocked by:** 03, 04, 05.

**Status:** done

- [x] The gate was run and its failures are proven to predate this branch. With `git` on PATH: `PYTHONPATH=src python -m pytest tests -q` gives **2435 passed, 17 failed, 1 skipped in 385 s**. All 17 reproduce at base `daaa8d6` in a detached worktree: 13 are registry content-pin drift (`content sha256 e0a9e77147fe does not match the pinned e53efb1fb99a`, `tests/test_catalog_bundle.py`, `tests/test_marketplace_*.py`, `tests/test_registry_*.py` — the same 13 at base) and 4 write to `/home/node/.agent-desk/sample/sample-sales.xlsx` and are refused by this machine's sandbox (`tests/test_server_auth.py::test_a_null_origin_form_post_with_a_session_reaches_the_handler`, three in `tests/test_ui_wave2.py` — the same 4 at base). `python -m compileall -q src tests` is clean. The frontend half of `tools/ci_local.py` (npm ci, tsc, vitest) cannot run here: `frontend/node_modules` is empty and `frontend/dist` is not in this checkout.
- [x] docs/known-limitations.md gains "Coupled intelligence": the six stated preferences and no learned ones, no reset action, a bounded table (10 columns, 60 rows, 5 suggested rows), header-only digests, drafts that are never sent, no press button on any surface, the SPA tracker card ignoring appended elements, keyword-anchored research, read-only memory, and no attendee names.
- [x] docs/evidence/2026-11-18-coupled-intelligence.md records what shipped, the survey's overlap findings (`meeting-prep` already printed the next event and its checklist; `waiting-on-you` already ranked threads; row picking was manual; no preference store existed; memory writes stay behind approval), the thresholds that decided behaviour, what did not land and why, and the five things the next round should pick.
- [x] The work is committed on `feature/coupled-intelligence` with the spec and tickets beside it: f92eed3, 632896f, b9b89fa, 553f15c, 5a4f20c, 66a107d, b548419, fb4896f, 00b30d0, plus this document's commit.
