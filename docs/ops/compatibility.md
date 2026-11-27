# Compatibility identifiers

The product and the agent are Nexuus Bot. The names in this table are
compatibility identifiers, not the product name and not a second
wordmark: each one is a data folder, environment variable, browser
key, wire identity, command, launcher, artifact, share, compliance or
legal contract that keeps its existing spelling so existing desks,
plugins, scripts and operator rules keep working.

This document is generated from `tools/naming/allowlist.json`, the
same structured allowlist the naming guard (`tools/naming_guard.py`)
reads. Edit the allowlist, then regenerate; a hand-edited table fails
the table tests:

    python tools/naming/generate_compatibility_table.py

One row per allowlist entry, in the allowlist's order. The exact
context column is the entry's own documented context: an identifier is
tolerated only there, never globally.

| Category | Identifier | Exact context | Owner | Review trigger |
| --- | --- | --- | --- | --- |
| import-compatibility | `agentdesk` | `The Python package tree's own module identity: import statements, module-path strings in docstrings and comments, logging namespaces, and internal code identifiers such as the AgentDeskServer class. Ticket 08 re-roots the tree to nexuusbot; afterwards this identifier is permitted only in the alias package (src/agentdesk as the shim), alias tests, plugin compatibility tests and compatibility documentation.` | Spec 032 stories 27 to 30, out-of-scope item 14 | A founder-approved migration spec setting the alias support window. |
| import-compatibility | `python -m agentdesk.server` | `The documented server module command; it keeps working through the alias after ticket 08, with its existing parser name.` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `python -m agentdesk.probe` | `The documented probe module command; it keeps working through the alias after ticket 08.` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `python -m agentdesk.presentations.cli` | `The documented presentations module command; it keeps working through the alias after ticket 08.` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `python -m agentdesk.registry` | `The documented registry module command; it keeps working through the alias after ticket 08.` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `python -m agentdesk.validator` | `The documented validator module command; it keeps working through the alias after ticket 08.` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `agentdesk.probe` | `The probe argparse parser name (python -m agentdesk.probe --help prints it).` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `agentdesk.presentations` | `The presentations argparse parser name.` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `agentdesk.registry` | `The registry argparse parser name.` | Spec 032 story 29 | A founder-approved migration spec. |
| import-compatibility | `agentdesk-validator` | `The validator argparse parser name.` | Spec 032 story 29 | A founder-approved migration spec. |
| data-and-local-state | `.agent-desk` | `The runtime data root default (~/.agent-desk or %USERPROFILE%\.agent-desk) with its config.env, templates, logs, PID, temp, backup, plugin-data and update-state names, including .agent-desk-backup, in code and in the documentation that explains it.` | Spec 032 story 35, out-of-scope item 1 | A founder-approved migration spec. |
| data-and-local-state | `agent-desk-data` | `The reserved alternate data-folder name; current occurrences live in the test tree only.` | Spec 032 out-of-scope item 1 | A founder-approved migration spec. |
| data-and-local-state | `agent-desk/calendar_sync.json` | `The OneDrive calendar hint file path and its search candidates.` | Spec 032 story 35, out-of-scope item 1 | A founder-approved migration spec. |
| data-and-local-state | `agent-desk` | `The OneDrive folder name in the calendar hint setup copy and search paths.` | Spec 032 story 35, out-of-scope item 1 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_DATA` | `The data-root override variable: name and precedence kept in code, tooling and operator documentation.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_CALENDAR_FILE` | `The calendar-file override variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_LLM_BASE` | `The LLM endpoint variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_LLM_KEY` | `The LLM key variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_LLM_MODEL` | `The LLM model variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_MAIL_FOLDER` | `The mail folder variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_MARKETPLACE_ADMIN` | `The marketplace admin-mode variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_REGISTRY` | `The registry path override variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_TEMPLATES` | `The templates override variable: name and precedence kept.` | Spec 032 story 36, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `AGENTDESK_` | `The environment prefix in prefix-handling code and tooling checks (the prefix as display text stays rejected).` | Spec 032 out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `__AGENTDESK_LAYOUT_STRESS__` | `The layout stress-test global and its reads.` | Spec 032 story 37, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `__AGENTDESK_LAYOUT_TRIPLED__` | `The layout tripled-test global and its reads.` | Spec 032 story 37, out-of-scope item 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-ci-` | `Temporary directory prefix of the local CI gate.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-base-index-` | `Temporary file prefix of the registry base index in the CI gate.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-smoke-` | `Temporary directory prefix of bundle smoke checks.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-walkthrough-` | `Temporary directory prefix of walkthrough runs.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-ready-` | `Temporary directory prefix of demo readiness checks.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-engine-smoke-` | `Temporary directory prefix of engine sidecar smoke checks.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-feedback-` | `Temporary directory prefix of feedback walkthrough runs.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-layout-` | `Temporary directory prefix of layout audit runs.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-bundle-` | `Temporary directory prefix of bundle build work.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-wizard-` | `Temporary directory prefix of wizard runs.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-selfcheck-` | `Temporary directory prefix of server selfchecks.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-publish-` | `Temporary directory prefix of registry publish runs.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-registry-` | `Temporary directory prefix of registry work in the server and CI.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-marketplace` | `Temporary name prefix of marketplace work.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-update-` | `Temporary directory prefix of update staging work.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-peer-` | `Temporary directory prefix of peer work.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-probe-` | `Temporary directory prefix of probe runs.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-shadow` | `The Excel shadow store name.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk-face-` | `Temporary directory prefix of face walkthrough runs.` | Spec 032 out-of-scope items 1 and 2 | A founder-approved migration spec. |
| environment-and-tooling | `agentdesk_mock_endpoint` | `The module name the walk tools load tools/mock_endpoint.py under.` | Spec 032 tooling contract | A founder-approved migration spec. |
| environment-and-tooling | `agent-desk-core` | `The provenance comment in settings.py naming the development sandbox where spec 028 was authored.` | Spec 032 ticket 01a classification | The next edit of that comment. |
| browser-and-secrets | `agentdesk.railCollapsed` | `Browser storage key for the rail collapsed state, in the SPA source, the committed bundle, the server-rendered fallback script and the walkthrough tools.` | Spec 032 story 38, out-of-scope item 3 | A founder-approved migration spec. |
| browser-and-secrets | `agentdesk.setupDismissed` | `Browser storage key for the get-started dismissal state.` | Spec 032 story 38, out-of-scope item 3 | A founder-approved migration spec. |
| browser-and-secrets | `agentdesk.marketplace.catalog.v1` | `Browser storage key for the marketplace catalog cache.` | Spec 032 story 38, out-of-scope item 3 | A founder-approved migration spec. |
| browser-and-secrets | `agentdesk.theme` | `Browser storage key for the theme choice.` | Spec 032 story 38, out-of-scope item 3 | A founder-approved migration spec. |
| browser-and-secrets | `agentdesk_session` | `The session cookie name in the server auth code and its tests.` | Spec 032 story 39, out-of-scope item 4 | A founder-approved migration spec. |
| browser-and-secrets | `agent-desk` | `The OS keychain service name in the keys store.` | Spec 032 story 40, out-of-scope item 4 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agent-desk` | `The health and peer identity value (APP_NAME) in the health endpoint and peer discovery.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `AgentDesk/` | `The server User-Agent prefix AgentDesk/<version>.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agentdesk/0.1` | `The probe User-Agent.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agentdesk-probe` | `The probe client User-Agent suffix.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agentdesk-peer-channel:` | `The peer channel derivation prefix.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agentdesk-peer-token:` | `The peer token derivation prefix.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agent-desk` | `The audit actor value recorded in audit stores.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agent-desk.local` | `The Outlook Message-ID domain in the feeder writer, the WPN collector and the Outlook export script.` | Spec 032 story 41, out-of-scope item 5 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agent-desk` | `The plugin publisher identity: manifests, catalog records, publisher route values, installed publisher records, walkthrough fixtures and the authoring example.` | Spec 032 story 43, out-of-scope item 6 | A founder-approved migration spec. |
| wire-and-recorded-identity | `/publisher/` | `The generic publisher route pattern: the marketplace API dispatches routes starting /publisher/ to a publisher page whose name segment carries existing publisher ids such as agent-desk (src/agentdesk/marketplace/api.py get_publisher, and the frontend marketplace router).` | Spec 032 story 43, out-of-scope item 6 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agent-desk-wizard` | `The wizard publisher identity.` | Spec 032 story 43, out-of-scope item 6 | A founder-approved migration spec. |
| wire-and-recorded-identity | `agentdesk:theme` | `The existing theme DOM event name.` | Spec 032 story 42, out-of-scope item 5 | A founder-approved migration spec. |
| commands-and-launchers | `agent-desk.cmd` | `The Windows launcher: its filename is retained and its printed text names the product (ticket 02 renames the print, never the filename).` | Spec 032 stories 44 and 45, out-of-scope item 7 | A founder-approved migration spec. |
| commands-and-launchers | `agent-desk.command` | `The macOS launcher: its filename is retained; its printed text is ticket 02's.` | Spec 032 stories 44 and 45, out-of-scope item 7 | A founder-approved migration spec. |
| commands-and-launchers | `probe.cmd` | `The Windows probe launcher: its filename is retained; its printed text is ticket 02's.` | Spec 032 stories 44 and 45, out-of-scope item 7 | A founder-approved migration spec. |
| commands-and-launchers | `probe.command` | `The macOS probe launcher: its filename is retained; its printed text is ticket 02's.` | Spec 032 stories 44 and 45, out-of-scope item 7 | A founder-approved migration spec. |
| commands-and-launchers | `agent_desk_entry.py` | `The frozen entry script: its filename is retained; ticket 08 keeps the filename and points its import at the canonical package.` | Spec 032 story 45, out-of-scope item 7 | A founder-approved migration spec. |
| commands-and-launchers | `test_agent_desk` | `The tests of the retained launchers; a path may keep an old form as a test of a retained launcher.` | Spec 032 path rule, implementation decisions | A founder-approved migration spec. |
| public-distribution | `kanitmann01/agent-desk` | `The repository and clone URLs and the provenance record.` | Spec 032 story 46, out-of-scope item 8 | A founder-approved migration spec. |
| public-distribution | `cd agent-desk` | `The clone folder name in the checkout instructions.` | Spec 032 story 46, out-of-scope item 8 | A founder-approved migration spec. |
| public-distribution | `dist/agent-desk` | `The built artifact folder name in the build script, the SBOM bundle property value, the distribution guide and CI.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `agent-desk.zip` | `The update artifact name.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `agent-desk-bundle` | `The bundle artifact name in the hosted workflow.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `agentdesk.exe` | `The update alias executable name beside AgentDesk.exe.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `AgentDesk.exe` | `The installer executable name and the AppLocker BinaryName.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `%LOCALAPPDATA%\AgentDesk` | `The bundle install folder contract in the operator guides.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `%LOCALAPPDATA%.\\AgentDesk` | `The bundle install folder contract as spelled in the build tool's selfcheck source literal.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `fileserver\agentdesk` | `The AgentDesk install and update share names in the distribution guide.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `agentdesk.xml` | `The exported AppLocker policy file name in the distribution guide.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| public-distribution | `cn=agent desk, o=agent desk` | `The signing placeholder identity in the AppLocker template.` | Spec 032 story 47, out-of-scope item 9 | A founder-approved migration spec. |
| compliance-metadata | `agent-desk` | `The SBOM application name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:license-file` | `The SBOM licence-file property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:license-exception` | `The SBOM licence-exception property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:dev-dependency` | `The SBOM dev-dependency property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:stdlib-note` | `The SBOM stdlib-note property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:license-ref` | `The SBOM licence-ref property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:sdk-license` | `The SBOM SDK licence property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:bundle` | `The SBOM bundle property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:python-runtime-dependencies` | `The SBOM runtime dependency property name.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agentdesk:frontend-lockfile` | `The SBOM frontend-lockfile property name and its sha256 variant.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| compliance-metadata | `agent-desk-licenses` | `The licence table identifier [tool.agent-desk-licenses] and its programmatic reads.` | Spec 032 story 48, out-of-scope item 10 | A founder-approved migration spec. |
| legal-text | `Agent Desk bundles third-party components` | `The generated third-party notice wording in its generator; the committed file is excluded as a notice file.` | Spec 032 story 49, out-of-scope item 11 | A founder-approved migration spec. |
| legal-text | `The Agent Desk core itself is proprietary` | `The generated third-party notice wording in its generator; the committed file is excluded as a notice file.` | Spec 032 story 49, out-of-scope item 11 | A founder-approved migration spec. |
| legal-text | `Agent Desk core` | `The licensing guide's licence-table row for the proprietary core.` | Spec 032 story 49, out-of-scope item 11 | A founder-approved migration spec. |
| legal-text | `grants Agent Desk` | `The licensing guide's plugin-grant summary.` | Spec 032 story 49, out-of-scope item 11 | A founder-approved migration spec. |
