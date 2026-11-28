# Enterprise distribution

Status: 2026-11-16. This document describes the one-folder Windows bundle,
what IT must provide, and the AppLocker rule template. The bundle is
**unsigned in this environment**; no publisher string exists yet. Treat the
AppLocker section as a template to complete after signing, not as a deployed
policy.

The product is Nexuus Bot. The names the bundle and its rules ship with
(`AgentDesk.exe`, `dist/agent-desk`, the `\\fileserver\AgentDesk` install
and update shares, `agent-desk.zip`, the AppLocker `BinaryName`) are
compatibility identifiers: they keep their exact spelling so endpoint and
update rules keep matching. `docs/ops/compatibility.md` lists every
retained identifier with its context, owner and review trigger.

## Build

### Prerequisites

- Windows 10 or 11, x64.
- Python 3.11+ recommended (the repo floor is 3.10). The SBOM generator uses
  `tomllib` on 3.11+; on 3.10 it can still parse the current zero-dependency
  pyproject.
- Nuitka: `python -m pip install nuitka`.
- Node 22+ only if you need to rebuild the dashboard. The committed Vite
  bundle in `src/agentdesk/server/static/spa/` is what ships; end users never
  need Node.
- A C compiler is not required on Windows: Nuitka can fetch its own MinGW64
  toolchain, but only when the build is invoked with
  `--allow-downloads`. That download is an explicit opt-in, not a default.

### Commands

```
python scripts/sbom.py
python scripts/license_gate.py build/sbom.cdx.json --report build/license-report.txt
python scripts/third_party_notices.py
python scripts/build_bundle.py build
python scripts/build_bundle.py verify
python scripts/build_bundle.py smoke
```

If the dashboard sources changed, rebuild the committed bundle first:

```
cd frontend
npm ci
npm run build
cd ..
```

The build refuses to run without `build/sbom.cdx.json`, `LICENSE`,
`LICENSE-SDK`, and `THIRD-PARTY-NOTICES.md`. It also refuses to overwrite a
non-empty `dist/agent-desk` that has no prior `manifest.json` unless
`--force` is passed.

### Local development and the gate

Developer tools are an optional extra: `python -m pip install -e ".[dev]"`
installs pytest and pytest-xdist, and neither is a runtime dependency or
enters the SBOM. `python tools/ci_local.py` runs the full suite as one of its
gates; when xdist is importable it runs pytest in parallel with the worker
count capped at eight (higher counts exhausted the Windows ephemeral port
range under the suite's loopback traffic), and without xdist it keeps the
original serial invocation, so the verdict and the reported counts are the
same either way.

### What the Nuitka profile does

- `--standalone` produces a **one-folder** bundle. `--onefile` is deliberately
  not used: one-file self-extracts on every launch, is harder for AppLocker
  and endpoint protection to reason about, and leaves temporary copies of the
  executable.
- `--enable-plugin=no-qt` keeps unused Qt support out.
- `--include-package=agentdesk` compiles the application package.
- `--include-data-dir=src/agentdesk/server/static=agentdesk/server/static`
  embeds the committed dashboard build output.
- `--nofollow-import-to=tests` and `pytest` keep test code out.
- `--windows-console-mode=disable` produces a GUI-subsystem executable. It
  binds only to `127.0.0.1` and opens the browser; it does not install a
  service or a firewall rule.
- No `--windows-uac-admin` flag is used. Nuitka's default `asInvoker`
  manifest is kept, so the app runs as the signed-in standard user.

The exact command is recorded in `dist/agent-desk/manifest.json` under
`build.command`, along with the Nuitka version, Python version, duration,
platform, entrypoint, and signing status.

### Output layout

```
dist/agent-desk/
  AgentDesk.exe            stable file name, required by the publisher rule
  manifest.json            file list + SHA-256 + build metadata
  sbom.cdx.json            CycloneDX 1.6 SBOM for this build
  THIRD-PARTY-NOTICES.md   generated attribution
  LICENSE                  proprietary core terms
  LICENSE-SDK              Apache-2.0 plugin SDK terms
  licenses/
    third-party/           upstream texts (React, CPython, Apache, ...)
    fonts/                 OFL texts for the two font families
  ...                      Nuitka runtime files and the embedded dashboard
```

`manifest.json` lists every shipped file with size and SHA-256. The manifest
itself is excluded from its own list. `build_bundle.py verify` recomputes the
hashes and fails on any missing, changed, or unlisted file.

The executable name is intentionally `AgentDesk.exe` and must not change
casually: the AppLocker publisher rule pins `BinaryName`.

### Smoke test

`python scripts/build_bundle.py smoke` starts
`dist/agent-desk/AgentDesk.exe --port <free port> --no-browser` with
`AGENTDESK_DATA` pointed at a temporary directory, then polls
`http://127.0.0.1:<port>/health`.

The health endpoint is authenticated. The bootstrap token is held in memory
only, so a smoke test cannot present it. The smoke test therefore treats
**HTTP 401 as success**: it proves the HTTP server and the auth gate are
live. HTTP 200 also passes and additionally validates the health payload.
Any other status, or a process that exits, fails. The result is written to
`build/smoke-report.json` with the executable SHA-256, port, status, and
startup time.

If Nuitka is not installed, `build` prints `SKIP: Nuitka is not installed`
and exits 3. If no built executable exists, `smoke` prints `SKIP` and exits
3. Neither path fabricates an artifact or a result.

## What IT needs

- Windows 10/11 x64 with the standard user able to run executables from a
  per-user directory.
- An AppLocker or WDAC policy that allows the signed executable. AppLocker's
  default rules generally allow Program Files and Windows and block
  `%LOCALAPPDATA%`, which is where this bundle is installed. An explicit
  publisher allow rule is required.
- A code-signing certificate (Authenticode) whose chain is trusted by the
  fleet, plus a signing step in the release pipeline. Until then, the app is
  unsigned and a publisher rule cannot be built.
- Endpoint protection allowlisting or reputation for the signed publisher.
  The binary is a new, low-prevalence executable; unsigned builds will
  trigger SmartScreen and possibly AV heuristics.
- Network egress for the model and data sources the user configures. The app
  listens only on loopback; no inbound firewall rule is needed.
- A backup policy for the runtime data root, `%USERPROFILE%\.agent-desk`
  by default or the directory named by `AGENTDESK_DATA`. That directory
  holds user data and settings; the install folder `%LOCALAPPDATA%\AgentDesk`
  holds the program, not user data.

No admin rights, service account, machine-wide registry key, or driver is
required at runtime.

## AppLocker publisher rule

### Until a certificate exists

The build is unsigned, so there is no publisher string. The manifest records:

```json
"signing": {
  "status": "unsigned",
  "publisher": null,
  "note": "No Authenticode certificate is available in this environment. ..."
}
```

Do not deploy a publisher rule for an unsigned file. AppLocker publisher
conditions match the signing certificate; an unsigned binary has none.

### After signing

Get the exact values from the signed release binary:

```powershell
$sig = Get-AuthenticodeSignature .\AgentDesk.exe
$sig.Status
$sig.SignerCertificate.Subject
(Get-Item .\AgentDesk.exe).VersionInfo |
  Format-List CompanyName, ProductName, FileVersion, OriginalFilename
```

Use `SignerCertificate.Subject` verbatim as `PublisherName`. It is a full
distinguished name, for example
`CN=Agent Desk, O=Agent Desk, L=Seattle, S=Washington, C=US`. The product
name and binary name must match the version resource exactly.

Template, with placeholders that must be replaced from a signed binary:

```xml
<AppLockerPolicy Version="1">
  <RuleCollection Type="Exe" EnforcementMode="Enforced">
    <FilePublisherRule
        Id="00000000-0000-0000-0000-000000000000"
        Name="Nexuus Bot - signed publisher"
        Description="Allow Nexuus Bot from its per-user install folder"
        UserOrGroupSid="S-1-1-0"
        Action="Allow">
      <Conditions>
        <FilePublisherCondition
            PublisherName="CN=&lt;REPLACE-WITH-CERT-SUBJECT-CN&gt;, O=&lt;REPLACE-WITH-ORG&gt;, L=&lt;REPLACE-WITH-LOCALITY&gt;, S=&lt;REPLACE-WITH-STATE&gt;, C=&lt;REPLACE-WITH-COUNTRY&gt;"
            ProductName="Nexuus Bot"
            BinaryName="AgentDesk.exe">
          <BinaryVersionRange LowSection="0.1.0.0" HighSection="*" />
        </FilePublisherCondition>
      </Conditions>
    </FilePublisherRule>
  </RuleCollection>
</AppLockerPolicy>
```

Replace `Id` with a new GUID. Replace `UserOrGroupSid` with the intended
group (for example a pilot AD group) instead of Everyone, where possible.
Tighten `BinaryVersionRange` to the tested version range once the release
cadence is known.

Validate before rollout:

```powershell
# Parse the policy and test the rule against the actual file.
Get-AppLockerPolicy -Xml -Path .\AgentDesk.xml
Test-AppLockerPolicy -XmlPolicy .\AgentDesk.xml -Path .\AgentDesk.exe -User Everyone
```

The publisher rule only works if the certificate chain is trusted on the
client and the file is signed. Hash rules are possible but brittle: every
rebuild changes the hash, so they are not recommended as the primary rule.

## Runtime and data

- Launch is on demand: Start menu shortcut per user, no startup entry, no
  background service.
- The server binds to `127.0.0.1` only and opens a browser at
  `/auth/<one-time token>`. The token is exchanged for a session cookie.
- Default data root: `%USERPROFILE%\.agent-desk`. Override with the
  `AGENTDESK_DATA` environment variable. The program installs to
  `%LOCALAPPDATA%\AgentDesk`; that folder holds the application, not user
  data.
- Uninstall: delete the shortcut and the install folder
  `%LOCALAPPDATA%\AgentDesk`, then the data root `%USERPROFILE%\.agent-desk`
  if the user's data is no longer needed. No machine-wide changes are made.

## Update channel and rollback

The update channel is a controlled file share, for example:

```
\\fileserver\AgentDesk\stable\<version>\agent-desk.zip
\\fileserver\AgentDesk\stable\<version>\manifest.json
\\fileserver\AgentDesk\stable\<version>\sbom.cdx.json
```

Publish each version with its manifest and SBOM. When code signing exists,
publish the signature and verify it before distribution. Do not overwrite a
version directory in place.

Update procedure:

1. Close Nexuus Bot.
2. Copy the new version to a versioned folder under
   `%LOCALAPPDATA%\AgentDesk\app\<version>`.
3. Verify `manifest.json` against the extracted files and check the SBOM and
   signature status recorded in the manifest.
4. Repoint the per-user shortcut to the new `AgentDesk.exe`.
5. Keep the previous version folder until the pilot confirms the upgrade.

Rollback:

1. Close the app.
2. Repoint the shortcut to the previous version folder.
3. Keep the data directory unless the release notes say a migration ran; if
   one did, restore the pre-upgrade backup before launching the old version.

No data migration is assumed by this document. Check each release's notes
before rolling back across a version that changed stored data.

### Automatic updates (off by default)

The desk has a built-in updater, shipped off. In Settings > Updates, set the
share folder and leave Install updates off to only report what the share
holds. Turning Install updates on lets the desk stage a newer version, run
that version's own `--self-check` against a copy of the data, and write
`<data>/update/current.json` only when the check passes. A failed check
deletes the staged copy. A staged version waits for a restart: the desk never
restarts itself, and nothing runs while it is closed.

The first start of a pending version repeats the check in-process. On failure
the desk points `current.json` back at the previous version and restores any
SQLite store whose `PRAGMA integrity_check` no longer passes from the snapshot
taken before staging. The Settings page and dashboard name the rollback.

The launcher stub that reads `current.json` and starts the version it names is
pending Security review. Until it ships, the per-user shortcut still points at
the current `AgentDesk.exe`; a staged version, its pointer and its previous
version folder all remain on disk.

## Known gaps in this environment

1. **Unsigned build.** No code-signing certificate is available here, so the
   publisher rule is a template with placeholders, not a working policy.
   `manifest.json` says `unsigned` and `publisher: null`.
2. **Nuitka unavailable.** `python -m nuitka --version` fails with
   `No module named nuitka`. No bundle was built and no smoke test was run in
   this checkout. The scripts report SKIP with exit 3; the CI Nuitka job is
   tolerant only while the toolchain is absent.
3. **No installer.** Distribution is a zip or folder copy plus a per-user
   shortcut. There is no MSIX, MSI, or auto-update service.
4. **No AppLocker/WDAC rollout.** Policy design, pilot group, certificate
   procurement, and signing are out of scope for this ticket.
5. **Touches page contradiction.** `src/agentdesk/server/touches.py:64` still
   says the app is MIT. The core owner must update it; this packaging work
   was not allowed to edit `src/agentdesk`. See `docs/licensing.md`.
6. **Visual C++ runtime.** Nuitka standalone bundles Python and compiled
   modules, but validate on a clean Windows image that any required Visual C++
   runtime is present. This environment did not produce an artifact to test.
