# Sources audit (verified at 6bb5bbb, code read by audit-sources)

MUST FIX
1. Fresh desk has zero plugin cards: no startup/first-run install() caller (only marketplace/api.py:1201,1354,1470; peers_api.py:551; app.py:5425,5778,6115). Runtime opens over an empty data dir (app.py:7196-7216); layout.py:25 has only 4 builtins. Excel Tracker / Page watch never appear as data cards until Priya installs them from Marketplace. dashboard_state.py:215.
2. Mail source cannot be set up without a terminal: needs a folder of exported .eml files produced by tools/export-outlook.ps1 (plugins/execute.py:1053), pointed at via a free-text input (settings_view.py:1218). PRODUCT.md promises no terminal. Missing folder -> unconfigured only (mail/watcher.py:72-77).
3. Spec 015 outcome is false: registry ships 3 plugins, not 2; presentation-starter survived with no card and no server caller (only tools/pack_builder.py:131 + tests), and tests pin it (tests/test_catalog_bundle.py:140, tests/test_registry_hardening.py:186). Packs retired correctly (registry/packs.json empty; 23 trees in archive/plugins).
4. Trust stack is inert on the only shipped install path: registry/index.json releases carry no signature/keyId; stage_registry_install is called without a trust store (app.py:5775-5777), and _verify_against_trust fails closed only when a trust store is supplied (registry/install.py:155-201). 1,404 lines never run for bundled plugins.

SHOULD FIX
5. Marketplace governance has no user: publish/approve/policy-import require AGENTDESK_MARKETPLACE_ADMIN=1 (marketplace/api.py:740-751). Its own copy admits signatures are not re-verified (api.py:65-67) while claiming no plugin runs without an eligible policy decision (:80).
6. "Connected to Hermes" is false: 46 grep hits in src/agentdesk, all docstrings/comments/license; zero imports or calls. Only live-text trace is two dead threat regexes matching ~/.hermes (safety/threat_patterns.py:137,139).
7. Page watch is core code reading a plugin's private data dir by hardcoded name (app.py:2957-2972); if competitor-watch is absent/renamed the card silently vanishes, and presentations duplicates the read (presentations/pipeline.py:80-81).
8. Wizard is real but buried: reachable from exactly one dashboard form (Dashboard.tsx:502-504 -> POST /wizard/start), no nav entry; 855 lines. Legacy registry-install routes still served with a "deleted 2026-Q4" note (app.py:5725-5734).
9. There is no src/agentdesk/research/ package: research is assistant/research_store.py plus web view; the plugin research-brief can only read latest() (plugins/sources.py:925).

NICE TO HAVE
10. Excel shadows land in system temp, not the desk workspace (excel/watcher.py:67, shadow.py:23); per-poll cleanup exists (watcher.py:225) but crash leftovers sit outside any user-visible folder.
11. Plugin engine is heavier than its payload: 5,536 lines (sources.py 1314, execute.py 1066, runtime.py 886) to carry 2 card plugins and 12 declarative source types; presentation-starter adds a third install/consent surface.

Verdicts: live 6 (excel, calendar, mail-metadata, inbox+budget/snooze, presentations, wizard), buried 3 (wizard, probe via Settings, trust), inert 2 (marketplace admin, trust-at-install), demo-only 1 (presentation-starter), fake claim 1 (Hermes integration). Spec 015 incomplete (3 not 2).
Lean: about -2,500 to -3,000 lines (trust 1,404; admin/governance half of marketplace api ~800-1,000; presentation-starter + pinned tests).
Not checked: live run of wizard/marketplace flows, actual Power Automate output, peers path, probe-vs-deskcheck overlap (grep zero source overlap).
