# The Nuitka smoke leg, run locally (spec 018 #235, 2026-11-21)

The `nuitka-build-smoke` job in `.github/workflows/enterprise.yml`,
exercised end to end on this machine with keyring present. Verdict
first: **the build carries keyring and the smoke stays green; no
fallback store is needed and none was made.**

## The job's steps, as run here

1. `python -m pip install nuitka .` (the job's install step): Nuitka
   4.3.5 (from source wheel, cp314) plus this checkout's package with
   its declared dependencies (`cryptography>=44`, `keyring>=25`).
2. `python scripts/sbom.py`: 219 components (9 distributed),
   `build/sbom.cdx.json`.
3. `python scripts/license_gate.py build/sbom.cdx.json`: RESULT: PASS.
4. `python scripts/third_party_notices.py`: regenerated
   THIRD-PARTY-NOTICES.md (this also surfaced that the committed file
   predated keyring; the regenerated file is part of this commit, which
   is what the workflow's `--check` step expects an environment with
   the declared dependencies installed to produce).
5. `python scripts/build_bundle.py build --allow-downloads`:

       build: Nuitka 4.3.5; log build/nuitka-build.log
       build: wrote dist/agent-desk (120 files, 177s, unsigned)
       build: exe sha256 85be6dd0594c259db5c7819042941c5b084ee20106a50c7fbe0fad9a064eacd7

   (No MSVC Windows SDK on this machine, so Nuitka used its
   auto-downloaded zig C backend; the workflow's windows-latest runner
   uses MSVC. Same build script, same flags.)

6. `python scripts/build_bundle.py verify`:

       verify: PASS 120 files match manifest.json (version 0.1.0)

7. `python scripts/build_bundle.py smoke`:

       smoke: PASS AgentDesk.exe served /health on 127.0.0.1:54702 with HTTP 401 in 0.6s (unsigned build)

## How keyring's runtime backend discovery travels

The worry from the spec: keyring discovers its backends at runtime
through package metadata (the `keyring_backends` entry-point group via
`importlib.metadata`), which a standalone build can drop. Empirical
answer on this build:

- `build/nuitka-report.xml` lists the compiled keyring tree inside the
  bundle: `keyring.backend`, `keyring.backends.Windows` (the Windows
  Credential Manager backend), `keyring.backends.fail` and
  `keyring.backends.null` (the honest no-keychain pair), plus the
  macOS/Linux backends; Nuitka 4.3.5 carries the included
  distributions' metadata, so the entry-point group resolves inside
  the compiled exe.
- The built exe booted against a throwaway data dir and authenticated
  through its one-time start link: `GET /api/connections` answers
  `{"keychainAvailable": true, "connections": []}`. The wrapper's
  `available()` answers false only for the fail/null backends, so a
  true here means a real OS keychain backend resolved inside the
  packaged build.
- `nuitka-built-exe-connections.png` shows the built app's Settings
  Connections card rendering with no no-keychain notice (the notice
  the page carries when `available()` is false).

So the packaged build stores keys in the real OS keychain, exactly as
the development tree does. The CI job's `continue-on-error` applies
only when the probe cannot install Nuitka at all (no toolchain); with
Nuitka present, a build, verify, or smoke failure fails the job.

## Not claimed

The build is unsigned (no code-signing certificate exists), so it is
the smoke evidence, not a release artifact. Nothing in `dist/` is
committed; the release caveats in `docs/known-limitations.md` stand.
