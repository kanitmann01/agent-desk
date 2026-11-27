# Spec 032: Nexuus Bot, one name on every live surface

**Status:** ready-for-agent (2026-11-26). Filed as #353. Tickets: #354, #355, #356, #357, #358, #359, #360, #361, #362, #363
`GLOSSARY.md` is the vocabulary.
Builds on main at `0f622e3` and the Spec 017 rule that a surface must not name a product that is not on the machine.
The live-surface inventory, the naming guard, the Python import boundary and the frontend package boundary are the seams. No new product seam.

## Problem Statement

Two names are now in play. The README says Nexuus Bot. The unchanged application and documentation layer says Agent Desk in 86 files and 207 occurrences of visible text at main `0f622e3` (R7). The brand guard pins the README title and the face constant, and keeps the em-dash rule. It pins nothing else.

The guard no longer catches old wordmarks, tab titles, page headings, avatar initials, server copy, prompts, generated reports, operator guides or the committed bundle. Three README screenshots still show the old UI. The Python distribution, import path and frontend package also carry the old code identity.

The founder chose the visible brand and code names as the scope. Data, runtime contracts and public distribution identities must remain stable so existing desks, plugins, scripts and operator rules keep working.

## Solution

Nexuus Bot is the product name and the agent name. Every live surface says Nexuus Bot. The avatar initials become NB.

A full-surface guard lands first. It owns an explicit inventory, rejects the old display forms, keeps the U+2014 ban and allows only named compatibility identifiers in named contexts. Name enforcement is on from its first commit: a temporary list names exactly what main still shows, so the gate stays green on the untouched tree while new old-brand text cannot land.

Live surfaces and live documents change next. That includes the server-rendered pages, the SPA, generated output, the README, the demo, the glossary, setup and operator guides, human-readable bundle metadata, and published Specs 030 and 031.

The package identity moves last. The Python distribution becomes `nexuus-bot`, the canonical import path becomes `nexuusbot`, and the frontend package becomes `nexuusbot-dashboard-spa`. The old `agentdesk` import subtree remains a compatibility alias to the same canonical module objects. Old module commands keep working.

The data folder, environment prefix, browser keys, cookie, keychain service, wire identities, publisher identities, command names, launcher scripts, repository name, executable and artifact names, SBOM metadata, legal lines and historical archives keep their names. Each is pinned by a story and a test so a later rename cannot move it by accident.

## User Stories

### The name people meet

1. As a manager, I want the product and the agent to be called Nexuus Bot everywhere, so that I never have to decide whether two names mean the same thing.
2. As a manager, I want every wordmark in the phone bar, desktop rail and server-rendered shell to say Nexuus Bot, so that navigation has one identity.
3. As a manager, I want every browser tab title, page title and breadcrumb to say Nexuus Bot, so that tabs and history identify the right product.
4. As a manager, I want the avatar title to say Nexuus Bot and its initials to read NB in the SPA, the server shell and the committed bundle, so that the face matches the product.
5. As a manager, I want the startup banner and launcher output to say Nexuus Bot while the launcher filenames stay unchanged, so that the first message is new and the command still works.
6. As a manager, I want authentication recovery, session-expired, update and error messages to say Nexuus Bot, so that a failure does not send me to an old product name.
7. As a manager, I want the setup wizard, plugin descriptions and every prompt or sentence that names the product to say Nexuus Bot, so that the agent speaks with one name.
8. As a manager, I want probe reports and generated presentation metadata to say Nexuus Bot, so that exported work carries the current brand.
9. As a reader, I want the README title, body, image alt text and architecture labels to say Nexuus Bot, so that the public introduction is consistent.
10. As a reader, I want the three README screenshots to stay as they are through every stage of this rename, as the founder decided on 2026-11-25, so that they are captured once against the finished product instead of twice.
11. As a presenter, I want the spoken and written demo to say Nexuus Bot while retained commands keep their exact spelling, so that the demo is truthful and runnable.
12. As a reader, I want the glossary title and product definition to say Nexuus Bot, so that the vocabulary starts with the approved name.
13. As a frontend developer, I want the frontend README and package description to say Nexuus Bot, so that setup documentation matches the application.
14. As an operator, I want the distribution guide to say Nexuus Bot in prose while it keeps the exact executable, artifact, install, update and BinaryName contracts, so that branding changes without breaking rollout.
15. As an operator, I want the marketplace guide to say Nexuus Bot and to distinguish the runtime data root from the bundle install folder, so that backup and recovery instructions are accurate.
16. As a licence reviewer, I want the live licensing guide to say Nexuus Bot in explanatory prose while legal instruments, the guide's plugin-grant summary, generated notices and licence-table identifiers stay byte-for-byte unchanged, so that engineering documentation and legal records do not drift.
17. As a reader, I want Windows file properties, the bundle manifest product and AppLocker rule names, descriptions and ProductName conditions to say Nexuus Bot, so that every human-readable product field agrees.
18. As a reader, I want no live instruction to promise an installer or executable that does not exist, so that the first retirement rule remains true even though launcher scripts keep their names.

### The guard

19. As a reviewer, I want the guard to pin Nexuus Bot on every surface in an explicit inventory, so that a missed surface fails instead of relying on memory.
20. As a reviewer, I want the guard to reject every old display form and the old avatar initials on live surfaces, so that mixed branding cannot ship.
21. As a reviewer, I want the guard to allow an old identifier only at its exact documented context, so that a compatibility exception cannot hide a new old-brand sentence.
22. As a writer, I want the U+2014 ban to remain in force across the same live trees, so that the rename does not weaken the writing rule.
23. As an archivist, I want dated evidence, tickets, plans, ideas, research, old specs, design records and archives excluded by name, so that provenance remains intact.
24. As a reviewer, I want old branded media rejected by SHA-256 fingerprint rather than a stored plaintext token, so that image leaks fail without publishing the retired wordmark. Delivered by a follow-up issue, not by these tickets.
25. As a maintainer, I want negative guard fixtures for a missing new name, an old wordmark, old initials and an unapproved compact identifier, so that the guard itself is proven to fail.

### The package identity

26. As a Python developer, I want the distribution name to be `nexuus-bot`, so that package metadata names the current product.
27. As a Python developer, I want the canonical import path to be `nexuusbot`, so that new code uses the new identity.
28. As a plugin author, I want `import agentdesk` and every old `agentdesk.*` submodule to resolve to the same module objects as `nexuusbot.*`, so that existing plugins and scripts do not break or create duplicate state.
29. As an operator, I want `python -m agentdesk.server`, `python -m agentdesk.probe`, `python -m agentdesk.presentations.cli`, `python -m agentdesk.registry` and `python -m agentdesk.validator` to keep working through the alias, so that existing commands and runbooks remain valid.
30. As a plugin author, I want every Python import used by the registry plugins to resolve through `nexuusbot` and again through `agentdesk`, so that either host path is proven in isolation.
31. As a frontend developer, I want the private package name and lockfile identity to be `nexuusbot-dashboard-spa`, so that the frontend package names the current product.
32. As a frontend developer, I want the production bundle to build into the canonical Python package and remain served at the same static URL, so that the code path moves without a URL migration.
33. As a release developer, I want all first-party imports, frozen entry imports, package inventories and bundle build inputs to use the canonical package while the build also carries the small old-import alias, so that startup and packaging cannot miss the move.
34. As a developer, I want generated package metadata to be regenerated rather than hand-edited, so that distribution and source inventories agree.

### Compatibility contracts that keep their names

35. As a manager with an existing desk, I want the data root to remain `.agent-desk`, including its config, templates, logs, PID, temp, backup, plugin data and update state, and the OneDrive calendar hint to remain `agent-desk/calendar_sync.json`, so that the renamed product opens the same desk and finds existing calendar exports.
36. As an operator, I want `AGENTDESK_DATA`, `AGENTDESK_CALENDAR_FILE`, `AGENTDESK_LLM_BASE`, `AGENTDESK_LLM_KEY`, `AGENTDESK_LLM_MODEL`, `AGENTDESK_MAIL_FOLDER`, `AGENTDESK_MARKETPLACE_ADMIN`, `AGENTDESK_REGISTRY` and `AGENTDESK_TEMPLATES` to keep their names and precedence, so that existing environments keep working.
37. As a developer, I want `__AGENTDESK_LAYOUT_STRESS__` and `__AGENTDESK_LAYOUT_TRIPLED__` to keep their names, so that layout tooling keeps its contract.
38. As a manager, I want `agentdesk.railCollapsed`, `agentdesk.setupDismissed`, `agentdesk.marketplace.catalog.v1` and `agentdesk.theme` to keep their names, so that browser preferences and catalog state survive.
39. As a manager, I want the session cookie to remain `agentdesk_session`, so that current sessions do not fail.
40. As a manager, I want the keychain service to remain `agent-desk`, so that saved secrets remain reachable.
41. As an operator, I want health and peer identity to remain `agent-desk`, the server, LLM and probe User-Agents to remain `AgentDesk/<version>`, `agentdesk/0.1` and `agentdesk-probe`, the peer derivation prefixes to remain `agentdesk-peer-channel:` and `agentdesk-peer-token:`, the audit actor to remain `agent-desk`, and the Outlook Message-ID domain to remain `agent-desk.local`, so that old and new desks recognise each other and stored records keep their meaning.
42. As a developer, I want the existing `agentdesk:theme` event to keep its name and no new product-branded custom event, data attribute, API path, custom URL scheme or hostname to be introduced, so that the wire surface stays stable.
43. As a plugin author, I want publisher `agent-desk`, wizard publisher `agent-desk-wizard`, publisher route values and installed publisher records to remain unchanged, so that plugin pages, policy and provenance still resolve.
44. As an operator, I want the documented CLI command names to stay the same, so that scripts do not need a command rewrite.
45. As an operator, I want `agent-desk.cmd`, `agent-desk.command`, `probe.cmd`, `probe.command`, `agent_desk_entry.py` and the existing start scripts to keep their filenames, so that shortcuts and runbooks still point to real files.
46. As a reader, I want the repository and clone folder to remain `kanitmann01/agent-desk`, so that URLs and checkout instructions remain true.
47. As an IT operator, I want installer names, `AgentDesk.exe`, the `agentdesk.exe` update alias, the `agent-desk` bundle folder, `agent-desk-bundle`, `agent-desk.zip`, `AgentDesk` install and update shares, AppLocker BinaryName and the signing placeholder identity to remain unchanged, so that endpoint and update rules keep matching.
48. As a licence reviewer, I want SBOM application name `agent-desk`, properties `agentdesk:license-file`, `agentdesk:license-exception`, `agentdesk:dev-dependency`, `agentdesk:stdlib-note`, `agentdesk:license-ref`, `agentdesk:sdk-license`, `agentdesk:bundle`, `agentdesk:python-runtime-dependencies`, `agentdesk:frontend-lockfile` and `agentdesk:frontend-lockfile-sha256`, and table `[tool.agent-desk-licenses]` to remain unchanged, so that generated compliance records stay stable.
49. As a licence reviewer, I want the proprietary licence, SDK licence, copyright lines, plugin notices, generated third-party notice wording and the licensing guide's plugin-grant summary to remain unchanged, so that this rename makes no legal amendment.
50. As a historian, I want dated archives and old specifications to remain as written, so that they continue to record what was produced then.
51. As a founder, I want Spec 032 to remove none of these compatibility contracts, so that any future contraction needs a separate approved support window.

### Documents and dependent specs

52. As an operator, I want one compatibility table naming every retained identifier, its exact context, its owner and its review trigger, so that the exceptions are documented rather than folklore.
53. As a reader, I want the glossary to distinguish the product name from compatibility identifiers, so that new copy does not imitate legacy code names.
54. As a developer, I want the README to name the canonical distribution and import path and explain the old import alias, so that setup uses the new identity without hiding compatibility.
55. As a founder, I want published Spec 030 to say that both the product and agent are Nexuus Bot, to remove its conflicting copy exclusion and to depend on Spec 032, so that shell and face work starts from one name.
56. As a founder, I want published Spec 031 to record its dependency on Spec 032 and use Nexuus Bot wherever it names the product, so that presentation work starts from the same vocabulary.
57. As a reviewer, I want a before-and-after count report using the R2 method, so that the rename can be measured rather than asserted.
58. As a new contributor, I want the README's frontend prerequisite to state the minimum Node version for the frontend development tools and which versions below it do not work, with the value taken from the frontend toolchain rather than guessed, so that setup does not start on a runtime the build rejects.
59. As a reader, I want the README's keychain sentence to say only what the code does, that model keys go to the OS keychain where a usable keychain is available, that no key is stored where it is not, and that plaintext configuration and legacy fallback paths exist, so that the public introduction makes no stronger claim than the code supports.
60. As a maintainer, I want the README's screenshot capture instructions to include the step that installs the browser, so that the capture command runs on a clean machine and the screenshots can be retaken with one command and no hand work.

### Proof

61. As a reviewer, I want every stage to end with `7/7 gates passed` and `CI PASS`, so that a partial rename cannot become the new baseline.
62. As a reviewer, I want no test in this spec to start a real desk, a walk or the application, so that naming proof stays deterministic and side-effect free.
63. As a release developer, I want the committed SPA to match a fresh production build, so that the shipped bytes carry the new name.

## Implementation Decisions

### The name contract

- The approved product name and agent name are exactly `Nexuus Bot`. The avatar initials are exactly `NB`.
- The guard owns the approved literals and the live-surface inventory. Runtime constants and rendered output must equal them.
- The inventory covers source and shipped SPA titles, both rails, the server shell, avatar title and initials, startup output, authentication and session copy, update and error pages, the wizard, product-naming prompts and sentences, probe reports, presentation metadata, the README family, demo, glossary, frontend setup documents, operator guides, human-readable bundle metadata and the committed bundle.
- Old display forms are rejected case-insensitively: `Agent Desk`, `AgentDesk`, `agentdesk`, `agent-desk`, `agent_desk` and the uppercase prefix when used as display text. The old `AD` initials are rejected only in avatar contexts, because `AD` has unrelated valid uses.
- Production source and live documents are scanned. Test trees may carry negative fixtures and compatibility imports. The em-dash scan keeps its broader live-tree scope.
- Content and tracked path names are checked. A path may keep an old form only when it is an alias shim, a retained launcher, a test of a retained launcher, a legal file or a dated archive.
- An allowlist entry names an exact identifier and the context permitted to contain it. A spelling is never allowlisted globally.
- Legal instruments and notice files are excluded from the display-name scan and pinned unchanged. Dated archive trees are excluded by name and pinned as provenance.

### The compatibility allowlist

The guard and the operator compatibility table read the same short, structured list:

- Import compatibility: `agentdesk` and its submodules, only in the alias implementation, alias tests, plugin compatibility tests and compatibility documentation.
- Data and local state: `.agent-desk`, `.agent-desk-backup`, `agent-desk-data`, `agent-desk/calendar_sync.json`, log, PID, temp, install and update names derived from the existing contracts.
- Environment and tooling: the nine `AGENTDESK_*` variables named in the stories, `__AGENTDESK_LAYOUT_STRESS__`, `__AGENTDESK_LAYOUT_TRIPLED__`, and the existing runtime and tooling temp names `agentdesk-ci-`, `agentdesk-base-index-`, `agentdesk-smoke-`, `agentdesk-walkthrough-`, `agentdesk-ready-`, `agentdesk-engine-smoke-`, `agentdesk-feedback-`, `agentdesk-layout-`, `agentdesk-bundle-`, `agentdesk-wizard-`, `agentdesk-selfcheck-`, `agentdesk-publish-`, `agentdesk-registry-`, `agentdesk-marketplace`, `agentdesk-update-`, `agentdesk-peer-`, `agentdesk-probe-` and `agentdesk-shadow`.
- Browser and secrets: `agentdesk.railCollapsed`, `agentdesk.setupDismissed`, `agentdesk.marketplace.catalog.v1`, `agentdesk.theme`, `agentdesk_session` and keychain service `agent-desk`.
- Wire and recorded identity: health and peer value `agent-desk`, User-Agents `AgentDesk/`, `agentdesk/0.1` and `agentdesk-probe`, peer derivation prefixes `agentdesk-peer-channel:` and `agentdesk-peer-token:`, audit actor `agent-desk`, Outlook Message-ID domain `agent-desk.local`, publisher `agent-desk`, wizard publisher `agent-desk-wizard`, existing DOM event `agentdesk:theme`, and the generic publisher route pattern.
- Commands and launchers: `python -m agentdesk.server`, `python -m agentdesk.probe`, `python -m agentdesk.presentations.cli`, `python -m agentdesk.registry`, `python -m agentdesk.validator`, parser names `agentdesk.probe`, `agentdesk.presentations`, `agentdesk.registry` and `agentdesk-validator`, `agent-desk.cmd`, `agent-desk.command`, `probe.cmd`, `probe.command`, `agent_desk_entry.py` and the existing start scripts.
- Public distribution: repository and clone folder `kanitmann01/agent-desk`, installer names, `AgentDesk.exe`, the `agentdesk.exe` update alias, the `agent-desk` bundle folder, `agent-desk-bundle`, `agent-desk.zip`, `AgentDesk` install and update shares, AppLocker BinaryName and the signing placeholder identity.
- Compliance metadata: SBOM application `agent-desk`, properties `agentdesk:license-file`, `agentdesk:license-exception`, `agentdesk:dev-dependency`, `agentdesk:stdlib-note`, `agentdesk:license-ref`, `agentdesk:sdk-license`, `agentdesk:bundle`, `agentdesk:python-runtime-dependencies`, `agentdesk:frontend-lockfile` and `agentdesk:frontend-lockfile-sha256`, and table `[tool.agent-desk-licenses]`.
- Legal text: the existing proprietary and SDK licence wording, copyright lines, plugin notices, generated third-party notice wording and the licensing guide's plugin-grant summary, only in their legal or generator contexts.

The list records purpose, owner and review trigger. Spec 032 does not remove an entry.

### The guard stage

- Replace the two-literal policy with the full inventory, structured allowlist, temporary list, count report and negative fixtures.
- Name enforcement is on from the first commit. The temporary list carries exactly what main still shows, so the untouched tree stays green while new old-brand text cannot land, and the guard's tests prove that injected drift fails.
- Keep the U+2014 rule enforced throughout.
- The three README screenshots are named on a dated retained-media list (their paths, the date, and the wave closeout retake as the review trigger). Nothing else in the guard looks at images. Refusing old branded media by SHA-256 fingerprint (story 24) becomes a follow-up issue, not part of this spec.
- Ticket 07 empties the temporary list of display surfaces, so no temporary baseline exception for display text survives the surface stage.

### The surface stage

- Change server-rendered and SPA copy together. Use one approved literal per runtime and pin both to the guard.
- Change the avatar to `NB` in both renderers and rebuild the committed SPA.
- Change live document families: README, the readme capture instructions, demo, glossary, frontend README and package description, distribution guide, marketplace guide and licensing guide prose.
- Correct the marketplace guide so the runtime data root and bundle install folder are separate facts. The runtime default remains `.agent-desk`; the bundle install contract remains `AgentDesk`.
- The three README screenshots are not replaced in this spec. They are retaken once in the final closeout of the wave, after Specs 030 and 031 have landed, by the README's screenshot capture command. This spec's surface stage first makes that command complete by adding the browser-install step its instructions leave out (story 60). Retaking the screenshots is then a single command, so the images update without hand work.
- Change Windows product, company and file-description fields, bundle manifest product and AppLocker rule name, description and ProductName condition. Keep filenames, artifact names, BinaryName and signing identity.
- Update Specs 030 and 031 before either starts. Spec 030's product decision becomes Nexuus Bot, its conflicting copy exclusion is removed or narrowed, and its dependency points to Spec 032. Spec 031 records the dependency and uses the new product name.
- Keep all compatibility identifiers exact. Live prose may explain them, but may not present them as the product wordmark.
- Rebuild and commit the SPA. The hosted workflow must find no committed-bundle diff.

### The package stage

- Rename the Python distribution to `nexuus-bot` and move the canonical package tree to `nexuusbot`.
- Move first-party imports, module entry points, package data references, frozen entry imports, build inputs and generated package inventories to the canonical name in one stage.
- Keep a small `agentdesk` compatibility package. It aliases the complete old subtree to canonical module objects, not to copies. Module identity is part of the contract.
- The canonical module commands exist, but published command names and launcher filenames do not change. The old module commands work through the alias.
- Include both the canonical package and the alias in packaged and frozen builds. The retained entry script keeps its filename and uses the canonical import.
- Rename the private frontend package and lockfile identity to `nexuusbot-dashboard-spa`. Move its production output to the canonical package tree. Keep the static mount and all browser URLs unchanged.
- Regenerate distribution metadata and the committed bundle. Do not hand-edit generated inventories.
- The old Python distribution name is not promised as an install alias. No published PyPI package was found. The compatibility promise is the old import path.

### Delivery order

1. Guard machinery, inventory, allowlist, temporary list, count report and negative fixtures land with name enforcement on and the untouched tree green. The stage ends with `7/7 gates passed` and `CI PASS`.
2. Surfaces, live documents, human-readable metadata and Specs 030 and 031 change. Name enforcement turns on. The rebuilt bundle is committed. The stage ends with `7/7 gates passed` and `CI PASS`.
3. The Python and frontend package identities move, the old import alias lands, and packaging and bundle tests prove both paths. The stage ends with `7/7 gates passed` and `CI PASS`.

## Testing Decisions

A good test drives a public seam and checks what a person can see, what a command returns, what an import resolves to or what a document says. It never asserts a private helper or a wall-clock time.

1. The naming guard (pytest): every inventory entry carries `Nexuus Bot`; old display forms and old avatar initials are absent outside exact exceptions; each allowlist entry is accepted only in its documented context; archive and legal exclusions are deliberate; U+2014 remains absent; injected missing-name, old-name, old-initial and unapproved-identifier fixtures fail. Prior art: `tests/test_brand_naming.py`.
2. Server-rendered surfaces (pytest): page titles, breadcrumbs, wordmarks, avatar title and initials, startup copy, authentication recovery, session copy, wizard copy and probe headers render the approved name. Use render functions and fixtures, not a running server. Prior art: `tests/test_server_spa.py`, `tests/test_ui_wave2.py`, `tests/test_probe_report.py`.
3. SPA surfaces (Vitest): tab title, rail wordmarks, avatar title and initials, session-expired copy, update banner and product-naming prompts use the approved name. Prior art: `frontend/src/test/shell.test.tsx`, `frontend/src/test/face-rail.test.tsx`, `frontend/src/test/brief-decisions.test.tsx`.
4. Generated and bundled output (pytest and static checks): presentation metadata, the committed SPA, Windows metadata fields, bundle manifest product and AppLocker rule names, descriptions and ProductName conditions carry the new name. Executable, artifact, BinaryName, SBOM and legal bytes keep their old contracts. Prior art: `tests/test_update_channel.py`, `tests/test_update_stage.py`, `tests/test_update_rollback.py`, `tests/test_sbom.py`.
5. Document families (pytest or a reading command): README and readme provenance, demo, glossary, frontend README and package description, distribution guide, marketplace guide, licensing guide, compatibility table and Specs 030 and 031 satisfy their stories. The marketplace guide states the data root and install folder separately. No instruction promises a missing installer.
6. README images: a test pins the three existing image hashes and the provenance note as unchanged by every stage of this spec. No application is started to make or check them.
7. Package identity (isolated subprocess tests): build and install the distribution in a temporary environment; import `nexuusbot`; import `agentdesk`; assert that corresponding submodules are the same objects; run every old module command with `--help` and assert its existing parser name; confirm generated distribution metadata. Prior art for launcher text and module invocation: `tests/test_agent_desk_cmd.py`, `tests/test_agent_desk_command.py`, `tests/test_probe_cmd.py`, `tests/test_probe_command.py`, `tests/test_registry_index.py` and `tests/test_validator_support.py`. No existing distribution-install or alias-identity test was found.
8. Registry plugins through both paths (pytest subprocesses): in one clean interpreter import the host through `nexuusbot`, and in another through `agentdesk`. In each, install, validate and render every plugin in the registry. Add a registry-plugin import fixture that imports a public host module through each path and returns the same value. Both runs must produce the same result. Prior art: `tests/test_plugins_runtime.py`, `tests/test_plugins_execute.py`, `tests/test_registry_publish.py`.
9. Frontend package and bundle: package name and lockfile identity equal `nexuusbot-dashboard-spa`; type-check and Vitest pass; a fresh production build equals the committed bundle; the static URL and browser storage keys are unchanged. Prior art: `frontend/src/test/tokens.test.ts`, `frontend/src/test/setup-strip.test.tsx`, `frontend/src/test/theme.test.tsx`.
10. Compatibility contracts (existing suites plus static contract checks): config precedence, calendar paths, data-root default, cookie, keychain, health, peers, all User-Agents, peer derivation prefixes, audit actor, Outlook Message-ID domain, theme key and event, temp names, publisher policy, publisher routes, updater paths, executable names and all SBOM metadata remain pinned. Tests use temporary roots and fake services, never the real user data folder. Prior art: `tests/test_config.py`, `tests/test_server_auth.py`, `tests/test_keys_store.py`, `tests/test_server_health.py`, `tests/test_peers_discovery.py`, `tests/test_peers_store.py`, `tests/test_llm_chat.py`, `tests/test_ledger.py`, `tests/test_server_ledger_api.py`, `tests/test_marketplace_policy.py`, `tests/test_update_channel.py`, `tests/test_update_stage.py`, `tests/test_update_rollback.py`, `tests/test_sbom.py` and `frontend/src/test/theme.test.tsx`.
11. Counts: repeat the R2 method on tracked text and tracked paths before and after. The baseline at `3540b9f` is 613 files, 3,240 content occurrences and 290 branded paths. At `0f622e3`, 86 files and 207 old visible occurrences remain. The required result is zero old display occurrences on live surfaces, zero old avatar renders, every inventory surface on the new name, and every remaining old identifier explained by one allowlist entry. Record the exact after-count; do not guess it.
12. Gates: each of the three stages ends with `7/7 gates passed` and `CI PASS`. Hosted CI rebuilds the SPA and fails on a committed-bundle diff. Bundle verification may inspect artifacts but must not launch the executable.

No test in this spec starts a real desk, a walk or the application. No test opens a browser against a live desk. No test reads, lists or changes the real user data folder. CLI checks stop at argument parsing. Packaging checks use temporary environments. Visual evidence is limited to committed images and reviewer readings.

## Out of Scope

1. The data folder `.agent-desk` and its config, templates, logs, PID, temp, backup, plugin-data and update-state names, plus the OneDrive calendar hint `agent-desk/calendar_sync.json`.
2. The `AGENTDESK_*` environment prefix and the two `__AGENTDESK_*` layout globals.
3. Browser keys `agentdesk.railCollapsed`, `agentdesk.setupDismissed`, `agentdesk.marketplace.catalog.v1` and `agentdesk.theme`.
4. Cookie `agentdesk_session` and keychain service `agent-desk`.
5. Health and peer identity `agent-desk`, User-Agents `AgentDesk/<version>`, `agentdesk/0.1` and `agentdesk-probe`, peer derivation prefixes `agentdesk-peer-channel:` and `agentdesk-peer-token:`, audit actor `agent-desk`, Outlook Message-ID domain `agent-desk.local`, existing DOM event `agentdesk:theme`, other custom event names, data attributes, API paths, URL schemes and product hostnames.
6. Publisher `agent-desk`, wizard publisher `agent-desk-wizard`, publisher route values and installed publisher records.
7. CLI command names, `agent-desk.cmd`, `agent-desk.command`, `probe.cmd`, `probe.command`, `agent_desk_entry.py` and the existing start scripts.
8. Repository and clone folder `kanitmann01/agent-desk`.
9. Installer names, `AgentDesk.exe`, the `agentdesk.exe` update alias, the `agent-desk` bundle folder, `agent-desk-bundle`, `agent-desk.zip`, `AgentDesk` install and update shares, AppLocker BinaryName and the signing placeholder identity.
10. SBOM application `agent-desk`, properties `agentdesk:license-file`, `agentdesk:license-exception`, `agentdesk:dev-dependency`, `agentdesk:stdlib-note`, `agentdesk:license-ref`, `agentdesk:sdk-license`, `agentdesk:bundle`, `agentdesk:python-runtime-dependencies`, `agentdesk:frontend-lockfile` and `agentdesk:frontend-lockfile-sha256`, and table `[tool.agent-desk-licenses]`.
11. Proprietary and SDK licence wording, copyright lines, plugin notices, generated third-party notice wording and the licensing guide's plugin-grant summary.
12. Historical archives, dated evidence, tickets, plans, ideas, research, old specs and design records.
13. An install alias for the old Python distribution name, a PyPI publication, a repository rename or a publisher migration.
14. Removing or contracting any compatibility alias. A later migration spec must set the support window.
15. Starting a real desk, running a walk, running the application or launching the built executable as part of this spec's tests.
16. Replacing the three README screenshots. They stay as they are through every stage of this spec; the surface stage only completes their capture instructions.

## Further Notes

### History in three lines

- On 2026-11-17, Agent Desk was renamed to Nexuus Bot through PR #122, with 48 changed paths; package, environment, data-folder identifiers and licence wording stayed unchanged.
- On 2026-11-21, Spec 017 reversed the name to Agent Desk because a surface must not name a product that is not on the machine.
- The reversal needed two fix-backs, first for bundle metadata, SBOM and build scripts, then for operator guides, demo and frontend documents, proving that manual renames outran their guard.

### Decisions the founder took on 2026-11-25

- The product and agent are Nexuus Bot.
- The scope is what people see and code names. The data folder and public distribution names are out.
- The README screenshots are not replaced during the rename; they stay as they are.
- The rename lands after the last wave audit closes and before Spec 030 starts. It is Spec 032.
- Main at `0f622e3` is the baseline. Its README already says Nexuus Bot and its guard has already been replaced.
- The seam-check defaults are the proposed cut until the founder approves, vetoes or changes them.

### What changes in Specs 030 and 031 and in the README

- Spec 030 changes its founder decision to say that both product and agent are Nexuus Bot. Its out-of-scope item against copy that speaks as Nexuus Bot is removed or narrowed to copy beyond the approved name. Its dependency now says Spec 032 completes the rename and guard before shell and face work starts.
- Spec 031 has no old product wordmark at baseline. It gains a dependency on Spec 032 and uses Nexuus Bot wherever it names the product. Its template decisions do not change.
- The README keeps its new title. Its three screenshots, their alt text and the provenance note stay as they are during this rename. Old operational identifiers stay and are labelled as compatibility contracts. This spec's surface stage also corrects three README sentences: the frontend prerequisite states the minimum Node version, the keychain sentence says only what the code does, and the screenshot capture instructions gain the browser-install step. After the package stage, its developer section names `nexuus-bot`, `nexuusbot` and the `agentdesk` alias. Its repository URLs, clone folder, launcher names and data-folder examples remain true.

### Dependencies

- The audit of the last wave closes its P0 and P1 findings before Spec 032 starts.
- Spec 032 lands before Spec 030 starts. Specs 030 and 031 are both updated before either begins implementation.
- No implementation starts from the narrower guard now on main. The full-surface guard is reopened first.

### Risks and mitigations

- The guard is too narrow again. Mitigation: an explicit inventory, path checks, negative fixtures and a count report.
- A partial package move breaks imports or frozen startup. Mitigation: one atomic package stage, a complete alias, module-identity tests and registry-plugin tests through both paths.
- Documents drift from the application. Mitigation: one story and one check per live document family.
- README images contradict the text. Mitigation: they stay unchanged in this rename, this spec pins their hashes, and their provenance note already labels the pre-rename source commit.
- A compatibility identifier is renamed by accident. Mitigation: exact allowlist contexts, dedicated stories and existing contract suites.
- Legal or public records drift. Mitigation: byte pins for legal files, SBOM identifiers, publisher records and external names.
- The committed SPA is stale. Mitigation: rebuild it in the surface and package stages, then require a clean hosted bundle diff.

### Follow-ups to file

- Refusing old branded media by SHA-256 fingerprint in the brand-leak gate, without storing the retired plaintext token (story 24).
- A separate founder-approved migration if any compatibility contract or public distribution identity should later move.
- A support-window review for the old import alias and retained contracts. Spec 032 sets no expiry.
- The built-in sample data's sample client is renamed to a fictional name in its own ticket, issue 347, ahead of the rename; Spec 032 does not touch it.
