# Spec 008: Installable plugins, end-to-end creation, and an Outlook brief without a connector

Status: ready-for-agent (2026-11-18). Target: working demo the same day.
Tickets live in docs/tickets/2026-11-18/.

## Problem Statement

1. **Installing a plugin is broken.** 24 of the 25 local-release pins in
   registry/index.json do not match the plugin trees the registry ships. The
   marketplace offers Outlook Digest, Excel Report and the rest, then install fails
   with a hash mismatch before any card appears. The same drift made issue #115 red.
2. **Publishing a plugin is not end to end.** The Studio can build a sample and
   validate it, but the path from "created here" to "listed in Marketplace" to
   "installed on this desk" has not been walked in one run, so no one knows which
   step is missing.
3. **Outlook has no connector.** The Outlook Digest plugin declares a mail-digest
   data source and the host reads an .eml folder, but nothing creates that folder,
   nothing explains how mail gets there, and a machine with Outlook installed but no
   configured profile shows an empty card. The demo cannot open Outlook and install
   a connector.
4. **The Outlook card is a stub.** It shows a message count, a top-sender list and a
   scope line. It does not show a digest of what needs attention, the one message
   that matters most, or a reply the user could start from. The ask is explicit:
   those three live inside the plugin, not on the home dashboard.
5. **Nothing proves the plugin path in a browser.** Tests install from a fixture,
   but no run drives Marketplace -> Install -> card -> real .eml data and records
   the evidence.

## Solution

One browser session that installs the Outlook Brief from the Marketplace, points it
at a folder of exported .eml files, and shows a digest, the most important message,
and three reply starters inside the plugin card. The same session publishes a
minimal plugin from the Studio and installs it, proving creation is end to end.

- **G1 Install truth.** Every local release pin in registry/index.json equals the
  SHA-256 tree digest of the plugin directory; the bundled catalog is rebuilt from
  those pins. Installing each bundled plugin into a throwaway desk succeeds, and a
  test fails when a pin drifts.
- **G2 Creation end to end.** Studio: name -> sample JSON -> validate -> publish ->
  appears in the catalog -> installs -> renders the sample -> binds live data. The
  trace names every hop and the fix closes the broken one.
- **G3 No-connector Outlook input.** A folder of .eml files is the connector. A
  helper script exports a local Outlook profile to that folder through COM when a
  profile exists; when it does not, a checked-in mock inbox provides the same shape
  for the demo. The app never needs Graph, IMAP, OAuth, or a tenant admin.
- **G4 Outlook Brief plugin.** New declarative data source outlook-brief reads the
  configured mail folder and binds: active-thread digest rows, the most important
  message (subject, sender, age, why), and three reply starters. The plugin manifest
  carries all three as render elements; the home dashboard gets no new card.
- **G5 Honest states.** No folder -> amber copy naming Settings. Empty folder ->
  "no .eml files yet" with the export script path. Unreadable folder -> the
  watcher's own cause. No invented counts, no sample stamp on real data.
- **G6 Browser proof.** Marketplace install, Settings mail toggle, plugin card with
  mock inbox, Studio publish/install, screenshots, pass/fail table.

## User Stories

1. As the presenter, I want Install to work from the Marketplace on the first click,
   so the demo never shows a hash error.
2. As a desk owner, I want my local Outlook mail to reach the app without an admin
   or a connector, so I can use the product on a locked-down laptop.
3. As a desk owner, I want the Outlook card to tell me what arrived, which message
   matters most, and how I might reply, so I can act without opening Outlook first.
4. As a plugin author, I want my published plugin to appear in the catalog and
   install on the same desk, so creation is complete rather than a preview.
5. As a reviewer, I want a browser walkthrough with evidence, so "it works" is a
   recorded run, not a claim.

## Acceptance Criteria

- G1: python scripts/sync_registry.py reports 0 changed pins on a clean tree;
  python -m pytest -q tests/test_registry_library.py tests/test_catalog_bundle.py
  tests/test_registry_hardening.py tests/test_marketplace_walkthrough.py passes;
  a new test recomputes every local release pin and fails on drift; installing
  outlook-digest, excel-report, research-brief and sales-delta-widget from the
  bundled catalog into a temp desk succeeds.
- G2: a created plugin with one metric element validates through the Studio, is
  published, appears in the catalog, installs, and renders its sample; the trace
  document lists each request and response.
- G3: tools/export-outlook.ps1 -OutDir <dir> exports at least 3 .eml files from a
  configured profile, and exits with a plain message when no profile exists;
  demo/outlook-inbox/ holds at least 6 checked-in .eml files that parse.
- G4: with mail_folder pointing at the mock inbox and mail_enabled on,
  /api/plugins/outlook-digest/retest returns a payload whose elements include
  messages > 0, a nonempty thread digest, a topEmailSubject, a topEmailWhy, and
  three reply starters.
- G5: unconfigured and empty-folder states return attention status with copy that
  names Settings and the export script; no binding carries a number in those states.
- G6: docs/demo/2026-11-18-plugins.md records the browser steps with screenshots;
  no console errors; all plugin cards stay inside their grid at 1280 and 1600 px.

## Non-Goals

- Microsoft Graph, IMAP OAuth, Exchange Web Services, tenant consent, or any cloud
  connector.
- Sending mail from the app; reply starters are text, and any draft stays local.
- Reading message bodies or sending them to a model. The mail path stays
  metadata-only; the brief is built from headers (From, To, Cc, Subject, Date,
  Message-ID, In-Reply-To, Importance).
- Outlook .msg or .pst parsing.
- Reworking the home dashboard, the EVP tracker demo, or issue #115's CI job.
- Multi-user mailboxes or shared mailboxes.

## Risks

- The demo laptop has Outlook.exe but no configured profile. The mock inbox is the
  rehearsed path; the export script is the real-machine path, proven by its no-profile
  message.
- A stale bundled catalog could still ship if only registry/index.json is rebuilt.
  T01 rebuilds both and the guard test reads the bundled catalog too.
- The plugin card is 2x1 by default; the brief needs a taller layout. The manifest
  moves to 2x2 and the browser sweep proves no overlap.
- Reply starters built from subjects can sound generic. The card labels them
  "starters from the subject line" and never claims to have read the body.

## Further Notes

- The mail watcher's folder read is host-owned, so the plugin declares no filesystem
  read glob; it declares network empty and llm false.
- The export script uses Outlook COM (New-Object -ComObject Outlook.Application),
  reads the Inbox default folder, and writes <timestamp>-<id>.eml with CRLF.
  It is opt-in and runs on the user's machine only.
