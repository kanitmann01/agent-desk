# 012: Memory-aware agents: one recall-and-feedback layer for every task

**Status:** done (2026-11-18); evidence in `docs/evidence/2026-11-18-agents-memory/`
**GitHub:** issue #167; its six tickets are #168, #169, #170, #171, #172, #173
**Worktree:** `.worktrees/agents-memory`, branch `feat/agents-memory`
**Builds on:** spec 002 (the memory bank port), spec 010 (receipts and the press)

## Problem Statement

The desk has three things that never meet.

It has a memory bank: facts with entities, hybrid recall, review-card capture,
encryption at rest. It has a bring-your-own-key endpoint: one OpenAI-compatible
client every model surface already shares. And it has surfaces that do work: the
assistant answers, research summarizes, plugins read data sources.

What it cannot do is *tasks*. If the user says "make a presentation on the Q3
review", no surface accepts that job. And the two halves of memory never reach
any work the desk might do:

- **Recall does not travel.** The assistant chat is the only surface that
  recalls facts into its prompt, ranked against the question. A task surface
  does not exist to recall into; the skills runner (a saved ask, re-run weekly
  say) calls the model with widget context but no facts at all.
- **Feedback does not come back.** After any piece of work lands, the user
  learns things ("my manager liked it, wants it concise"). The memory loop can
  capture from assistant, research and workbook channels, but there is no run
  to attach that sentence to and no channel that says where it came from. The
  next presentation starts from zero.

The user's example states the acceptance bar: make a presentation, tell the
desk how it landed, and the next presentation for the same manager remembers
the preference without being told again.

## Solution

A host-side **Agents** layer: one runner that every task-capable agent shares,
which does the memory integration once so no agent has to do it itself.

Each agent is a **registry entry**: an id, a name, a blurb, a prompt builder,
and an artifact shape. Two ship now: a presentation agent (a slide outline from
a brief) and a worksheet-brief agent (a short briefing grounded in the watched
workbook's status). Adding a third (Excel deeper, mail, calendar) is a registry
entry plus tests, and touches no memory code, because the runner owns recall
and feedback for all of them.

The runner, per run:

1. **Recalls.** The run's query is the agent's name joined to the user's brief;
   the store's existing hybrid recall ranks facts against it and the same
   bounded block the assistant uses (at most five facts, five hundred
   characters, whole facts only) enters the prompt. A run with nothing to
   recall says so; silence is the designed empty.
2. **Records what it used.** The run row stores the recalled facts' texts and
   ids, so the run page can print a receipt ("this run used: ...") the way
   spec 010's readings print their inputs. A user who distrusts the coupling
   can see exactly which memories shaped the artifact.
3. **Calls the endpoint once**, through the same effective-client resolution
   the assistant uses (saved settings over environment), and records the run
   honestly: ok with the artifact, or degraded with the named cause when the
   endpoint is off, unconfigured or failing. No fake artifacts.
4. **Accepts feedback.** Every run page carries a "how did it land?" form.
   The text becomes the run's feedback record and is offered to the memory
   loop on a new **agents** capture channel, on the same terms as the other
   channels: model extraction when the endpoint answers, the deterministic
   rules on the user's own words otherwise, a review card by default, a stored
   fact only on acceptance.

The next run of the same agent recalls what the last one learned: the fact
"the manager prefers concise slides" ranks on the word *manager* in the next
brief, the entity graph carries it, and the receipt shows it was used.

The desk's plugin guarantee is untouched: plugins stay declarative and
LLM-free, and no plugin may call a model. Agents are a host surface like the
assistant and research panels, not a plugin class. Memory already reaches
plugin cards through the insight seam; this spec adds the task surface, and
the two never cross.

## User Stories

1. As a user with a task, I want to type "Q3 business review" into a presentation agent and get a slide outline, so that the first draft is the desk's job, not mine.
2. As a user, I want a page that lists what the desk can do for me, so that I can see the agents I have without knowing route names.
3. As a user running an agent, I want the run to use what the desk already knows about me, so that I do not re-explain my context every time.
4. As a user running an agent with an empty memory, I want the run to say it used nothing, so that silence is never mistaken for "it read my memory and found none".
5. As a user who distrusts the coupling, I want each run to print the exact facts it recalled, so that I can verify what shaped the artifact.
6. As a user, I want to tell the desk how the work landed ("my manager liked it, wants it concise"), so that the lesson survives the conversation.
7. As a user giving feedback, I want the fact to appear as a review card I accept, so that nothing enters memory without my hand.
8. As a user editing the proposed fact before accepting, I want the same edit-then-accept flow the memory page has, so that corrections are first-class.
9. As a user running the same agent next week, I want the earlier feedback recalled into the new run, so that the second presentation is already concise.
10. As a user, I want the feedback to name its source run on the memory page, so that provenance reads the same as every other origin.
11. As a user with the endpoint off, I want the run to return a named degraded state, so that I know the desk is paused, not broken.
12. As a user with a sealed memory bank, I want runs to proceed with no facts block and feedback capture to decline politely, so that encryption never silently degrades into plaintext reads.
13. As a user, I want the endpoint call to use my saved BYOK settings without a restart, so that configuring the endpoint mid-session is enough.
14. As a user, I want the worksheet-brief agent to read the workbook status the assistant sees, so that its briefing is grounded in the same live data.
15. As a user with no workbook, I want that agent to say so honestly, so that a blank never becomes a zero.
16. As a user running a saved skill, I want its run to recall facts too, so that memory reaches everything the model does, not only the assistant panel.
17. As a user, I want per-channel capture switches to include the agents channel, so that I can turn feedback capture off without touching the others.
18. As a user on the server-rendered page, I want every control to work without JavaScript, so that the page keeps the house promise.
19. As a user in the SPA, I want an Agents entry in the rail, so that the surface is reachable without typing a URL.
20. As a user, I want the model's artifact printed as text and structure, never as raw HTML, so that nothing the model says becomes markup.
21. As an operator reading the audit log, I want each run and each feedback recorded, so that automated composition is auditable like the press is.
22. As a developer adding an agent, I want to write one registry entry with a prompt builder and no memory code, so that the integration cannot be done wrong per-agent.
23. As a developer, I want the runs in their own store with the same inert-default hermeticity as every other store, so that tests never touch the real user data directory.
24. As a developer, I want the recall bounds to come from the one module that owns them, so that the assistant and the agents cannot drift.
25. As a reviewer, I want the end-to-end loop (run, feedback, accept, recall) provable from outside over HTTP, so that the claim "it remembered" is a test, not a hope.

## Implementation Decisions

- **A new `agents` package owns the layer**: a registry (the agent kinds), a
  runs store, and a runner. The registry entry carries the prompt builder and
  artifact shape; the runner owns recall, endpoint resolution, honest
  degradation, provenance and audit. No agent kind touches memory directly.
- **Recall reuses the store and the bounds as-is.** The run's query is the
  agent's name joined to the brief; the ranking, the five-fact/five-hundred-
  character block and the superseded-fact exclusion are the existing ones. A
  locked store contributes no block and the run proceeds, exactly as the
  assistant does today.
- **Runs are rows, not files.** One SQLite store holds agent runs: agent id,
  brief, status, the model's reply, the parsed artifact, the recalled fact
  texts and ids, timestamps, and the run's feedback with its own timestamp.
  The store joins the harness's inert in-memory defaults, per the standing
  hermeticity invariant for every new store.
- **Feedback rides the memory loop, it does not bypass it.** The feedback
  handler stores the text on the run, then offers the run transcript (brief,
  artifact summary, feedback) to capture on the new `agents` channel with the
  feedback text as the user's own words. Review mode by default: a
  `memory_draft` card, acceptance stores the fact, rejection leaves nothing.
  The channel's label and per-channel settings switch join the existing
  channel roster, and the memory page's capture surface lists it without
  code changes on the client.
- **The server renders the page; the SPA only links it.** `/agents` is a
  server-rendered page in the house style: a roster of agents with run forms,
  the run history with artifacts and receipts, and a feedback form per run.
  The SPA rail gains an Agents link and the bundle is rebuilt. No client
  script is added to the server page.
- **Artifacts are parsed tolerantly and printed escaped.** The presentation
  agent asks the model for a slide outline; the reply is parsed into
  (title, bullets) slides when it cooperates and rendered as a text outline
  when it does not. Nothing the model returns is ever interpolated as HTML.
- **Honest states over invented ones.** No endpoint configured, endpoint
  calls turned off, a failing call: each is a recorded degraded run with the
  pinned cause vocabulary the assistant already uses. A degraded run is kept
  in history with its cause, because the store holds what happened.
- **Skills join the recall contract.** The skill runner's prompt gains the
  same bounded facts block, ranked against the skill's prompt text, through
  the same helper the assistant uses. One line of integration, no new
  surface.
- **Audit rows: `agents.run` and `agents.feedback`**, alongside the existing
  `memory.capture` row the loop already writes for the channel.
- **Briefs and feedback are bounded** the way questions and retain excerpts
  are: a few hundred characters, trimmed, blank refused with a named error.
- **A local OpenAI-compatible mock ships as a tool**, so the end-to-end
  browser walkthrough (and any future demo) can run the full loop,
  BYOK-configure the desk against it, and show recall changing the artifact,
  without spending a real key. It is a test double for the endpoint, and the
  evidence names it as such.

## Testing Decisions

- **The HTTP API is the primary seam**, the house rule: tests boot the real
  server through the hermetic harness and drive `POST` the run and feedback
  routes over real sockets, then assert the memory cycle (review card
  appears, acceptance stores the fact, the next run's receipt contains it).
  Prior art: the server memory suites and the plugin runtime suites.
- **Unit seams only for pure parts**: the registry lookup, the prompt
  assembly (facts block present, bounds respected), the tolerant artifact
  parse, and the feedback transcript shape. Prior art: the memory service
  and loop unit suites.
- **Degradation is asserted, not avoided**: endpoint off, endpoint missing,
  endpoint raising each produce their named state, and no run row pretends
  success.
- **Hermeticity**: the new store boots in-memory in the harness; a test
  asserts a boot with no injection never writes the real user data
  directory, matching the standing invariant.
- **The browser walkthrough is evidence, not the test suite**: it exercises
  the same routes a user's hand would, against the mock endpoint, and its
  screenshots are filed under the repo's evidence directory.

*Testing-seam note: the user was away when this spec was cut; the seam follows
the repo's own primary-seam rule (the harness docstring) rather than a
confirmed choice. See Further Notes.*

## Out of Scope

- LLM calls inside plugins; the Class D guarantee and its validator rules are
  untouched.
- Multi-turn tool loops, streaming replies, or an agent that browses; a run
  is one prompt, one call, one artifact, like every model surface in the desk.
- Exporting real `.pptx`/`.xlsx` files; the artifact is the outline/briefing
  on the page.
- Marketplace listing, publishing or sharing of agents.
- Changes to recall ranking, embeddings, or the memory schema; the layer
  consumes the store as-is.
- Auto-approve of feedback facts; the review default stands.
- Plugin-card insight changes; that seam already recalls and keeps its own
  receipts.

## Further Notes

- Naming: the surface is **Agents** (`/agents`), the package `agents`. It
  sits beside Assistant and Research as a host surface, which is why it is
  not a plugin class.
- The mock endpoint tool exists so the demo's determinism is honest: the
  memory loop, capture, review and recall in the screenshots are all real;
  only the model's words come from the local double, and the evidence says
  so plainly.
- Open decision with recommended default: whether the worksheet-brief agent
  should also recall workbook-history facts from memory (it will not in v1;
  the excel-watch workbook channel already captures those facts, and the
  runner's recall will rank them when the brief mentions the workbook).
  Veto point for the next reader; tickets can be cut without resolving it.
