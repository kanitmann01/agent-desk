# TODO: executive demo, 2026-11-18

Opened: 2026-11-17. Expires: **2026-11-19**.

If today is after 2026-11-19 and docs/demo/2026-11-18-evp.md exists, this file is
history: delete it. Do not start work from it. The durable record is
specs/007-real-data-audit-and-settings.md and docs/tickets/2026-11-17/.

## Objective

An end-to-end browser demo for the EVP on 2026-11-18: browse a real Excel or JSON file,
pick the rows to track, get one model opinion on the choice, accept or decline it, confirm,
and see the tracker card read the file's real numbers. One rail, one settings home, one
audit trail; every surface the demo touches proven in a real browser.

## Acceptance

- [x] T1 JSON previews and tracks (docs/tickets/2026-11-17/T01.md)
- [x] T2 The model reviews the user's own choice (T02)
- [x] T3 Tracker card names its file, rows, and freshness (T03)
- [x] T4 Peers off the rail; Activity and Capabilities under Settings (T04)
- [x] T5 One audit trail behind Settings > Activity (T05)
- [x] T6 One settings card + browser sweep with evidence (T06)
- [x] docs/demo/2026-11-18-evp.md written with screenshots and a pass/fail table
- [ ] python tools/ci_local.py green

## Verification on 2026-11-17

- pytest full suite: 2148 passed, 14 failed, 1 skipped. One failure was mine
  (the trimmed endpoint hint lost the Anthropic URL and the clear-key sentence);
  the copy is restored and the affected files pass 58/58. The remaining 13 are
  the pre-existing bundled-registry pin drift in issue #115 (deferred by Ken), so
  ci_local is **not** green and cannot be claimed green until #115 lands.
- Frontend: tsc --noEmit clean; vitest 21 files / 242 tests passed.
- Browser: 11 paths at 1280 and 1600 px return 200, render the seven-link rail,
  have no horizontal overflow and log no console errors. Audit kind filter shows
  model calls and hides the questions table.
- Live tracker: Q4 pipeline, 881,000 USD, 6 rows, read just now, no SAMPLE stamp.

## Notes

- The demo uses the real data dir; the sample switch must be off on demo day and does not
  need deleting, only documenting.
- Local Python is 3.14.5; the declared floor is 3.10 and CI pins 3.12. Do not use syntax
  newer than 3.10.
