# Licensing

Status: engineering policy and packaging record, 2026-11-16. **This is not
legal advice and has not been reviewed by counsel.** The proprietary licence
contains bracketed `[COUNSEL: ...]` placeholders for commercial terms. Do
not describe the product as legally cleared until counsel has reviewed
`LICENSE`, `LICENSE-SDK`, and the plugin distribution grant.

## The boundary

| Area | Licence | What it covers |
|---|---|---|
| Agent Desk core | Proprietary, all rights reserved (`LICENSE`) | The application, runtime, dashboard UI, validator implementation, and documentation, except the SDK materials below |
| Plugin SDK | Apache-2.0 (`LICENSE-SDK`) | The declarative plugin manifest schema (schemaVersion 2), `docs/design/plugin-authoring-v2.md`, and any file explicitly marked Apache-2.0 or placed under `sdk/` |
| In-box plugins | MIT, per plugin manifest | `registry/plugins/*` content. These predate the core relicence and are out of scope for it |
| Third-party components | Their own licences | Recorded in `THIRD-PARTY-NOTICES.md` and the SBOM; texts ship in `dist/agent-desk/licenses/` |

The SDK boundary is a specification and documentation grant, not a separate
binary or Python package. No `sdk/` directory exists today. The plugin
validator in `src/agentdesk/validator/` implements the schema and remains
proprietary; plugin authors do not need that source to author or distribute
a compatible declarative plugin.

Why Apache-2.0 for the SDK: plugin authors need a clear patent grant and a
permissive right to implement the manifest schema, including in commercial
tooling. Apache-2.0 is compatible with the proprietary core because the SDK
is a separate boundary, not a licence of the core.

The plugin manifest schema accepts only MIT, Apache-2.0, BSD-2-Clause,
BSD-3-Clause, and ISC for plugins. That allowlist is enforced by the core
validator and is unchanged by this work. In-box plugins keep their existing
MIT notices.

## Adapted source

Hermes Agent (github.com/NousResearch/hermes-agent, commit `f6c3eb1`,
Copyright (c) 2025 Nous Research) is MIT-licensed. Portions adapted in
`src/agentdesk/{ledger,deskcheck,agentloop,recommend,safety,update}`,
`memory/profile*.py` and `repetition/curator.py`. The upstream licence text
is vendored verbatim at `licenses/third-party/hermes-agent-LICENSE.txt`
(sha256 `821556e6...5ab6`), and every adapted file's module docstring names
the upstream path it came from and points at that file.

This is adapted source, not a package dependency. It is vendored by
adaptation rather than installed, so it is not a component in the SBOM, adds
no entry to `THIRD-PARTY-NOTICES.md`, and passes the licence gate without an
exception; the vendored licence text is the notice that travels with the
adapted code.

## Plugin authors keep their copyright

Plugin authors retain all right, title, and interest in their plugins.
Submitting a plugin to the marketplace does not assign copyright. The author
grants Agent Desk a worldwide, non-exclusive, royalty-free, sublicensable
licence to host, reproduce, distribute, display, and make the plugin
available, and to modify it only as technically necessary to package,
validate, render, or display it. `LICENSE` section 5 records this grant;
the exact scope, term, patent, moral-rights, and takedown terms are marked
for counsel and must be finalised before the marketplace opens to third
parties.

## The licence gate

`scripts/license_gate.py` reads a CycloneDX 1.6 JSON SBOM and checks every
component, including components whose CycloneDX `scope` is `excluded`
(build-only). Build-only packages are still checked so a restricted licence
cannot hide in the toolchain.

Allowlist: `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`.

Recorded exceptions, each requiring an `agentdesk:license-exception`
property on the component with the matching licence value:

| Licence | Components | Why |
|---|---|---|
| `OFL-1.1` | `@fontsource` font packages | Font licence; bundling is permitted when the copyright notice and licence travel with the fonts |
| `PSF-2.0` | CPython runtime | The Python runtime is redistributable under the PSF licence; it is not a third-party code dependency of the app |
| `MIT-0` | `@csstools/color-helpers` | Build-only, never distributed |
| `CC-BY-4.0` | `caniuse-lite` | Build-only browser data, never distributed |

Commons Clause, UNLICENSED or unknown, GPL, LGPL, AGPL, and SSPL always fail,
even if an exception property is present. A missing licence fails. SPDX
expressions are evaluated conservatively: every identifier must pass, so a
dual `MIT OR GPL-3.0` component fails for review rather than silently
choosing a branch.

Exit codes: `0` pass, `1` missing or malformed SBOM, `2` policy failure.
`--report PATH` writes the same human-readable report.

Adding a dependency is a licensing decision. Update the source manifest, run
the SBOM generator, and let the gate fail before adding an exception. New
exceptions belong in `scripts/license_gate.py` and
`scripts/sbom.py` and need a written rationale plus counsel review, not a
hand-edited SBOM.

## SBOM and notices

```
python scripts/sbom.py
python scripts/license_gate.py build/sbom.cdx.json --report build/license-report.txt
python scripts/third_party_notices.py
python scripts/third_party_notices.py --check   # CI
```

`scripts/sbom.py` writes `build/sbom.cdx.json` in CycloneDX 1.6. It covers
the CPython runtime, every frontend package pinned in
`frontend/package-lock.json` (production and development), and the Python
runtime dependency set from `pyproject.toml`. The app currently declares no
third-party Python runtime dependencies; the SBOM records that explicitly
and includes the stdlib note. Ordering is deterministic.

`THIRD-PARTY-NOTICES.md` is generated from the SBOM and is never
hand-edited. It lists every distributed component with the path and SHA-256
of its upstream licence text. `--check` fails if the committed file is stale.
The generated notices deliberately omit the SBOM timestamp and serial so the
file is stable across regeneration.

The legacy `THIRD-PARTY-LICENSES.md` and `tools/license_manifest.py` were
deleted once the local gate watched this SBOM chain (spec 017 6f): they were
a second, weaker license record whose hardcoded SPA versions could be wrong
and still pass their byte-diff gate. `THIRD-PARTY-NOTICES.md` plus the SBOM
are the authoritative distribution record, checked by hosted CI and by the
local `licenses` leg alike. Do not create a root `NOTICE` file; an existing
test asserts it does not exist, and the generated notices cover third-party
attribution.

## Landmine sweep

Target: the vendored react-bits components from the old dark-glass theme,
licensed MIT plus Commons Clause. Commons Clause forbids selling the
software, which is incompatible with a commercial enterprise distribution.

Finding: no react-bits source, vendored directory, or Commons Clause licence
remains in the tree. A repository-wide search for
`commons clause`, `commons-clause`, and `react-bits` finds no source or
vendored directory. The remaining hits are historical or defensive:
the T14 ticket and plan documents, this document, the gate fixtures in
`tests/fixtures/license_gate/commons.cdx.json` and
`tests/test_license_gate.py`, and the negative regression assertion in
`frontend/src/test/tokens.test.ts:200-203`, which asserts that
`src/vendor` does not exist and that no component imports
`vendor/reactbits`. The components and their supporting animation, styling,
and class-helper packages were removed with the dark-glass theme in an
earlier revamp. The three-theme Geist system in `docs/design-language.md` is
drawn with the repo's own stylesheet and components, so no user-facing
feature was dropped by this ticket.

Because nothing remained, nothing was quarantined and no new directory was
excluded from the build. The regression guard is the CI source scan for
`Commons Clause` and `react-bits` in `src/`, `frontend/src/`, and
`registry/` (it excludes `frontend/src/test/tokens.test.ts`, the negative
assertion above), plus the SBOM gate for dependencies. Do not reintroduce
these components.

## Known gaps and required follow-ups

1. `src/agentdesk/server/touches.py:64` still renders `License: MIT` on the
   user-facing "What this app touches" page. The packaging agent was not
   allowed to edit `src/agentdesk`; the core owner must change it to point at
   `LICENSE` and `LICENSE-SDK`. Until then the UI contradicts this document.
2. The build is unsigned in this environment. There is no Authenticode
   certificate, so the AppLocker publisher string is a documented placeholder,
   not a verified rule. See `docs/ops/distribution.md`.
3. Nuitka is not installed in this environment, so no bundle was built and no
   smoke result is claimed. The build script prints an explicit SKIP and exits
   3. CI has a Nuitka job that is tolerant only while the toolchain is absent.
4. The proprietary terms are a packaging draft. No counsel review has
   happened. The `[COUNSEL: ...]` placeholders are not enforceable final
   terms.
5. The plugin distribution grant is drafted in `LICENSE` section 5 but is
   not yet implemented as a marketplace acceptance flow. The marketplace must
   present it before accepting third-party submissions.
6. The SBOM records the frontend dependency tree, not a byte-for-byte scan of
   the compiled JavaScript bundle. The committed Vite output is built from the
   locked tree; the frontend CI job rebuilds it and checks the committed diff.
