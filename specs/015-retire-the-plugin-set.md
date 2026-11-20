# Spec 015: Retire the plugin set to the two desk plugins

Status: ready-for-agent (2026-11-19). GitHub: issue #188; its body is the live
copy when the two disagree.

## Problem Statement

The desk ships 25 in-box plugins and three curated packs. Only two of those
plugins are attached to the six cards the owner actually keeps on the home
desk: the Workbook Tracker card (the workbook-tracker plugin) and the Page
watch card (the competitor-watch plugin). The other 23 are AI-built demos that
nobody wired into the desk's real work.

That gap is now the product's credibility problem:

- A reviewer cannot tell a shipped commitment from a demo. The catalog, the
  packs, the walkthroughs and the README all present 25 plugins as the
  product's depth, and none of the 23 earns that claim.
- The retirement surface is expensive for what it returns: every catalog
  change re-pins 23 plugin trees and regenerates digests, packs promise
  eight-plugin sets, docs and demos walk through cards nobody uses, and the
  test and CI surface carries the set.
- Installed demo plugins put cards on the desk that the owner never asked
  for, which is exactly the "mosaic of equal cards" the dashboard was
  designed not to be.

What must not change: the six cards (Pipeline, Moves, Decisions, Digest,
Excel Tracker, Page watch), the sources and payload behind them, and the
marketplace engine that the Add plugin path and the two surviving plugins
depend on.

## Solution

Retire the 23 plugins that are not bound to the six cards.

- The 23 plugin trees move out of the shipped registry into an archive folder
  in the repository. They stay on disk and in git history, but the marketplace
  no longer lists, installs, updates or packages them.
- The registry index, the packs document and the bundled catalog shrink to the
  two plugins the six cards are bound to. Packs retire: no pack exists that a
  product desk would ship today.
- The product wiring only the retired set used is removed: catalog
  regeneration paths for the archived trees, pack promises, the walkthrough
  steps and docs that present the 23 as shipped product. Historical,
  date-stamped documents stay as history.
- The marketplace engine, install/update/uninstall, consent, trust center,
  policy, peer sharing, Studio and the wizard survive unchanged. The Add
  plugin entry point survives; it opens the marketplace with the two shipped
  plugins and the create path.
- The dashboard, its payload, the six cards and their sources are unchanged.
  The two surviving plugins keep their cards and their setup flows.
- The owner's desk uninstalls the 23 installed copies once through the
  existing Installed surface: code goes, data folders stay.
- No automatic migration ships. A desk that never installed them is already
  correct; a desk that did gets the one-time manual cleanup.

Follow-up (out of scope here, but named so the archive's future is clear):
rebuild the two surviving plugins as core desk cards, after which the catalog
can honestly be empty.

## User Stories

1. As the desk owner, I want the six cards (Pipeline, Moves, Decisions,
   Digest, Excel Tracker, Page watch) to render exactly as they do today, so
   that my morning desk does not change.
2. As the desk owner, I want the workbook-tracker and competitor-watch
   plugins to stay installed and supported, so that the Tracker and Page
   watch cards keep working on my desk and on a fresh desk.
3. As the desk owner, I want the other 23 plugins archived on disk, so that I
   can read or recover any of them later without keeping them in the product.
4. As the desk owner, I want the marketplace to stop offering the retired 23,
   so that what I browse matches what the product stands behind.
5. As the desk owner, I want the 23 installed copies uninstalled once, so
   that no retired plugin keeps running on my desk.
6. As the desk owner, I want the data folders of the 23 kept after uninstall,
   so that nothing I tracked is lost by a retirement I cannot undo.
7. As the desk owner, I want the two remaining plugins' setup, consent and
   update flows untouched, so that my Tracker and Page watch keep behaving.
8. As a marketplace visitor, I want Discover to show the two shipped plugins
   honestly, so that the catalog's size is the product's real size.
9. As a marketplace visitor, I want publisher, category and trust surfaces to
   keep working for the two remaining entries, so that nothing about the
   marketplace breaks when the set shrinks.
10. As a marketplace visitor, I want no pack to promise a bundle containing a
    retired plugin, so that installing a pack never half-fails.
11. As a marketplace visitor, I want an honest empty state where packs used to
    be, so that the page reads as a decision rather than a bug.
12. As the desk owner, I want the Add plugin button to stay, opening the
    marketplace with the two shipped plugins and the create path, so that the
    entry point does not disappear.
13. As the desk owner, I want Studio and the wizard untouched, so that I can
    still build a local plugin the proper way when I need one.
14. As a reviewer, I want the committed catalog artifact and the registry
    index to agree on exactly two plugins, so that no install is ever offered
    for an archived tree.
15. As a reviewer, I want the archive excluded from the packaged build and
    from the marketplace scan, so that the retired set cannot leak back into
    the product by accident.
16. As a maintainer, I want catalog regeneration to work with two plugins and
    no packs, so that the routine release step stays one command.
17. As a maintainer, I want the registry review gate to pass over the two
    remaining trees, so that the retirement does not weaken CI.
18. As a maintainer, I want tests that assert the two-plugin catalog, the
    empty pack list and the fresh-desk install set, so that the retirement is
    locked in against silent regression.
19. As a maintainer, I want the acceptance walkthrough rewritten for the
    two-plugin reality, so that the executable proof matches the product.
20. As a maintainer, I want the README, operator docs and demo copy to say two
    plugins where they said 25, so that the next reader is not misled.
21. As a maintainer, I want the date-stamped historical docs left as history,
    so that the record of the 25-plugin release is not rewritten.
22. As a future plugin author, I want the archive README to say it is
    reference-only and not an import queue, so that the next plugin push
    starts from a stated bar instead of a bulk restore.
23. As the product owner, I want the bar for plugins returning to be written
    down, so that "properly later" is a definition rather than a hope.
24. As a release builder, I want the committed single-page build refreshed
    when marketplace copy changes, so that the double-click launcher serves
    the same product the source describes.
25. As the desk owner, I want the retirement never to delete a data folder,
    so that an update can never destroy something I did not ask to remove.

## Implementation Decisions

- **Archive contract.** The 23 retired plugin trees move, with history, from
  the shipped registry into a single archive folder under the repository. The
  trees are not edited as part of the move. The archive carries a short README
  naming the retirement date, why the set was retired, and that it is
  reference-only (not an import queue).
- **Archive isolation.** The archive folder is outside the registry scan, the
  bundled-catalog build input, the license and SBOM inputs, and the packaged
  build. A test proves the shipped catalog and the packaged inputs contain no
  archived id.
- **Registry contract.** The registry index keeps exactly the two surviving
  plugins, with their existing pins and releases unchanged. The packs document
  becomes an empty pack list. The bundled catalog is regenerated from the
  registry and carries exactly the two entries with fresh digests; its
  generated-at stamp is refreshed.
- **Marketplace contract.** No marketplace API or route changes. The assembled
  catalog lists two entries; the packs endpoint returns zero packs; the pack
  surface shows an honest empty state when no pack exists, and an unknown pack
  keeps answering as it does today. Publisher, category, detail, consent,
  install, update, rollback, trust-center and audit behavior are unchanged.
- **Dashboard contract.** The dashboard payload, the six cards, their data
  sources, the layout behavior and the plugin-card render contract are
  unchanged. The two surviving plugins keep rendering their cards and setup
  flows. No dashboard route is removed.
- **Plugin runtime contract.** Install, update, uninstall, purge, consent,
  policy, quarantine, yank, peer sharing, Studio submission and the wizard are
  unchanged. Retirement removes catalog entries and trees, not engine
  capability.
- **Add plugin contract.** The Add plugin entry point stays visible and opens
  the marketplace, where the two shipped plugins and the create path live.
- **Demo and docs contract.** Remove demo fixtures, walkthrough steps and
  catalog/pack copy that name the 23 retired plugins as shipped product.
  Date-stamped historical documents (release notes, research notes, evidence,
  the previous TODO entry) are left as history. Current product documents
  (README status, marketplace operator docs, demo instructions) are updated to
  the two-plugin reality, including the removal of the three packs.
- **Scripts contract.** The catalog build and registry sync routines continue
  to operate generically over whatever the registry holds, including two
  plugins and zero packs; no script gets a hard-coded allowlist of retired
  ids. The executable marketplace acceptance walkthrough is rewritten against
  the two-plugin catalog: no pack install step, no retired-plugin detail step,
  same install/consent/rollback/publish/kill-switch coverage over a two-plugin
  and synthetic-plugin mix.
- **Migration contract.** No automatic uninstall or data deletion ships. The
  owner's desk removes the 23 through the existing Installed surface, once;
  uninstall keeps data folders, as it already does. A fresh desk never sees
  the retired set because the catalog no longer carries it.
- **Trust bar for returning plugins** (recorded so the archive's purpose is
  explicit): at least one plugin the owner uses weekly with an owner-written
  spec; every shipped plugin passes the same review and tests as core code and
  carries a real registry digest; no more than three to five plugins ship at
  once; the archive is never restored wholesale.
- **Sample data.** The sample-data switch and the built-in core card samples
  are unchanged. Only sample or demo content that names or presents the
  retired 23 is removed.

## Testing Decisions

A good test here asserts external behavior: what the registry publishes, what
the catalog assembles for a fresh desk, what the marketplace shows and
installs, and that the dashboard still renders its six cards. It does not
assert internal helpers, pin the exact generated-at timestamp, or introspect
the archive folder's contents.

Seams, highest existing first (no new seams are needed):

1. **The catalog assembly seam (primary).** The registry index, the bundled
   catalog artifact and the assembled marketplace catalog are the one public
   seam the SPA and installs both consume. Tests assert: index and bundle pin
   the same two ids; the bundle is fresh against the registry; a fresh desk's
   catalog totals two; every bundled plugin installs from Discover. Prior art:
   the existing catalog-bundle, registry-library and fresh-desk suites.
2. **The registry review seam.** The shared registry review passes over the two
   remaining trees, and the append-only history check still passes. Prior art:
   the existing registry-review suite.
3. **The marketplace SPA seam.** Existing marketplace tests with fixture
   records continue to prove Discover, Detail, Pack, Installed, Studio and
   routing; new assertions cover the zero-pack empty state. Prior art: the
   existing marketplace test suite.
4. **The dashboard regression seam.** The dashboard's existing tests keep
   proving the six cards render and the payload contract is unchanged; the
   retirement must not need a dashboard test change. Prior art: the dashboard
   shell and card suites.
5. **The executable acceptance walkthrough.** The local walkthrough script is
   the end-to-end proof over a two-plugin catalog and a synthetic plugin, and
   the local CI gate keeps running it. Prior art: the existing walkthrough
   script and local CI.

CI: the local gate list stays the same; the registry gate iterates the two
remaining trees; the walkthrough step expectation is updated rather than
skipped. A missing archive-isolation assertion is a failure, not an omission.

## Out of Scope

- Rebuilding the workbook-tracker and competitor-watch plugins as core desk
  cards. That follow-up is what would let the catalog become empty.
- Any automatic migration, forced uninstall or data purge on a desk.
- Marketplace redesign, pack replacement, trust/review workflow changes, or new
  plugin features.
- Changes to the plugin engine, SDK, validator, policy, peers, Studio, wizard,
  dashboard payload, dashboard routes or the six cards' sources.
- Restoring, re-publishing or re-importing any archived plugin.
- Retired ids that an owner's organisation catalog or a paired desk still
  advertises: this change owns the bundled set only; other catalog sources
  keep their independence.

## Further Notes

- Git history is canonical for the archived trees; the archive folder exists so
  the set is browsable and honestly labelled, not because anything needs it at
  runtime.
- The two surviving plugins remain AI-built until the follow-up rebuild. They
  stay because the six cards depend on them; that exception is a compromise,
  not a certification.
- The README's status paragraph, the marketplace operator guide and the demo
  instructions are the current documents that must stop saying "25 plugins" and
  "three packs"; the dated release notes, research notes and evidence files
  keep their numbers as history.
- If the owner wants the retired set back on a desk, the supported route is a
  local registry path pointing at the archive, with the same review and
  consent paths as any local install; that is a manual act, never a product
  default.
