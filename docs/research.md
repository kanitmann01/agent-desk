# Enterprise Personal Agent: Assemble vs Build Research

Research run 2026-11-10/11 via four parallel research subagents (frameworks, plugin architectures, dashboard stack, enterprise distribution + landscape). All load-bearing claims verified against primary sources (GitHub LICENSE files, PyPI metadata, official docs) by the subagents; source URLs included per section.

> **v2 (2026-11-11, post-audit hardening):** an external audit was reviewed claim-by-claim against primary sources. Its architectural, Windows-enterprise, and security recommendations are ACCEPTED and now binding (section A9). Several of the audit's own factual "hallucination" claims were themselves contradicted by primary sources (A9.1). Sections A8.6 and A8.8 are superseded by A9.3. Read A9 before citing anything above it.

## 0. Requirements (as stated by the manager)

- Locked-down corporate Windows laptop (macOS nice-to-have). No admin rights.
- Install as a user-space script / CMD command. No elevation, no MSI, no registry.
- Bring-your-own-LLM: corporate OpenAI-compatible endpoint and key already available.
- Product shape: personalized dashboard where the user picks widgets/plugins:
  1. Excel sales file: show changes in the last 24 hours
  2. Calendar: pull the most important task, break it into subtasks/follow-ups
  3. Auto-research: paste what you did, agent researches and surfaces findings
- Plugin SDK so people can write their own plugins; central plugin repository; requirements expected to grow.
- Licensing: permissive only, enterprise-usable without source disclosure. User asked for "MIT or an adaptive license usable without attribution".

### License framing note (important for the legal conversation)

MIT, Apache-2.0, and BSD all require keeping the copyright/license notice in copies or documentation. That is not user-visible attribution and enterprises normally accept it. Truly zero-attribution licenses are 0BSD, Unlicense, CC0. Copyleft (GPL/AGPL/LGPL), SSPL, BSL, fair-code (n8n), and restricted licenses (Open WebUI branding clause, LobeHub, Dify's modified Apache) are excluded by policy.

## 1. Verdict

**Assemble the engine patterns, build the product.** The widget-dashboard personal agent for a locked-down corporate laptop does not exist off the shelf as of Nov 2026. What is solved and MIT/Apache/BSD-licensed: agent loops, BYO OpenAI-compatible endpoints, skills standards, scheduling, plugin manifest discipline, registry patterns. What nobody ships: the no-admin lockdown delivery, the personalized widget grid, and an IT-approvable governance wrapper. Those three are the actual build work, and they are small.

Two viable paths:

- **Path A (recommended for v1): thin custom Python core + NiceGUI dashboard + our plugin spec.** A small app: openai-python (Apache-2.0) against the corporate endpoint, optional Pydantic AI (MIT) for typed agent calls, APScheduler (MIT) for refresh, NiceGUI (MIT) for the widget grid served on 127.0.0.1, opened in the installed browser. Plugin system borrowed from the best patterns below (manifest validated before code runs, declarative vs code plugin classes, capability broker, git-repo registry). Smallest footprint, easiest IT conversation, no Node runtime, delete-folder uninstall.
- **Path B (if autonomous assistant behavior is also wanted): Hermes Agent core + our dashboard as a front-end.** Hermes (MIT, Nous Research, ~262k stars) already solves memory, self-written skills, cron, 20+ messaging channels, any-endpoint LLMs, and a native Windows user-space install to %LOCALAPPDATA%. Its plugin surface is Python, ideal for pandas/Excel widgets. Cost: it bundles Python+Node, moves fast (v0.23.x), and its UI is TUI/chat/desktop, not a widget grid; the dashboard is still ours to build. Use Hermes "taps" (git repos) as the plugin registry mechanism if this path is chosen.

Both paths converge on the same plugin spec and registry design (section 3) and the same no-admin delivery mechanics (section 4).

## 2. Framework inventory (verified)

| Framework | License | Windows user-space | BYO endpoint | Plugins | UI | Status (Nov 2026) |
|---|---|---|---|---|---|---|
| OpenClaw | MIT (OpenClaw Foundation) | Yes: install.ps1 / npm -g | Yes (models.providers custom base URL) | Plugin SDK + ClawHub marketplace + skills | Web Control UI, TUI, native apps | 394k stars, v2026.11.3, extremely active |
| Hermes Agent | MIT | Yes: PowerShell one-liner to %LOCALAPPDATA%\hermes | Yes, any endpoint | Skills (agentskills.io) + plugins + MCP | TUI + Desktop app + 6 chat channels | 262k stars, v0.23.1 (2026-11-10) |
| ZeroClaw | MIT OR Apache-2.0 | Yes: prebuilt zip to ~\.zeroclaw\bin, user PATH | Yes, any OpenAI-compatible | Provider crates, tools, MCP | Built-in web dashboard + cron | 33k stars, v0.8.7, pre-1.0 |
| Letta (letta-code) | Apache-2.0 | Yes (npm -g / uv tool) | Yes via /connect (custom base URL partially verified) | Skills from GitHub/ClawHub/Hermes hubs | TUI + hosted chat | repo pivot in 2026; some features account-gated |
| Microsoft Agent Framework | MIT | Yes (pip) | Yes | Middleware, skills, MCP | DevUI | Successor to AutoGen + SK; v1.25.0 |
| AutoGen | code MIT, repo CC-BY-4.0 | pip | Yes | AgentChat | Studio (archived) | ARCHIVED, do not build on it |
| CrewAI | MIT | pip | Yes (LLM base_url + LiteLLM) | Tools, Flows, skills | None OSS (commercial AMP) | 60.7k stars; telemetry ON by default, opt-out env var |
| LangChain / LangGraph | MIT / MIT | pip | Yes (base_url; standard-OpenAI caveat) | Integrations; Deep Agents harness | langgraph dev local server; Studio is cloud | 149k / 44.8k stars |
| Semantic Kernel | MIT | pip / per-user dotnet | Yes (inject AsyncOpenAI) | Plugins (code, OpenAPI, MCP) | none (library) | maintenance track; MAF is the successor |
| Pydantic AI | MIT | pip/uv | Yes (OpenAIProvider base_url, OpenAICompatibleProvider) | Tools, toolsets, MCP | clai CLI, no dashboard | 21.1k stars, v2.67.0 |
| Google ADK | Apache-2.0 | pip (Py 3.11+) | Yes via LiteLLM api_base | Built-in + MCP + OpenAPI | adk web dev UI | 22.2k stars |
| smolagents | Apache-2.0 | pip | Yes (OpenAIServerModel api_base) | Tools from MCP/Hub | GradioUI built in | 30.3k stars |
| Open Interpreter (Rust) | Apache-2.0 now; legacy Python 0.4.x is AGPL-3.0 | irm install.ps1 | Yes | Skills, Codex SDK protocol | TUI | young 0.0.x; license history tangled, avoid PyPI package |
| NanoClaw | MIT | No: Docker/WSL2 required | Partial | /add- skills | none by design | excluded for this use case |
| IronClaw (NEAR AI) | MIT OR Apache-2.0 | Mostly (PowerShell script; MSI may trigger UAC) | Yes (base_url in resolution) | WASM tools, MCP | Local WebUI (SSE/WS) | 12.7k stars |

License-history flags:
- LangChain: no license change (MIT throughout; LICENSE last touched 2023-11-29). Confirmed via commits API.
- Open Interpreter: current Rust repo Apache-2.0 (history reset 2025-04-16); the famous Python line is AGPL-3.0 (PyPI open-interpreter 0.4.x). Do not pin anything from PyPI.
- AutoGen: root CC-BY-4.0 (docs/media), code MIT via LICENSE-CODE; archived regardless.

Top 3 as a backbone: 1) OpenClaw (only one shipping plugin SDK + central registry + Control UI together), 2) Hermes Agent (best locked-down-Windows footprint, Python plugin surface, skills standard), 3) ZeroClaw (single Rust binary, built-in dashboard, dual MIT/Apache licensing; cost is Rust for deep plugins).

## 3. Plugin architecture: findings and recommended spec

### 3.1 "DSH plugin architecture" is real

DeepSeek Harness (dsh), github.com/deepseek-ai/deepseek-harness, MIT, ~278k stars, TypeScript. Tagline: "Everything is a Plugin." Built on Cordis; plugins declare a `dsh` field inside package.json; composition is config-patch based (ordered layers, patches replace config rows by id); "there is no privileged core to patch". Explicit developer preview with breaking changes. No marketplace; discovery via the GitHub topic `dsh-plugin`.

Verdict: mine it for ideas (everything behind stable service interfaces, reversible registrations), do not copy wholesale; the config-patch model is esoteric and unstable, and it has no registry story.

### 3.2 What the successful systems share

| System | Manifest | Sandboxing | Registry | License |
|---|---|---|---|---|
| OpenClaw | openclaw.plugin.json, configSchema JSON-Schema validated before code runs | in-process, explicitly NOT sandboxed | ClawHub with lockfile + signed verify | MIT |
| Hermes | SKILL.md (agentskills.io) + plugin.yaml | Python in-process, write_approval staging for self-authored skills | Skills Hub + git "taps" | MIT |
| DSH | dsh field in package.json + cordis.patch.yml | in-process reversible effects | none (GitHub topic) | MIT |
| VS Code | package.json contributes + activationEvents | extension host, API-mediated | Marketplace; .vsix offline install | per-extension |
| Raycast | package.json commands/preferences (host-rendered prefs) | host-rendered UI | Raycast Store | per-extension |
| HACS | hacs.json + HA manifest.json | none (downloader) | curated git list + custom repos | MIT |
| Dify | manifest.yaml with explicit resource.permission block | separate plugin daemon, runtime-enforced permissions | marketplace with risk levels, OSV scan, air-gapped repack | Apache-2.0 + 2 extra conditions (not OSI-clean) |
| Chrome MV3 | manifest.json permissions tiers | multi-process sandbox | Web Store review | platform |
| Zed | extension.toml, WASM sandbox | real sandbox | git repo as registry, PRs reviewed | per-extension |
| OpenAI Codex plugins | plugin.json + marketplace.json with policy blocks | per policy | admin-pinnable local/git marketplaces | platform |

Common pattern: one declarative manifest read before any code executes; declarative contributions separated from executable code; least-privilege permission declaration; host-rendered settings; lazy activation; central discovery is usually just a curated index in git; semver + lockfile + releases; local validator identical to registry CI; corporate review = risk labels + scanning + offline install + admin-pinned sources.

### 3.3 Recommended plugin spec (the build part)

Two plugin classes, the single most important enterprise choice:

- **Class D (declarative):** manifest + skills + widget templates. No executable plugin code; the host interprets them. Installs with a prompt only. Covers most widgets (Excel delta, calendar breakdown, research prompts).
- **Class C (code):** ships a worker (Node or Python) talking IPC through a capability broker; never raw fs/net. Requires explicit approval, and in enterprise mode an admin allowlist.

Manifest (condensed example for the sales widget):

```json
{
  "schemaVersion": 1,
  "id": "sales-delta-widget",
  "name": "Sales 24h Delta",
  "version": "1.2.0",
  "publisher": "acme-tools",
  "class": "declarative",
  "engines": { "dashboardHost": ">=1.0.0 <2.0.0" },
  "license": "MIT",
  "permissions": {
    "filesystem": { "read": ["${workspace}/reports/*.xlsx"], "write": ["${pluginData}"] },
    "network": { "allow": [] },
    "llm": { "allow": true, "maxTokensPerDay": 200000 },
    "shell": "none"
  },
  "optionalPermissions": {
    "network": { "allow": ["https://api.acme.example.com/*"], "userPrompt": "Compare against the live sales API?" }
  },
  "activationEvents": ["onWidget:sales-delta", "onSchedule:0 * * * *"],
  "contributes": {
    "widgets": [{ "id": "sales-delta", "title": "Sales 24h Delta", "size": "2x1",
                  "refresh": { "cron": "0 * * * *" },
                  "dataSource": { "type": "excel-watch", "file": "${workspace}/reports/sales.xlsx", "deltaWindow": "24h" },
                  "render": { "type": "ui-schema", "file": "widget.ui.json" } }],
    "skills": ["skills/sales-summary/SKILL.md"],
    "preferences": [{ "name": "thresholdPct", "type": "number", "default": 5, "title": "Alert threshold (%)" }]
  }
}
```

- Lifecycle: discover (fetch index.json from pinned sources) -> install (zip pinned by hash into %LOCALAPPDATA%\<Host>\plugins\<id>\<semver>, validate manifest + permissions WITHOUT running anything) -> enable (secrets prompted, stored in Windows Credential Manager, user scope) -> lazy activation on activationEvents -> semver updates with lockfile plugins.lock.json -> uninstall preserves ${pluginData} until confirmed.
- Permission model: deny by default; no shell in v1 for any class; LLM calls proxied through the host so plugins never see the endpoint or key; every broker call logged (plugin id, capability, target, timestamp) for the audit trail; skills are content, not code, with a review queue for agent-modified skill files (Hermes write_approval pattern).
- Central repository: one internal git repo; root index.json (Zed extensions.toml + Codex marketplace.json shape) listing id, publisher, latest, risk level, class, releases with sha256 + git tag; publishing is a PR that CI checks with the same validator the client runs (manifest schema, permission lint rejecting shell/unscoped fs, OSV dependency scan, hash consistency). Escape hatch: add-source-by-URL for power users, off by default in enterprise mode; offline file-path mirror supported.
- SDK: template repo + `<host> plugin validate .` where the validator is byte-identical to registry CI (the Dify/Hermes trick that prevents "passes locally, rejected by store").

Provenance: manifest-before-code from OpenClaw + Dify; activationEvents + contributes from VS Code; permission tiers from Chrome + Dify; host-rendered preferences from Raycast; capability broker/daemon from Dify; git index + PR review from Zed + HACS; lockfile from OpenClaw; SKILL.md standard from agentskills.io (Hermes/OpenClaw/Letta interop).

## 4. Dashboard stack (all licenses verified from LICENSE files)

| Approach | License | Notes |
|---|---|---|
| NiceGUI (recommended) | MIT | asyncio-native, ui.timer per-widget refresh, Quasar grid, ~150-300 MB, pip --user/uv |
| Plotly Dash (fallback A) | MIT | dcc.Interval callbacks, Flask threads + APScheduler, ~120-250 MB, most mature |
| FastAPI + React bundle (fallback B, max control) | FastAPI MIT, Starlette/Uvicorn BSD-3, React/Vite/Recharts MIT, ECharts Apache-2.0 | served on localhost; pywebview (BSD-3) + WebView2 (preinstalled Win 10/11) as native shell |
| Streamlit | Apache-2.0 | full-script rerun model fights always-on multi-widget dashboards |
| Gradio | Apache-2.0 | chat/demo oriented, weak dashboard grid |
| Panel | BSD-3 | viable, Bokeh-weight |
| Reflex | Apache-2.0 | ships Bun; VC++ redistributable usually needs admin: risky on locked-down laptops |

Widget building blocks: python-calamine (MIT, fast Excel), pandas (BSD-3), openpyxl (MIT, .xlsm/formulas), APScheduler (MIT), openai-python (Apache-2.0), tavily-python (MIT) or Brave/Serper HTTPS.

### License traps (verified, exclude)

- Grafana, Metabase, ToolJet: AGPL-3.0.
- Open WebUI: custom license, BSD-3 base + branding-preservation clause + CLA (drifted from MIT 2023).
- LobeChat/LobeHub: "Community License", Apache-2.0 + derivative-distribution restrictions.
- MongoDB: SSPL; hidden dependency of LibreChat (MIT itself) and HF chat-ui. Meilisearch: MIT AND BUSL-1.1.
- recurring-ical-events: LGPL-3.0 (expand RRULEs via python-dateutil instead, Apache-2.0/BSD dual).
- n8n: Sustainable Use License (fair-code), not open source. Flowise: EOL Aug 31, 2026. Dify: modified Apache-2.0 (internal single-tenant use permitted, but a legal-review item; architecture is fine to copy, code is not).
- pywin32: PSF-2.0, permissive but off the literal allow-list (so is Python itself); get a one-line policy ruling.

### Calendar access reality (locked-down corporate Windows)

Delegated Graph Calendars.Read needs no admin consent at Microsoft defaults, but most corporate tenants restrict user consent and often disable app registration. Realistic paths in order: (a) small IT ask, admin grants delegated consent for one user (zero-install, best); (b) Outlook COM automation via pywin32 from a user script, no admin, but object-model guard prompts depend on AV state; design for a one-time prompt; (c) zero-IT fallback: export/subscribe calendar to .ics and parse with icalendar (BSD-2), expanding recurrences manually.

### Auto-research widget

Search APIs (Tavily/Brave/Serper) are ToS services, no license issue; concerns are data egress and audit: send only derived search phrases, never raw internal text; log every outbound query; prefer whatever search endpoint IT already sanctions (Azure AI Search/Bing) as a swap-in; keep summarization on the corporate OpenAI-compatible endpoint via openai-python base_url.

## 5. No-admin delivery mechanics (Windows)

First gate to test: does unsigned code execute from the user profile at all? If the org enforces strict WDAC (App Control for Business), only an IT exception, an already-allowlisted runtime, or a browser-only surface works. AppLocker default rules block user-writable paths once enforced; its script collection only covers PS1/BAT/VBS, so the gate is whether python.exe/node.exe may run.

Runtime: Python embeddable zip (no MSI, no registry; enable site-packages in the ._pth, bootstrap pip via get-pip.py) or uv standalone installer (MIT/Apache-2.0, installs to ~\.local\bin, UV_UNMANAGED_INSTALL for one-shot bootstrap) or the python NuGet package (useful where corporate Artifactory NuGet feeds exist but PyPI is blocked). WinPython for a full offline zip (~4 GB).

Most common real failure: TLS inspection. pip >= 24.2 uses the Windows truststore by default (helps); otherwise export the corporate root CA, set REQUESTS_CA_BUNDLE / SSL_CERT_FILE, or pip install pip-system-certs; npm analog NODE_EXTRA_CA_CERTS. Python 3.13+ enables VERIFY_X509_STRICT which can break older inspection appliance CA certs. Ship CA bundle path + HTTPS_PROXY as first-class settings.

Bootstrap pattern that survives: one .cmd (not .ps1; execution policy GPO ignores -ExecutionPolicy flags) that extracts the embeddable Python, writes user env vars, installs from the corporate mirror if present, starts the server on 127.0.0.1, opens the default browser. Recurring jobs: per-user Scheduled Tasks (creatable without admin) or in-process APScheduler. Hygiene: everything under %LOCALAPPDATA% or Documents, uninstall = delete folder, plus a one-page "what this writes" doc for the IT conversation. VS Code User Setup (per-user install + portable mode) is the precedent IT orgs already accept.

## 6. Landscape adaptation (Nov 2026)

- a16z Top 100 (Oct 2026): consumer personal agents broke out (Muse, Dots, Grok Bot; startups Instinct/Tomo/Poke/Lindy/Town at hundreds of thousands of users); nothing in it claims enterprise personal-agent delivery; usage skews to power users.
- BYOA ("bring your own agent") is the governance discourse: Okta 2026 finds 52% of employees admit unapproved AI tools; Gartner 69% suspect shadow GenAI; Netskope 47% of work GenAI users on personal apps. IT wants a sanctioned path; that is the opening for this tool.
- OpenClaw went foundation-governed (501(c)(3)) and launched OpenClaw Enterprise (Sep 30, 2026, MIT, self-hosted control plane, "Kubernetes for agents", with Red Hat and Nvidia), motivated by orgs banning agent platforms outright. Server-oriented, not a laptop personal agent.
- Governance patterns CISOs converge on (Arcade/Zenity/Dataiku/Kestra): agent/tool registry under version control, scoped credentials, approval gates, immutable audit trail, risk-level review. The plugin spec in section 3 is designed to slot into exactly this: manifest, named owner, audited actions.
- Precedents of assembling from MIT/Apache: LangGraph ~400 named enterprise deployments; Microsoft Agent Framework (AutoGen+SK successor) as the Microsoft-shop base; Hermes itself began as Nous's internal productivity tool. Nobody publishes a ready-made "personal agent in a box" that is simultaneously permissive-licensed, enterprise-governed, and packaged for locked-down user-space Windows. That combination is the white space.

## 7. Recommended plan

1. Probe (day 1): test on the manager's actual laptop: can an embeddable-Python hello-world run from %LOCALAPPDATA%? Does pip reach PyPI or is a mirror/CA needed? Is WebView2 present? This decides Path A feasibility before any design work.
2. v1 (2-4 weeks): Path A skeleton: .cmd bootstrap + embeddable Python + NiceGUI dashboard on 127.0.0.1 + the three widgets hardcoded (calamine/pandas delta; .ics or COM calendar; research via corporate LLM + sanctioned search). No plugin system yet; prove IT-acceptability and manager value.
3. v2: introduce the plugin spec (Class D first: manifest + widget templates + SKILL.md), internal git index.json registry, validator CLI, lockfile. Ship the sales widget as the first plugin to prove the SDK.
4. v3 (optional): Class C workers via capability broker, admin allowlist mode, audit export; or adopt Hermes as an engine sibling if autonomy/messaging channels get requested.
5. Legal: keep every dependency on the MIT/Apache/BSD allow-list (section 4); file the one-line PSF ruling; never pull open-interpreter from PyPI (AGPL).

## Sources

Frameworks: github.com/NousResearch/hermes-agent; github.com/openclaw/openclaw (+ docs.openclaw.ai/plugins/manifest, docs.openclaw.ai/concepts/model-providers, clawhub.ai); github.com/zeroclaw-labs/zeroclaw (+ setup/windows.md); github.com/letta-ai/letta-code; github.com/microsoft/agent-framework; github.com/microsoft/autogen; github.com/crewAIInc/crewAI (+ docs.crewai.com/telemetry); github.com/langchain-ai/langchain, /langgraph, /deepagents; github.com/microsoft/semantic-kernel; github.com/openinterpreter/openinterpreter (+ github.com/endolith/open-interpreter); github.com/pydantic/pydantic-ai (+ pydantic.dev/docs/ai/models/openai); github.com/google/adk-python; github.com/huggingface/smolagents; github.com/nanocoai/nanoclaw; github.com/nearai/ironclaw.

Plugin architectures: github.com/deepseek-ai/deepseek-harness (+ docs/architecture.md, github.com/topics/dsh-plugin); hermes-agent.nousresearch.com/docs/user-guide/features/plugins, /developer-guide/plugins, /marketplace; agentskills.io/specification; code.visualstudio.com/api (extension anatomy, publishing); developers.raycast.com/information/manifest.md; hacs.xyz/docs/publish/start; docs.dify.ai (plugin manifest, marketplace submission) + github.com/langgenius/dify; developer.chrome.com/docs/extensions/reference/manifest; zed.dev/docs/extensions/developing-extensions + github.com/zed-industries/extensions; developers.openai.com/plugins/build/plugins.

Dashboard stack: LICENSE files of streamlit, gradio, plotly/dash, holoviz/panel, reflex-dev/reflex, zauberzeug/nicegui, widgetti/solara, fastapi, pydantic/pywebview; PyPI JSON for openpyxl, python-calamine, apscheduler, icalendar, recurring-ical-events, tavily-python, uv; LibreChat + .env.example; lobehub/lobe-chat LICENSE; open-webui LICENSE + LICENSE_HISTORY; grafana, metabase, ToolJet, mongodb, meilisearch, apache/superset, getredash/redash LICENSEs; learn.microsoft.com (Graph permissions reference, Entra consent management, Outlook object model security, WebView2 distribution).

Enterprise mechanics + landscape: learn.microsoft.com (AppLocker overview, execution policies, WebView2 evergreen-vs-fixed); docs.astral.sh/uv (installer, storage); python.org/downloads/windows; nuget.org/packages/python; winpython.github.io; pip.pypa.io/topics/https-certificates; urllib3 issue #5110; code.visualstudio.com/docs/setup/windows + portable; a16z.com/100-gen-ai-apps-7; qz.com/openclaw-enterprise-ai-agent-control-plane-093026; openclaw.org; okta.com/newsroom/articles/ai-agents-at-work-2026; arcade.dev/blog/ai-agent-governance-compliance; zenity.io/blog/ai-agent-governance; kestra.io (+ Businesswire GA announcement); wavect.io/blog/internal-ai-agent-marketplace; action.deloitte.com (agent marketplaces insight); flowiseai.com/sunset; blog.n8n.io/announcing-new-sustainable-use-license; onyx.app/insights/best-enterprise-openclaw-options-2026.

---

# Addendum (2026-11-11, second research pass): the autonomy layer

Scope expansion from the manager: proactive research/suggestions, auto-skill creation from repeated manual tasks, automatic people-interaction memory, pre-meeting briefings, and English-described plugins authored by the agent for non-coders. Two further research agents verified the following.

## A8.1 Capability map: what exists vs what we build

| Capability | Exists today (precedent) | What we build | Verdict |
|---|---|---|---|
| Proactive research, topics, prompting the user | Hermes cron + deliver: to 20+ channels (fresh session per run, output auto-delivered, no inbound prompt needed), /heartbeat (idle-only, NO_REPLY guard, missed-tick coalescing), /goal persistent loops; OpenClaw automations + 30-min proactive check with idleOnly + activeHours | Nudge-budget dispatcher (per-category rate caps, global daily budget, digest batching, quiet hours); topic-watcher standing prompts per domain | ~70% copy |
| Detect task done 5+ times, propose/auto-create a skill | Hermes skill_manage + skills.write_approval staging (~/.hermes/pending/skills/, /skills diff|approve|reject) + curator lifecycle (stale at 14d, archive at 30d, consolidation ledger); OpenClaw Skill Workshop (history + undo). Academic: Voyager skill library (arXiv 2305.16291), Agent Workflow Memory (arXiv 2409.07429) | The repetition detector itself: nobody ships one. Activity log (what the user asked the agent / did through it) + nightly clustering job; at >=5 similar requests, draft a SKILL.md into the approval queue | Storage/gating copy, detector build; this is genuinely novel in production agents |
| People-interaction memory (who, what, follow-ups) | Hermes MEMORY.md/USER.md + SQLite FTS5 session search; OpenClaw USER.md + daily notes + "dreaming" consolidation; Mem0 (Apache-2.0, entity linking, Hermes ships a provider plugin); Graphiti (Apache-2.0, temporal KG); Letta memory blocks (Apache-2.0) | The person model: neither engine models third parties, only the owner. Per-contact entity layer on SQLite + FTS5 + sqlite-vec (Apache-2.0): contact -> interactions, commitments, follow-up dates; LLM extraction job | Substrate copy, person model build; commitment extraction is the highest-value piece |
| Pre-meeting pointers | Content template proven: Cortana Briefing Email (daily, only-when-actionable, mailbox-local), Sales Copilot meeting-prep card (1h before: attendees, prior threads, commitments, talking points via Graph attendee prioritization), M365 Copilot pre-meeting brief, Executive Briefing Agent template | Almost everything: no OSS agent reads Outlook. Cron at meeting-minus-60m reading the calendar ladder (.ics subscription > classic Outlook COM > Graph delegated); extraction prompts; only-when-actionable suppression | Mostly build, template copied |
| English-described plugins for non-coders | Pieces proven: Anthropic skill-creator (interview -> draft -> A/B eval -> optimize trigger description -> package), agentskills.io (description-as-contract, 1024-char, near-miss negative evals), Hermes install-time static scan (safe/caution/dangerous, no override), Zapier/Lindy/GPT-builder NL drafting, Deno-style scoped permissions | The loop itself: spec interview -> capability plan -> artifact generation -> static validation -> dry-run -> capped self-repair -> plain-English approval -> pilot install -> heartbeat UX -> re-validate on update. No direct precedent for the full loop on a locked-down corporate laptop | The novel combination; components proven |

## A8.2 The English-to-plugin flow (recommended, with guardrails)

1. Spec interview: agent extracts from conversation, asks at most 3-5 bounded plain-language questions with multiple-choice defaults (which file, what counts as a change, when to refresh). No code vocabulary.
2. Capability planning: map to broker scopes (file.read, calendar.read, timer); one consent question per scope in outcome terms; manifest may only request scopes the spec justifies.
3. Artifact generation: Class D manifest (JSON-Schema validated) + widget template in a whitelisted DSL + SKILL.md (imperative description, <=1024 chars); Class C worker only if needed (sandboxed JS, broker APIs only, no shell).
4. Static gate before any execution: schema validation (jsonschema, MIT), over-permission check (declared vs referenced scopes), static scan for forbidden constructs (import/eval/fetch to undeclared hosts). Dangerous verdict blocks install, no override (Hermes rule).
5. Dry-run with sample data: show the actual widget output; 2-3 trigger queries with near-miss negatives (agentskills.io method).
6. Capped self-repair: max 3 iterations, semantic assertions (not just no-exception), honest escalation ("could not build this safely") with degradation to a Class D declarative version. The two-class structure is the failure absorber: when codegen fails, ship the watch-diff-display version, not bad code.
7. One consolidated plain-English approval: what it does, what it can touch, what it can never do, the preview, the undo promise. No code shown. (Users rubber-stamp ~97% of prompts per Claude Code data, so approvals must be few and meaningful.)
8. Pilot install with a visible badge; every widget permanently shows last-run status (heartbeat/dead-man's-switch, amber on missed window with re-test button); all broker calls audited.
9. Updates re-validate and re-consent on any scope widening; previous versions kept, one-click rollback (OpenClaw pattern).

Security notes: Snyk's ToxicSkills audit found 36% of 3,984 audited agent skills vulnerable and 76 malicious; SKILL.md context poisoning is now a named vector (CSA, OWASP Agentic Skills Top 10, Datadog). Break the lethal trifecta structurally: a widget that reads private files gets no network egress; watched content is data, never instructions. QuickJS-NG had a 2026 sandbox-escape CVE (CVE-2026-37630), so the sandbox is depth, never the boundary; the capability broker is the boundary.

## A8.3 Proactivity budgeting (avoid the nagging agent)

Evidence: interruptions cost ~23 min to refocus, average screen attention ~47 seconds. Patterns to implement: digest windows (Briefing-email precedent: once daily, only when actionable), quiet hours (activeHours), idle-only firing, silence markers (NO_REPLY / [SILENT] / no_change), per-category caps + global daily budget, inbox-first (Notify/Question/Review triage, LangChain ambient agents) instead of push, and timing learned from accept/reject feedback (ProactiveBench reward-model approach, arXiv 2410.12361).

## A8.4 Always-on without admin

Per-user Scheduled Task (runs as the logged-on user, no elevation; some hardened estates deny creation), HKCU Run key, or Startup folder; OpenClaw's own Windows gateway install uses exactly these. Design for Modern Standby: run on logon, poll while awake, catch-up-on-wake (Hermes cron has catch_up_missed + grace windows; its zero-LLM script gate avoids paying tokens on no-change polls). EDR optics: user-space autostart is a classic malware pattern, so name the task clearly, keep everything documented, bind only localhost.

## A8.5 Enterprise risk notes specific to the autonomy layer

1. Mail ingestion is the riskiest feature: endpoint DLP (Purview) watches local AI reading mail/files; ship only derived abstractions (topics, counts, commitments) to the BYO endpoint, keep raw mail local, or get a sanctioned endpoint. Get written user acknowledgment before mail ingestion.
2. New Outlook (WebView PWA) exposes no COM components; orgs pushing it via policy silently kill Outlook COM automation. The calendar/mail ladder is .ics/watched-folder > classic Outlook COM > Graph (expect the "Need admin approval" consent wall on corporate tenants).
3. Frameworks are guardrails, not sandboxes (their own words): keep approvals smart/manual, never YOLO, default-deny messaging, DM pairing; Docker isolation is usually unavailable without IT.
4. Repetition detection must observe only what the user consciously shares with the agent (their prompts, files opened through it), never keystrokes/screens: employee-surveillance optics.
5. Self-authored skills are a prompt-injection surface: keep skills.write_approval: true and review diffs.

## A8.6 Revised verdict (SUPERSEDED by A9.3)

With autonomy in scope, the recommendation shifts from Path A to **Path B as primary: Hermes Agent as the engine, our dashboard + plugin compiler + autonomy layer on top**. Hermes already delivers the plumbing of proactive scheduling, first-message delivery, skill staging gates, curated memory, and a non-tech-user-safe default posture, all MIT, all user-space on Windows. OpenClaw is the credible alternative (standing orders, dreaming memory, smoother Windows daemon) with weaker hard gating. Our build list, in value order: (1) the English-to-plugin compiler with its validation/approval loop, (2) the repetition detector + skill-proposal queue, (3) the per-contact people memory with commitment extraction, (4) the meeting-prep job on the calendar ladder, (5) the interruption budget, (6) the widget dashboard itself. Roughly 70% of the plumbing is assembled; 100% of the differentiating product is built, on permissive licenses throughout (Hermes/OpenClaw MIT; Mem0/Graphiti/Letta/sqlite-vec Apache-2.0; SQLite public domain; jsonschema MIT).

## A8.7 UX-first constraint (post-research refinement): the web app IS the product

Clarification from the stakeholder: end users (the manager and peers) are no-code, non-technical. They cannot operate a terminal, chat-channel pairing, or config files. They can operate a web app. Consequence: every capability, including the autonomy layer, must be reachable as clicks in a localhost web UI. No terminal surface, ever.

Revised architecture (supersedes the A8.6 engine-first framing):

- The user-facing product is a local web app (NiceGUI or FastAPI+React on 127.0.0.1, optionally wrapped in a pywebview/WebView2 window so it feels like a native app with a taskbar icon and toast notifications). One double-click .cmd installs and opens it; per-user autostart keeps the agent alive; browser/WebView notifications surface proactive cards without any messaging-channel setup.
- Under the hood, the recommended engine reverts to the thin custom Python core (original Path A): when users never touch the engine's own UI, wrapping a developer-grade tool like Hermes headless buys plumbing but costs wrapper fragility (its approvals, skill diffs, and pairing are chat/CLI-shaped; every release could break the wrapper). Borrow its proven patterns instead: SKILL.md (agentskills.io) as the on-disk skill format so skills stay portable to Hermes/OpenClaw, write_approval-style staging queues rendered as web buttons, cron with deliver-to-inbox, smart-approval judging. Hermes remains a viable drop-in later for teams that want its channels, because the skill format is shared.
- No-code user journey: install (double-click, opens browser), dashboard widgets, an assistant chat box inside the app, "Add a plugin" wizard (English interview -> preview -> one consolidated plain-English approval), Approvals inbox (Accept / Dismiss / "show me what changed" in plain language), Settings as toggles only. Proactive suggestions arrive as inbox cards and optional notifications, governed by the interruption budget. Degradation paths: if the machine is asleep or the tab is closed, suggestions queue to the inbox and an optional email digest; nothing requires the user to babysit a process.

## A8.8 Architecture decision (SUPERSEDED by A9.3): Hermes engine + adapter layer + automated update pipeline

The team is technical (can write and maintain scripts); end users are strictly no-code. Decision: run Hermes Agent as the invisible engine, and build the no-code product as a web app sitting on a thin adapter layer ("control plane"), NOT by wrapping Hermes' own UX surfaces.

Three layers:

1. Web app (the product users see): dashboard + assistant chat + plugin wizard + approvals inbox + toggles, on 127.0.0.1 / WebView2 shell.
2. Adapter layer (our code, the "script"): a fixed, small operation vocabulary, deliberately the ONLY place Hermes is touched: send_prompt/get_reply (headless run), list/install/approve skills (skills dir + ~/.hermes/pending/skills/ staging), add/remove cron jobs, read/search memory, enqueue suggestion cards, health check. Everything else (channels, TUI, pairing) stays unused. Because SKILL.md is the agentskills.io standard, the skill surface is the most stable part.
3. Hermes engine: pinned version, configured once by the technical owner (approvals smart, write_approval on, default-deny messaging, endpoint/key from the corporate LLM).

Fragility containment (answers the wrapper-rot objection): the adapter implements a written contract (~8 operations) with contract tests that run against the pinned Hermes version in CI. When Hermes releases: CI pulls the new version, runs the contract tests, failures produce a report, an LLM maintenance agent drafts adapter patches against the failures, a technical human reviews and approves, the pin bumps and the update ships through the same internal distribution as the app itself. This is the "agent in production that handles each update," built as a bounded, tested, human-approved pipeline rather than a free-running agent, because a silent regression in the approvals or skills gate would be a security regression, and tests are what catch that, not the LLM's confidence.

Insurance: because the web app only talks to the adapter vocabulary, a minimal built-in core (the old Path A engine) can implement the same ~8 operations as a fallback backend if Hermes ever hard-pivots. The adapter interface is the asset; the engine is replaceable.

First implementation task when building: read the current Hermes docs/CLI to fix the exact headless invocation and file paths for each adapter operation, then freeze that as the contract test suite.

# A9. Post-audit hardening (2026-11-11, v2)

An independent audit challenged this research. Every checkable claim was re-verified against primary sources before accepting or rejecting it. Outcome: the audit's engineering, Windows-enterprise, security, and legal recommendations are accepted and now binding (A9.2, A9.3); several of its factual accusations are themselves contradicted by primary sources (A9.1). Meta-lesson recorded for the project: subagent research AND external audits both require primary-source verification; neither is exempt.

## A9.1 Audit verification scorecard

| Audit claim | Primary-source check (fetched 2026-11-11) | Verdict |
|---|---|---|
| Star counts (394k / 262k / 278k) hallucinated | api.github.com/repos/openclaw/openclaw: 394,311 stars, MIT, pushed 2026-11-11. api.github.com/repos/NousResearch/hermes-agent: 262,517, MIT. api.github.com/repos/deepseek-ai/deepseek-harness: exists, 278,386, MIT, description "DeepSeek Harness: Everything is a Plugin." | REJECTED. Subagent figures accurate. The auditor projected outdated ecosystem statistics onto the current landscape. |
| DSH/Cordis is a Koishi conflation | The repo exists; `cordis` is in its GitHub topic list; description matches | REJECTED. Architecture citation stands. |
| pydantic-ai v2.67.0 is a version conflation | pypi.org/pypi/pydantic-ai/json: 2.67.0, MIT, 2.x line | REJECTED |
| Microsoft Agent Framework 1.25.0 is an SK version | pypi.org/pypi/agent-framework/json: 1.25.0, MIT classifier | REJECTED |
| Cortana Briefing deprecated | Consistent with our own source (paused Jan 2023, folded into Viva Insights) | ACCEPTED as a labeling fix: cite only as the retired 2020-2023 historical UX precedent, alongside Viva Insights and M365 Copilot briefs |
| mem0 telemetry on by default (MEM0_TELEMETRY opt-out) | Not stated in the README/docs fetched; could not confirm | UNVERIFIED. mem0 is cut anyway (A9.2 rule 2) on least-dependency and telemetry-risk grounds |
| Graphiti needs GPL/SSPL graph-DB backends | README confirms required backends: Neo4j / FalkorDB / Neptune; embedded Kuzu is supported but explicitly DEPRECATED ("upstream Kuzu project is no longer maintained"); FalkorDB Lite embedded exists (Py 3.12+); backend licenses not stated in README | ACCEPTED SUBSTANTIVELY: cut Graphiti. Note the audit's own proposed fix (swap in Kuzu) is outdated, since Graphiti's Kuzu support is deprecated; this strengthens the cut, not the swap |

## A9.2 Accepted hardening (binding)

1. **Engine: single-runtime pure-Python core.** Do NOT deploy the Hermes binary: dual Python+Node doubles the AppLocker/WDAC and TLS-config surface (SSL_CERT_FILE plus NODE_EXTRA_CA_CERTS), node_modules extraction triggers AV real-time-scan storms, its installer is a .ps1 (blocked under GPO per our own Section 5), and its 20+ messaging connectors are an immediate CISO exfiltration objection. Instead port the three patterns we actually valued from Hermes into the core: cron with missed-tick catch-up and idle checks (APScheduler + watchdog), a pending/ staging approval queue for skills, and MEMORY/USER markdown + SQLite FTS5 search. Treat the audit's "under 500 lines" estimate as optimistic for production semantics (retry ladders, secret redaction, failure nudges); budget it as a small tested module. The A8.8 adapter vocabulary survives as the internal module interface; Hermes remains an optional future backend behind it; SKILL.md keeps skills portable.
2. **Memory stack: SQLite + FTS5 + sqlite-vec only.** mem0 and Graphiti are cut (telemetry risk unverified but plausible; graph-DB backends GPL/SSPL; embedded Kuzu deprecated). Zero services, zero telemetry, all MIT/Apache/public-domain.
3. **Excel delta widget, two flaws fixed.** (a) .xlsx stores no cell timestamps: excel-watch snapshots the parsed table into local SQLite on each poll and diffs row-hashes against the T-24h snapshot; the file itself never encodes the window. (b) Windows exclusive locks (~$ owner file) when desktop Excel has the workbook open: copy to a %TEMP% shadow file before parsing (shutil.copy2 with a short retry loop, pure stdlib; no pywin32 needed), parse the copy, never the live path.
4. **Calendar ladder gains Rung #0: the Power Automate bridge.** The user imports a 3-step personal cloud flow in their browser (Recurrence 30 min -> Get calendar view of events -> write calendar_sync.json to OneDrive for Business); the built-in OneDrive client syncs it into %USERPROFILE%\OneDrive; the agent reads local JSON. Zero Graph admin consent, zero Outlook COM, immune to New Outlook. Caveats: tenant admins can disable personal flow creation; seeded Power Automate rights vary by SKU; OneDrive sync adds latency; the one-time template import is a browser task the no-code user can do themselves. Old rungs remain in order behind it: .ics subscription (often blocked by Exchange sharing policy), classic Outlook COM (object-model guard, dying with New Outlook), Graph delegated (consent wall).
5. **Runtime delivery: uv primary.** Single static uv.exe; uv python install for the interpreter; --native-tls forces package resolution through the Windows SChannel trust store, sidestepping corporate TLS-inspection certificate failures at bootstrap without pip-system-certs or manual CA exports. The Python embeddable zip is demoted to airgapped fallback with its gotchas listed (no venv module, DLL resolution issues, certifi bootstrap).
6. **No autostart persistence in v1.** No HKCU Run key, no schtasks: an unsigned %LOCALAPPDATA% script plus Run-key/scheduled-task persistence plus periodic network calls is the exact behavioral signature of user-space persistence malware on CrowdStrike/Defender for Endpoint/SentinelOne, and will generate a SOC alert on day 1. v1 ships a Start Menu/Desktop shortcut the user clicks to start work; APScheduler runs in-process while the app is open; missed work catches up on next launch. Persistence is introduced only after IT/Security sign-off.
7. **Class D render is XSS-safe.** The manifest's render field is now a declarative JSON UI schema ("type": "ui-schema": cards, tables, KPIs, badges, chart references) rendered server-side by the host. No plugin-supplied HTML/JS ever executes in the dashboard origin. If rich custom visuals become necessary later: sandboxed iframe WITHOUT allow-same-origin, data strictly via postMessage, and it is treated and approved as Class C.
8. **Localhost server hardened.** Bind 127.0.0.1 only, never 0.0.0.0. On startup generate a 256-bit session token, launch the browser at /auth?token=<random>, exchange it for an HttpOnly, SameSite=Strict cookie, and validate Origin and Host headers on every HTTP and WebSocket request. This closes cross-site localhost fetch and DNS-rebinding attacks from any malicious page in the work browser.
9. **English-to-plugin compiler is Class D ONLY.** No LLM-generated executable code for non-coders: static scanning of generated JavaScript is trivially bypassed (globalThis['fe'+'tch'], prototype traversal), and non-coders cannot meaningfully audit a capability diff. If a request exceeds the declarative vocabulary (excel-watch, json-watch, http-get, calendar-read, llm-transform, ui-schema), the compiler stops and exports a feature request to the internal dev queue / plugin repository. This removes the sandbox-runtime CVE class from v1 entirely (no QuickJS/WASM needed) and eliminates the self-repair-gaming failure mode for generated code.
10. **Legal simplifications.** (a) Internal deployment of MIT/BSD/Apache components to employees of the same legal entity is generally internal use, not distribution, so notice-preservation clauses force no user-visible attribution; still ship upstream LICENSE (and Apache NOTICE) files inside the install folder as hygiene; have counsel confirm the framing. (b) pywin32 is eliminated: Windows Credential Manager access via ctypes (Advapi32 CredReadW/CredWriteW, Python stdlib) plus the Power Automate bridge replace COM automation; zero license exceptions remain for Legal to review.

## A9.3 Final architecture (v2; supersedes A8.6 and A8.8)

Single-runtime pure-Python local web app (NiceGUI, or FastAPI + static bundle) serving a hardened 127.0.0.1 UI (session-token auth, origin validation, WebView2 shell optional). Internal core modules behind adapter-vocabulary interfaces: prompt loop, skills staging (SKILL.md + pending queue), cron/heartbeat, SQLite/FTS5/sqlite-vec memory, suggestion inbox, health. Data ingestion via the Power Automate OneDrive JSON bridge and shadow-copied Excel snapshots. Runtime delivered by uv (--native-tls), started on demand via shortcut, no persistence until IT sign-off. Plugin system: Class D only for v1-v2 (manifest + ui-schema + declarative data sources + llm-transform), internal git registry per Section 3, English-to-plugin compiler emitting Class D exclusively. Hermes Agent: not deployed; patterns ported; remains a swap-in backend candidate behind the module interfaces. The module interfaces are the asset; every engine choice stays reversible.

## A9.4 Plan deltas

- Probe day adds: confirm the tenant allows personal Power Automate flow creation (try importing the 3-step template); confirm the OneDrive client is present and syncing; identify which EDR is running.
- v1: on-demand shortcut launch; three widgets hardcoded (Excel snapshot-diff; calendar via PA bridge; research via corporate LLM + sanctioned search). No persistence, no plugin system yet.
- v2: Class D plugin system (ui-schema render, git index.json registry, validator CLI); sales widget extracted into the first plugin; English-to-plugin wizard.
- v3+: persistence after IT sign-off; optional iframe visuals as Class C; optional Hermes backend swap; repetition-detector skill proposals.

A9 verification sources (fetched 2026-11-11): api.github.com/repos/openclaw/openclaw; api.github.com/repos/NousResearch/hermes-agent; api.github.com/repos/deepseek-ai/deepseek-harness; pypi.org/pypi/pydantic-ai/json; pypi.org/pypi/agent-framework/json; github.com/mem0ai/mem0; github.com/getzep/graphiti.

## Addendum sources

Proactivity + memory: hermes-agent.nousresearch.com/docs (cron, heartbeat, goals, skills, memory, curator, security, secure-hermes-on-a-work-machine, daily-briefing-bot); docs.openclaw.ai (automation/cron-jobs, gateway/heartbeat, automation/standing-orders, concepts/memory, tools/skills, platforms/windows); langchain.com/blog/introducing-ambient-agents (+ UX for Agents part 2); arXiv 2410.12361 (Proactive Agent), 2305.16291 (Voyager), 2409.07429 (AWM), 2504.07079 (SkillWeaver), 2505.20286 (Alita), 2504.13171 (sleep-time compute); github.com/mem0ai/mem0, getzep/graphiti, letta-ai/letta, asg017/sqlite-vec (all Apache-2.0 verified); learn.microsoft.com (Graph permissions, Entra consent, Sales Copilot meeting-prep, Executive Briefing Agent template, Purview endpoint DLP, schtasks, Modern Standby); Northwestern KB (Cortana Briefing); paloaltonetworks.com (endpoint DLP for local AI); ics.uci.edu/~gmark/chi08-mark.pdf (interruption costs).

NL-to-plugin: github.com/anthropics/skills (skill-creator); agentskills.io (spec, optimizing descriptions, best practices); docs.openclaw.ai/tools/creating-skills + openclaw.ai/blog/openclaw-agent-skill-workshop; hermes docs (plugins); help.zapier.com (NL Zap outlines); lindy.ai/blog/lindy-3-0; help.openai.com (GPT builder) + openai.com/index/introducing-agentkit; github.com/hkuds/autoagent; arXiv 2502.05957; snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub; labs.cloudsecurityalliance.org (SKILL.md context poisoning); owasp.org Agentic Skills Top 10; securitylabs.datadoghq.com (malicious skills); simonwillison.net/2025/Jun/16/the-lethal-trifecta; claude.com/resources/articles/auto-mode-default-in-claude-code; github.com/anthropics/sandbox-runtime; docs.deno.com (permissions); quickjs-ng.github.io + CVE-2026-37630; github.com/python-jsonschema/jsonschema; healthchecks.io (dead man's switch); learn.microsoft.com (Power Automate triggers, Excel + Power Automate).

## B. Outlook without a connector, and plugin truth (2026-11-18)

Spec 008 asked for a working Outlook plugin with no connector. The detailed
note is [research/2026-11-18-outlook-without-connector.md](research/2026-11-18-outlook-without-connector.md);
the creation trace is [research/2026-11-18-plugin-creation-trace.md](research/2026-11-18-plugin-creation-trace.md).

- **Decision: exported `.eml` folder is the only ingestion contract.** No Graph,
  IMAP, EWS, PST/OST, or COM in the product. Feeders, in order: manual Save as /
  OWA Download; personal Power Automate `Export email (V2)` to OneDrive; checked-in
  mock inbox for CI and the demo. Classic Outlook COM stays a dev/demo helper
  (`tools/export-outlook.ps1`) because new Outlook has no COM and the end user has
  no terminal.
- **Header-only survives.** The parser reads From, To, Cc, Subject, Date,
  Message-ID, In-Reply-To and Importance; bodies are discarded at parse time. The
  brief ranks messages with explainable rules and builds three subject-based reply
  starters, so no body ever reaches a card.
- **Declarative plugins stay declarative.** The Outlook card selects a host data
  source (`outlook-brief`) and declares its widget elements; the host adapter is
  code, the plugin is the binding. Adding executable plugin code was explicitly
  rejected as a larger security surface than the demo needs.
- **Install truth is a pin problem, not a resolver problem.** 24 of 25 local
  release pins had drifted from their trees after later edits; `sync_registry.py`
  plus `build_catalog.py` restored them. The old #115 failures were the same
  drift, not a marketplace defect.
- **Creation had two endings confused.** Publishing for review is a distribution
  action and still needs the admin switch; Studio's personal path is
  `POST /api/marketplace/studio/install`, which validates the inline tree and hands
  it to the same runtime the wizard uses. This is the end-to-end demo path.
- **Known limit.** A real Outlook profile is still required to export live mail;
  this machine has OUTLOOK.EXE but no profile, hence the demo inbox.
