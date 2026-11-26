# Architecture review and remediation, 2026-11-24

The mattpocock `improve-codebase-architecture` review of agent-desk-core
at cec6da9 (three read-only explorers over server, engine, connectors;
28 findings), the advisor-approved remediation wave (10 findings), and
the ponytail pass over the resulting diff (4 findings, fixed). Branch:
`arch/deepening-2026-11-24`. The full visual report was written to the
OS temp dir only (`architecture-review-2026-11-24-agentdesk-core.html`),
so nothing landed in the repo but this pack.

## What changed, by finding

Server: one `run_fill` entry in `presentations/pipeline.py` (the fill
loop, shorten, deliver and failure ladder existed twice in app.py);
one `deck_artifact` builder in `presentations/artifact.py` (three
hand-built literals, one copy-all-except delta); one `_require_store`
guard (55 app.py refusals, then 10 memory-mixin refusals in the
ponytail pass; the drifted 503 sentences consolidated per store, and
the combined skills-or-ledger guard now names the store that is
actually gone); deck-tool runs name their declaring plugin in the
result and the audit.

Plugins and marketplace: the runtime's `pending_diff` is the only
consent decision (the marketplace's auto-consent branch is deleted; a
`True->False` permission drop now holds for re-consent, fail-closed,
pinned by an updated test; a pure scope-key removal still applies
without consent, pinned by a new test; the response's display lists are
unchanged); one `emission_targets` spine under `layout_keys`,
`widget_cards` and `record_dashboard_view`, pinned before and after by
a table-driven golden matrix (7 cases); `validator/grammar.py` owns the
safe-name, JSON-selector and path-root patterns (lint, runtime,
sources, and from the ponytail pass also plugin config, import it).

Engine: `Step.order` plus `ordered_steps()` make the pass order
declared data (the "position is the order" noqa import is gone), and
`AgentLoop(steps=...)` lets tests select steps, so the nine STEPS
monkeypatches became constructor arguments; `agentdesk/locking.py` owns
the store-serialization rule (six copies deleted, the shared-lock
pairing named at the construction site); dead seams deleted in one
commit: the retired token-overlap scorer (`memory/service.py`),
the unused `seal`/`unseal` profile parameters, and the stale package
docstring claims.

## Deliberate behaviour changes (none are silent)

1. A marketplace update whose only change is a permission value drop
   (`True->False`) now stays `pendingConsent` until the user accepts;
   it used to apply through the auto-consent compensation branch.
2. A resumed presentation run's artifact card names the pack that
   actually produced the deck (id, version, digest), not the one stored
   at pause time.
3. Consolidated 503 sentences for stores whose refusals had drifted
   ("settings are not available" is now "the settings store is not
   available", and similar); status codes and JSON keys unchanged.

No UI surface changed, so there are no screenshots: the visible flows
are pixel-identical; the changed things are API sentences, an audit
field, and internals. `GLOSSARY.md` at the repo root names the new
interface vocabulary.

## Gate evidence

Two full `python tools/ci_local.py` runs on the branch, both 7/7 PASS:

- After the 10-finding wave: 652 s total; pytest 3111 passed, 2
  skipped, 13 warnings in 635 s; tsc clean; vitest 326 passed;
  licenses, registry-ci and brand-leak clean.
- After the ponytail fixes and `GLOSSARY.md`: 632 s total; pytest 3112
  passed, 1 skipped, 13 warnings in 618 s; the other six gates clean.

The baseline on the untouched checkout before the wave: pytest 3112
passed, 2 skipped in 620 s.

## The PR audit round

The PR (kanitmann01/agent-desk-core #5) was then audited by an
independent reviewer subagent with read-only tools. Its verdict, "fix 1
and 2 first", and every finding, is addressed on the branch:

Must fix 1, the consent sheet called a permission value drop a
widening: the installed DTO now splits the held update into widening
(positive adds only) and dropping (granted leaves removed), computed
off the active and staged manifests, and the surfaces render a drop as
a drop ("The staged version drops N scope(s).", the drops note, no
widening callout). The built SPA bundle is committed with the fix.
Hosted CI had also caught, before the audit, that `agentdesk/locking`
died at import on the 3.10 floor (`threading.RLock | None` evaluated;
RLock is a factory function there): the future import defers it, the
packaging-subset job is green.

Must fix 2, the resume's `run_fill` call had moved the run-folder
creation outside the failure ladder: it is wrapped again, so a write
failure degrades the run honestly instead of reaching the generic 500.

Should fixes: the split skills/ledger guard no longer doubles "the";
the golden matrix gains a rollback case that drives the newest and
active manifests apart (mutation-checked: swapping the sources fails
exactly that test); `ordered_steps` sorting is pinned with an
out-of-order list; the resumed artifact's identity refresh is pinned by
a pack-changed-between-phases test; the two residual safe-name copies
(registry index, peers guard) read `validator.grammar.SAFE_NAME`.
Nice-to-haves: `run_fill` turns a missing shell variant into a cause,
the `fill_cause` ladder has its four unit arms, the misleading
marketplace test name is fixed, `_manifest_scopes`'s docstring says
display-only, and the boot builds its shared lock through
`store_lock()`.

Slices after the round: marketplace 54, plugins runtime 24, agentloop
20, presentation pipeline 16, presentation research 7, skill refine and
memory loop 47, peers and registry 31, tsc clean, vitest 327.

## Commits (branch order)

16dbf86 one fill entry, af886ff one artifact builder, 8f25fa6 + ede7eb9
tool attribution (plus its templates-dir fix), d79f6bc one store guard,
e1cafac the runtime's diff decides re-consent, 9ea8776 one
emission-target seam, bdd8d17 one safety-grammar owner, b2d1bbd step
order as declared data, 2140827 one serialization owner, 801e6df dead
seams retired, 550b801 config grammar reads the owner, 88725ad the
combined guard and the mixin's store guards, 92ed4bf the attribution
docstring, and the glossary.
