# Issue closeout review, 2026-11-26

Repository: `kanitmann01/agent-desk`
Main reviewed: `0f290287b9c291f95fe7bbd1b8906b33db4b4c41`
Open before: 38
Pull requests reviewed: 129, comprising 125 merged, 3 closed without merge, and 1 open
Issues closed by this review: 0
Open after: 38

Only a merged delivery or a verifiably complete change on main qualifies as done. Open pull requests, branch work, partial delivery, and missing evidence remain open. No issue, pull request, or label was changed.

- #320, UI wave audit: Left open. Parent audit with open children #324, #325, #326, #327, #328, #350, #366, and #368; the required `docs/evidence/2026-11-25-main-audit/` pack is absent from main.
- #321, Spec 030 parent: Left open. All implementation children #329 to #336 remain open, and no merged pull request delivers the spec.
- #322, Spec 031 parent: Left open. All implementation children #337 to #344 remain open, and no merged pull request delivers the spec.
- #324, Baseline and BEFORE walk: Left open. The required BEFORE evidence pack is absent from main, and no merged pull request references or delivers this issue.
- #325, Code review and findings register: Left open. Required `findings.md` and `findings.json` in the audit evidence pack are absent from main.
- #326, Walk passes and photographs: Left open. Merged PR #352 (`e53c5919fd71`) adds the face-walk instrument only; the required walk outputs, photograph verdicts, and evidence pack are absent, while #366 and #368 remain open.
- #327, P0 and P1 fix round: Left open. No findings register, complete fix integration record, or post-fix re-walk evidence is on main; no merged pull request delivers this issue.
- #328, P2 and P3 triage and closeout: Left open. The audit evidence pack is absent from main, active audit tickets remain, and no merged pull request completes the closeout criteria.
- #329, One face store: Left open. Active Spec 030 ticket with no merged delivery pull request; parent #321 remains open.
- #330, One shell component: Left open. Active Spec 030 ticket with no merged delivery pull request; parent #321 remains open.
- #331, Server-rendered shell: Left open. Active Spec 030 ticket blocked by open #330, with no merged delivery pull request.
- #332, Declared server waits: Left open. Active Spec 030 ticket blocked by open #329 and #331, with no merged delivery pull request.
- #333, Memory page waits: Left open. Active Spec 030 ticket blocked by open #329 and #331, with no merged delivery pull request.
- #334, Background truth: Left open. Active Spec 030 ticket blocked by open #331, with no merged delivery pull request.
- #335, Face in working dialogs: Left open. Active Spec 030 ticket blocked by open #329, with no merged delivery pull request.
- #336, Walk instruments and evidence: Left open. Active Spec 030 proof ticket with open dependencies #332, #333, #334, and #335; no merged delivery pull request.
- #337, Workbook figures: Left open. Active Spec 031 ticket with no merged delivery pull request; parent #322 remains open.
- #338, New slide role: Left open. Active Spec 031 ticket with no merged delivery pull request; parent #322 remains open.
- #339, Executive review template: Left open. Active Spec 031 ticket blocked by open #338, with no merged delivery pull request.
- #340, Working session template: Left open. Active Spec 031 ticket blocked by open #338, with no merged delivery pull request.
- #341, Minimal template: Left open. Active Spec 031 ticket blocked by open #338, with no merged delivery pull request.
- #342, Form fills every role: Left open. Active Spec 031 ticket blocked by open #337 and #338, with no merged delivery pull request.
- #343, Presentation pack ships: Left open. Active Spec 031 ticket blocked by open #339, #340, and #341, with no merged delivery pull request.
- #344, Readiness and render proof: Left open. Active Spec 031 proof ticket blocked by open #342 and #343; no merged delivery pull request.
- #350, Demo and smoke inert runners: Left open. On main, `tools/demo_readiness.py`, `tools/demo_walkthrough.py`, `tools/engine_sidecar_check.py`, and `tools/smoke_first_plugin.py` still call `create_server` without `gate_runners` and do not import `_inert_gate_runners`; no pull request delivers the ticket.
- #353, Spec 032 rename parent: Left open. Merged PR #364 (`b39669491b96`) delivered the spec and ticket files only; all rename children #354 to #363 remain open.
- #354, Name contract data: Left open. Active Spec 032 ticket with no merged delivery pull request; parent #353 remains open.
- #355, Naming guard: Left open. Active Spec 032 ticket blocked by open #354, with no merged delivery pull request.
- #356, Server-rendered rename: Left open. Active Spec 032 ticket blocked by open #355, with no merged delivery pull request.
- #357, SPA rename and bundle: Left open. Active Spec 032 ticket blocked by open #355, with no merged delivery pull request.
- #358, Generated output rename: Left open. Active Spec 032 ticket blocked by open #355, with no merged delivery pull request.
- #359, README and public introduction: Left open. Active Spec 032 ticket blocked by open #355, with no merged delivery pull request.
- #360, Operator guides and compatibility: Left open. Active Spec 032 ticket blocked by open #355, with no merged delivery pull request.
- #361, File properties rename: Left open. Active Spec 032 ticket blocked by open #356, #357, #358, #359, and #360; no merged delivery pull request.
- #362, Python package rename: Left open. Active Spec 032 ticket blocked by open #356, #357, #358, #359, #360, and #361; no merged delivery pull request.
- #363, Frontend package rename: Left open. Active Spec 032 ticket blocked by open #362, with no merged delivery pull request.
- #366, Slow run model delay: Left open and untouched. PR #367 remains open with no merge commit at the final check.
- #368, Pending calendar fixture: Left open. On main, `tools/layout_audit.py:3221` still defines `_run_pending_audit` without `calendar_fixture`, and the call at line 3905 does not pass the fixture; no pull request delivers the ticket.

Unsure issues: none. The missing audit evidence pack, the open dependency chains, the unmerged PR #367, and the direct main-file checks were decisive.
