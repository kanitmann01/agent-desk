# 016-09: the profile review, end to end and in the browser

Date: 2026-11-22. Branch `ticket/016-09-profile`, worktree
`D:\20-projects\Personal Agents\agent-desk\.worktrees\016-09`, head `1ad81d9`
(the review pass committed the switch fix from section 7.1 there, together
with its own fix to `profile_review.apply`).

The ticket's acceptance says: after ten asks and a pass against a stub
endpoint, Settings shows a line with "Learned from activity on <date>";
Remove and Undo work; nothing ungrounded or injected is stored; the review
never opens `preferences.json`; and the audit row carries sizes, not text.

This file records what was actually run and seen. Where the ticket's stated
configuration could not reach the step at all, section 2 shows that, and
section 3 shows the run on a configuration that does reach it.

## 1. How the desk was run

Throwaway data folders, never the real profile:

- `%TEMP%\ad-016-09-walk\data-a` (scenario A, fresh)
- `%TEMP%\ad-016-09-walk\data-b` (scenario B, one legacy settings row seeded)

A loopback OpenAI-compatible stub stood in for the company endpoint:

- `stub.py` in this directory (the copy of the file that ran, stdlib
  `ThreadingHTTPServer`), loopback `127.0.0.1:8793`; `grounded-stub.py` beside
  it is a shorter transcription of the same reply without the request log,
  kept by the review pass, not the one this run used
- answers `/chat/completions`; a prompt carrying the review step's own marker
  sentence (`Only add or patch lines`) gets one operation adding the line
  `Owns the Halvorsen Freight and Kestrel Foods accounts.`, and the ids it
  cites are the two newest `activity` ids read out of the JSON payload the
  desk appended, so the reply can only cite ids the desk really showed it; if
  the payload carries no ids it answers `{"ops": []}`
- any other prompt gets one plain sentence, so the asks, the desk check and
  the other steps degrade the way they would against a model that answered
  in prose
- logs one JSON line per call to `stub.log` (prompt bytes, which marker
  matched, the cited ids), so what left the machine is visible

Boot, both scenarios:

```
$env:PYTHONPATH='<worktree>\src'
$env:AGENTDESK_DATA="$root\data-<a|b>"
python -m agentdesk.server --no-browser --port 8792
```

The boot log prints the one-time start link. It was exchanged once per
browser session and the token is redacted everywhere in this directory; the
session cookie is `agentdesk_session`, domain `127.0.0.1`, `HttpOnly`,
`SameSite=Strict`.

The ten asks were the same in both scenarios (Halvorsen and Kestrel
questions). Drivers `driver-a.py` and `driver-b.py` did the HTTP work: one
ask per question, then `POST /api/agent-loop/run` and a poll of
`/api/agent-loop` until the pass finished, then reads of `/settings`,
`/settings/activity`, `/api/profile/learned` and `/api/ledger`.

## 2. Scenario A: the endpoint configured the supported way

`AGENTDESK_LLM_BASE=http://127.0.0.1:8793/v1` in the environment, fresh data
folder, no settings row for it. Result (`scenario-a.json`):

| check | value |
| --- | --- |
| `/widgets/settings` | `llm_base: ""`, `endpoint_enabled: true`, `learn_profile: true` |
| pass started | `200 {"started": true}` |
| `lastSteps` names | `deskcheck`, `learn-topics` |
| `profile-review` step | **absent** (the loop omits a disabled step) |
| Settings learned line | `false` |
| Activity learned row | `false` |
| `/api/profile/learned` | `{"version": 1, "updatedAt": 0.0, "entries": [], "focusTopics": []}` |

The asks were answered, the memory loop extracted facts, and the review never
ran. This is defect 7.2, not a harness mistake: the step's gate reads
`settings.get("llm_base")`, and no supported surface writes that row any more
(the connections hub replaced it), so `learn_profile` cannot fire on a fresh
install.

## 3. Scenario B: a legacy `llm_base` row

One row seeded before boot, through the same `SettingsStore` the server uses:

```
{'llm_base': 'http://127.0.0.1:8793/v1', 'llm_model': 'stub-model',
 'learn_profile': True, 'endpoint_enabled': True}
```

Same ten asks, same stub. The pass (`scenario-b.json`):

| step | note |
| --- | --- |
| `deskcheck` | failed 0, findings 1, fixed 0 |
| `learn-topics` | topics 0 |
| `profile-review` | **applied 1, dropped 0**, 33 ms |

What the desk then held:

- `stub.log` for the scenario (21 lines): 20 `plain` calls and exactly one
  `profile-review` call, `{"bytes": 1850, "marker": "profile-review",
  "cited": [9, 10], "learnedIn": []}`. One review call, and the ids it cited
  are the ids the desk had just shown it.
- Settings: `<span class='stamp'>1 LEARNED</span>` and the row
  `Owns the Halvorsen Freight and Kestrel Foods accounts.`
  with `<span class='empty'>Learned from activity on 22 Nov 2026</span>`
  and a `Remove` form posting `/api/profile/learned/remove` with hidden
  `id=p-2368`
- Activity: `Learned a line about you from activity 9, 10.`
- `/api/profile/learned`:
  `{"by": "review", "id": "p-2368", "learnedFrom": {"activity": [9, 10]},
  "text": "Owns the Halvorsen Freight and Kestrel Foods accounts.",
  "ts": 1795336283.407}`
- `profile.learned.json` beside the other stores, 361 bytes, same document
- `preferences.json`: **not created**, and the driver's before/after sha256
  were both empty. The review never opens that file, on this path or any
  other (a source-grep test also pins it)

The audit row the review wrote (`audit.sqlite3`, `action = 'llm.profile'`):

```
{"id": 23, "actor": "agent-desk", "action": "llm.profile",
 "target": "http://127.0.0.1:8793/v1", "status": "ok", "model": "stub-model",
 "request_bytes": 1850, "detail": ""}
```

Sizes and the endpoint only: no prompt, no reply, none of the line's text.
The ten asks show up beside it as `llm.assistant` rows (261-277 bytes) and
`llm.retain` rows (2311-2327 bytes) whose status is `error`, detail
`Extractor did not return a JSON object. Nothing was written.` That is the
stub answering in prose to the memory extractor, not a defect: it is also
why `learn-topics` reported `topics 0` on this run, and it is the reason the
line in Settings can only have come from the review step.

## 4. The browser

One real Chrome profile through ego-lite, authenticated by exchanging the
start link, then the Settings page and the Activity page. DOM text quoted
below was read in the same call as its screenshot.

### 4.1 The learned line under the three themes

| theme | `document.documentElement.dataset.theme` | `body` background | screenshot |
| --- | --- | --- | --- |
| Unkey (default) | `unkey` | dark | `settings-learned-unkey.png` |
| Coforge | `coforge` | `rgb(8, 35, 64)` | `settings-learned-coforge.png` |
| Momentuum | `momentuum` | light | `settings-learned-momentuum.png` |

Each shot is the viewport with the card scrolled to centre, and each was read
after the theme click in the same session. The card read, identically in all
three:

```
What the desk learned about you  1 LEARNED
The desk learns only from what you ask it: ...
Owns the Halvorsen Freight and Kestrel Foods accounts.  Learned from activity on 22 Nov 2026  [Remove]
Learn focus topics from repeated asks            [On]
Learn lines about you from your recent asks      [On]
Save captured facts without asking               [On]
```

### 4.2 Remove

Clicked `Remove` (form `action='/api/profile/learned/remove'`,
`name=id value=p-2368`). The response landed back on `/settings#learned` and
the card, read again in the same call as the shot
(`settings-learned-removed.png`):

```
... 0 LEARNED
Nothing learned yet. The desk learns from what you ask it; nothing here is guessed.
[no remove form left]
```

`/api/profile/learned` is read again below, after the undo; the state right
after the remove was read from the page itself (0 LEARNED, the empty-state
sentence, no remove form left), and the activity trail gained
`You removed the learned topic or line: p-2368.` (`profile.removed`).

### 4.3 Undo

The Activity page renders one `form[action='/api/ledger/undo']` per undoable
change and shows `Undone <time>` once an entry has been undone. Clicking Undo
on `You removed the learned topic or line: p-2368.` wrote
`Undo: You removed the learned topic or line: p-2368.` (`ledger.undo`,
`undoes 2a56a73d…`) and marked the removal `undoneBy 73bd40e7…`
(`activity-learned-undo.png`).

The card came back, read in the same call as `settings-learned-restored.png`:

```
... 1 LEARNED
Owns the Halvorsen Freight and Kestrel Foods accounts.  Learned from activity on 22 Nov 2026  [Remove]
```

and `/api/profile/learned` held the original entry with the original
`ts` and `updatedAt`, which is the captured-bytes restore in
`src/agentdesk/ledger/undo.py:273` (`learned-profile`) doing its job.

One detail of this trail is mine, not the product's: the first Undo click in
the session hit `Learned a line about you from activity 9, 10.` rather than
the removal row, because my row finder matched the box text of the entry
above. That undo restored the pre-learn document (empty), which is why the
shot taken then read `0 LEARNED`; the second click, on the removal row,
restored the line. Both rows and both undos are visible in
`activity-learned-undo.png`; the ticket's "Remove, then Undo restores it"
path is the second one.

## 5. Files on disk after all of it

```
data-b\profile.learned.json  361 bytes  FA570DF3740C52D5…  (the restored document)
data-b\preferences.json      ABSENT
```

The full listing of the data folder is in `scenario-b.json` under `files`, and
both drivers' own dumps are committed beside this file (`scenario-a.json`,
`scenario-b.json`); they were written UTF-16 by the drivers and are stored here
as UTF-8 with the same JSON.

## 6. Tests

- `python -m pytest -q tests/test_server_profile_review.py tests/test_profile_review.py tests/test_threat_patterns.py tests/test_server_settings_api.py`
  -> `79 passed in 18.66s` at `1ad81d9` (my switch test plus the review
  pass's `apply` test)
- an earlier full gate on `2629e62` also passed 7/7 with
  `2987 passed, 2 skipped`; its transcript file was truncated to zero by a
  concurrent run before this commit, so it is not included here
- `pytest-baseline.txt` is the untouched branch head `d76c912`:
  `2933 passed, 2 skipped`
- full local gate at `1ad81d9`: `gate-final.txt`, 7/7 gates,
  `2989 passed, 1 skipped`. The two extra passes over `2629e62` are the new
  switch test and the review pass's own `apply` test; the skipped count moved
  from 2 to 1 between the two runs and that difference is not explained here.
  The capture was written UTF-16 by the PowerShell redirect and is stored
  here as UTF-8; no line of it was changed.

## 7. Two defects found while verifying

### 7.1 The Settings switch for the review was dead (fixed)

The page renders the third control with `data-setting='learn_profile'`
(`src/agentdesk/server/settings_view.py:353`) and the page posts every
`[data-setting]` click to `/settings/toggle` (`src/agentdesk/server/pages.py:562`),
but the route's allowlist (`src/agentdesk/server/app.py:3709`) named
`learn_topics` and not `learn_profile`:

```
POST /settings/toggle {"key": "learn_profile"}
-> 400 {"error": "unknown setting"}
```

So the user's off switch for the review did nothing, and no test flipped it.
The fix is in `1ad81d9`: the key is in the allowlist and in the pass-through
branch (the review reads its switch every pass), with the regression test
`test_the_third_switch_turns_the_review_off_and_on` in
`tests/test_server_profile_review.py`. The test asserts the rendered control,
the toggle down (gate false, widgets false) and the toggle back up.

### 7.2 The step cannot run on a fresh install (reported, not changed)

`_profile_review_enabled` (`src/agentdesk/server/app.py:6669`) requires
`settings.get("llm_base")`. Since the connections hub (#233/#234) no surface
writes that row: `/settings/endpoint/save` accepts only `presentationTimeout`,
`AGENTDESK_LLM_BASE` goes to `os.environ` and never to the settings store, and
`keys/resolve.py` says every model call-site resolves through the hub.
Scenario A is the proof: the endpoint is configured the documented way, the
widgets say so, and the step is absent from `lastSteps`.

The choice is the ticket owner's, so nothing was changed here:

1. keep the ticket as written and open a follow-up for fresh installs, or
2. move the gate to the same test the other post-hub call sites use
   (`_presentation_endpoint`, `src/agentdesk/server/app.py:2412`) and serve
   the review from the hub's `memory` job, so connections work and the audit
   row names the endpoint the hub resolved.

I recommend (2); it is a gate change, not a redesign, and it is the only one
of the two that makes the feature reachable for a new user.

## 8. What this does not cover

- The browser steps were driven in one session and one window; no automated
  SPA test was added (the repo's frontend tests cover the built SPA, not this
  flow).
- The two servers on the same host share the `agentdesk_session` cookie name
  (cookies are not port-scoped), so a session minted by one port is rejected
  by the other. It cost one 401 during this session and was fixed by deleting
  the cookie and exchanging the link again; it is a development nuisance, not
  a product path, and is not addressed here.
- No branch was pushed and no PR opened for this ticket.

## 9. Addendum: defect 7.2 resolved as option 2

Section 7.2's recommendation was taken: `_profile_review_client` now
resolves through `_job_llm_parts(server, "memory")` (the same whole-hub
builder the handler call sites use), so a job binding, a default binding,
a single saved connection, the legacy `llm_base` row or the startup
endpoint each serve the review, a saved connection answers to its label
in the `llm.profile` row, and the step gate keeps only the two switches
(`learn_profile`, `endpoint_enabled`). The scenario-A shape (startup
endpoint, no `llm_base` row) is pinned by
`test_the_client_serves_a_fresh_install_through_the_startup_endpoint`.
The audit row now names the hub's serving name instead of the raw
`effective_llm_config` base; on the env leg that is the same endpoint
string scenario B recorded.
