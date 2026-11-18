# TODO: plugin truth and Outlook demo, 2026-11-18

Opened: 2026-11-18. Expires: **2026-11-20**.

If today is after 2026-11-20 and docs/demo/2026-11-18-plugins.md exists, this
file is history: delete it. Do not start work from it. The durable record is
specs/008-plugin-truth-and-outlook-brief.md and docs/tickets/2026-11-18/.

## Objective

Make plugin installs true again, finish plugin creation end to end in the Studio,
and ship an Outlook Brief that works without a connector: digest, most important
email and reply starters inside the plugin card, built from exported .eml headers.

## Acceptance

- [x] T1 Every local registry pin matches its plugin tree (#115 fixed)
- [x] T2 Studio creates, validates and installs a plugin on this desk (T02)
- [x] T3 Outlook brief ranks headers, finds the top message, suggests replies (T03)
- [x] T4 Outlook Brief 0.3.0, demo inbox and export helper (T04)
- [x] T5 Browser proof and docs/demo/2026-11-18-plugins.md (T05)
- [x] python tools/ci_local.py green

## Verification on 2026-11-18

- Full pytest: 2224 passed, 1 skipped in 404.96s. The 13 issue #115 failures are
  gone after re-pinning all 25 local plugin trees and rebuilding the catalog.
- Registry/catalog/walkthrough tests: 36 passed.
- Studio install: 2 passed, including a seeded manual.json and a fresh stored
  source status after install. Runtime restart rebind: 10 passed.
- Outlook brief: mail/execute/watcher 59 passed; plugin family and policy 43 passed.
- Frontend: tsc --noEmit clean; vitest 22 files / 262 tests passed.
- Local CI: 6/6 gates passed in 419s, including pytest 2224 passed, 1 skipped.
- Demo inbox: demo/outlook-inbox/README.md documents the six header-only files and
  the export command.
- Browser: Dashboard, Studio and Installed have 0 console errors. Outlook Brief
  card shows 5 messages, the Q4 top email, three threads and three starters.
  Studio plugin installs to a live dashboard card with value 0 and a timestamp.
- Known limits: Outlook export needs an Outlook profile; headers only; starters
  are suggestions, not sent mail; marketplace publication still needs admin.

## Notes

- The demo desk is isolated at
  C:\Users\mannk\AppData\Local\Temp\agentdesk-plugins-2026-11-18.
- registry/plugins/outlook-digest is 0.3.0; index 0.2.0 is kept as tag
  outlook-digest-0.2.0 (local tag, not pushed).
- Local Python is 3.14.5; the declared floor is 3.10 and CI pins 3.12. Do not
  use syntax newer than 3.10.
