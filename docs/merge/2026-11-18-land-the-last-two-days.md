# Merge record: land the last two days (spec 011)

Date: 2026-11-18. Branch: `fix/spec-011-land-the-last-two-days`. Spec: #159.

## What this merge fixes

Eighteen PRs landed on 2026-11-16 and 2026-11-17/18, three of them within
minutes of each other on the evening of the 18th (#146, #147, #158). Each
branch passed (or overrode) its own checks; the combined result did not:

1. **The served bundle was stale.** #146's coupled-intelligence UI never
   reached `src/agentdesk/server/static/spa/`; the last rebuild predated the
   merge. The CI committed-bundle check failed on #146's own PR page and the
   merge happened anyway. The desk a user opened had no readings and no press.
2. **Two live contract gaps under the same feature.** Single-instance widget
   cards carried no `pluginId`, so `attach_cards` keyed nothing onto the
   digest, calendar or research cards (#165); and the SPA's press type did not
   know the nested `thread` shape the digest family emits, so a press posted
   no thread and the route refused (#166). #146's tests passed because each
   side was tested against its own assumption (flat fields, hand-built cards).
3. **The docstring gate went red.** #146's `insight/` package landed
   undocumented after #158's baseline was cut, and #147's function renames
   left two stale baseline lines (#161).
4. **The SBOM generator refused the memory feature's runtime dependency**
   (`cryptography`) instead of resolving and licensing it, so the SBOM and
   packaging CI jobs failed on main (#162), and the CI Python test job could
   not import the suite at all (#163).

## Provenance

| Ticket | Commit | What it did |
|---|---|---|
| #160 bundle rebuild | `fc62535` | Rebuilt the SPA from source; the press vocabulary is in the served bytes |
| #165 card shape | `ba1e768` | Every widget card names its plugin and instance; readings reach every family |
| #166 SPA press thread | `1fff808` | The press body carries the nested thread; the draft route resolves it |
| #163 CI installs | `933e3f9` + `ce00bf0` | python-tests, sbom and packaging jobs install declared deps from packaging metadata |
| #162 SBOM resolver | `7675569` (cherry-pick of `76c0760`) | One CycloneDX component per declared dependency, licensed from `[tool.agent-desk-licenses]`, byte-deterministic; refusals kept |
| #161 insight docstrings | see PR | The insight package documented to the standard; baseline cleaned |
| #164 evidence | see PR | Screenshots and gate transcripts under `docs/evidence/integration-2026-11-18/` |

## Verification

- `pytest`: 2535 passed, 1 skipped, and one failure that is a pre-existing
  full-suite ordering flake (`test_server_mail_api.py::test_toggle_on_polls_the_folder_and_files_cards`):
  it passes in isolation and in its own file on this branch, and fails the
  same way in a full run of unmodified main. The docstring gate passes with
  no insight entries and no stale lines.
- Frontend: 282 vitest tests green (281 + the new nested-thread press test),
  `tsc --noEmit` clean, and a fresh `npm ci && npm run build` produces a
  byte-identical tree to the committed bundle.
- Gates: `python scripts/sbom.py` succeeds (218 components, `cryptography`
  licensed Apache-2.0 OR BSD-3-Clause), double-build byte-identical, license
  gate PASS, third-party notices check green.
- Live: the desk was booted, the marketplace install of Outlook Brief walked
  through its consent sheet, the digest card drew its reading, and pressing
  "Draft a reply" reached the draft route with the thread and answered with
  the honest model-off sentence plus its full disclosure (no endpoint is
  configured on this desk, and none was invented).

## Honest limits

- The press cannot produce a real draft on a desk with no LLM endpoint; the
  evidence records the refusal sentence, which is the product's own honest
  behaviour for that state, not a gap in the wiring.
- Preventing a recurrence of merge-over-red is a repository-settings decision
  (require the frontend-build and python-tests checks); this merge makes green
  the default state worth protecting but cannot set branch protection itself.
