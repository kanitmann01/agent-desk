# Spec 023: The autonomous engine: the desk acts in its first ten minutes

Status: re-planned on 2026-11-23 (evening) on the founder's engine
decision and research read from primary sources the same night. This
spec replaces the "one line on a plugin card" slice, which stays inside
as the first visible step (ticket 023-1). Parent spec: 022.
Engine decision: #276.

## Direction from the founder (2026-11-23, three statements)

First: "I dont want another plugin or assistant point as hermes. I want
the underlying system of agents to work like hermes and grok bot, making
automatic connections between what already exists and what the plugins
bring. Plugins are just data aggregators and connectors."

Then: "But i want the underlying system to be hermes (or hermes like) i
just said don't make it into an explicit plugin. The feeling should be
autonomous like it's with hermes."

And, choosing the engine ("the real Hermes Agent, or our own core made
to behave like it?"): "find a complete python alternative to hermes,
there must a github project someone ported, if not, run the actual
hermes or hermes llike engine (take small parts of the system) and patch
it for our work, its a POC rn, if needed we will port later incase
nothing like that exists."

Read together: the agent system underneath the desk is Hermes, or
Hermes-like, and it must feel autonomous. The engine question is decided
in this order: a complete Python alternative first; if none holds up,
the real Hermes, taking small parts and patching them in, as the proof
of concept. Ruled out, unchanged: Hermes as an explicit plugin, as a
connection, or as a separate assistant entry point. Nothing user-facing
is named Hermes. Plugins stay data aggregators and connectors.

This reopens `docs/research.md` A9.2 ("Do NOT deploy the Hermes
binary", binding since 2026-11-11) for the POC, by the founder's
decision. A8.8's sentence remains the design's spine: "The adapter
interface is the asset; the engine is replaceable."

## What the research found (2026-11-23, primary sources)

- **No complete Python port exists.** GitHub searched the same evening:
  the only Python reimplementation of OpenClaw (Hermes's ancestor) is
  stale since May 2026 with 67 stars; nothing reimplements Hermes. The
  closest Python-native runtimes each miss something the desk needs
  (skills, cron, memory, an embeddable runtime) or need Node.
- **Hermes Agent is Python** (NousResearch, MIT, v0.23.3): the loop,
  tools, skills, memory, cron and CLI are Python; TypeScript is its
  terminal UI, web UI and desktop app only.
- **It runs headless**: `hermes -z "<prompt>" --format stream-json
  --base-url <url> --api-key <key> --model <id>`; one JSON event per
  line, any OpenAI-compatible endpoint, a user-supplied key.
- **Two deployment facts, measured**: its manifest effectively requires
  Python 3.14 (the core dependencies are pinned behind
  `python_version >= '3.14'` markers, and 3.14 is what this machine
  runs); and it refuses to build from source by design ("distributed
  via the shell installer, Docker image, or Nix"; an editable install
  from a clone is the remaining path). The PowerShell installer is the
  path A9.2 objected to.

## Problem Statement

The desk has a scheduler, not an agent. Read from the code on
2026-11-23:

- The loop's first full pass is a whole interval out (60 minutes by
  default) unless "Run now" is pressed (`agentloop/schedule.py`
  defers the first run on first sight). A fresh desk does nothing by
  itself for an hour.
- The dashboard fetches once on mount and then only after a user
  action (`App.tsx`); no poll, no event stream. When the desk has
  acted, the screen does not change by itself. Only the Memory page's
  island refreshes on its own.
- Nothing connects what a plugin brings to what the desk holds. The
  seven deterministic name matches never touch plugin rows; five of
  six insight families are keyed to retired plugin ids, so a plugin
  outside the one shipped family gets no reading at all.
- Every action the loop takes is not recorded: the rank step rewrites
  or snoozes cards with the ledger deliberately dropped, so Activity
  misses it and it cannot be undone.
- There is no engine boundary. Fifteen modules carry ported Hermes
  patterns behind a fixed-step loop; the "adapter vocabulary" A8.8 and
  A9.2 rely on was never drawn.

## Solution

The desk runs the real Hermes Agent as a **side-car engine**, and takes
small parts of it, patched for this product, as the POC. The desk keeps
its pure-Python core, its stores and its 3.10 floor untouched; the
engine lives in its own pinned install (its own venv, the tag pinned)
and is driven one turn at a time. The desk hands the engine a small
vocabulary of desk tools; every action the engine takes goes through
the desk's ledger, so it is visible in Activity and undoable.

Four behaviours, agreed with the founder as the first ten minutes, in
this order:

1. **It acts by itself, soon.** Within two minutes of a fresh desk's
   first start, with no "Run now", the desk has done something on its
   own: a desk check, a suggestion, a learned line. Anything at all,
   visible.
2. **The screen changes when it has acted.** The dashboard notices on
   its own, the way the Memory island already does, and says what
   changed.
3. **It connects what plugins bring to what the desk holds.** A card
   that shows a name the desk already knows says so, with its sources.
   The one-line slice (ticket 023-1, kept) is the first step; the
   engine extends it to rows no rule names today.
4. **Everything it does unasked is visible and undoable.** Activity
   lists it; Undo works; nothing skips the ledger, including the rank
   step that skips it today.

## Implementation Decisions

**The boundary is drawn first.** New `src/agentdesk/engine/` owns the
vocabulary, and nothing outside it imports the engine's backend: one
call that runs a turn ("given this context and these tools, act"), one
event stream in, one structured result out (actions taken, each with
its ledger shape). Two backends sit behind it: the side-car Hermes
process, and, when it is absent, the desk's existing fixed loop
(degraded but working, exactly today's behaviour). The fallback is not
a regression path; it is how the POC stays optional on machines that
cannot run the side-car.

**The side-car runs pinned and contained.** The engine backend shells
out to the pinned tag (v0.23.3) in its own venv, one `hermes -z` per
turn with `--format stream-json`, `--base-url` and `--api-key` set from
the desk's saved connection (the resolution hub as it stands). Its home
folder is under the desk's data folder, never the user profile root.
The PowerShell installer is not part of any user path in the POC; the
editable, pinned venv is created by a documented script a technical
owner runs once (dev machines and this POC only, which is where the
founder drew the line: "its a POC rn").

**The desk's tools are the engine's hands.** A token-scoped local
route (`/api/engine/tools`, its own token minted at boot, loopback
only; this closes the known gap #276 recorded for the presentation
tools) exposes a small, read-mostly vocabulary: read the dashboard's
names (workbook rows summary, agenda, memory's org and person names),
add one suggestion card through the existing builder, propose one
memory fact through capture's normal review path, and run the desk
check's read-only probes. Writes go through the desk's own handlers so
the audit trail and the ledger stay honest; the engine never writes a
store directly.

**Every action pays the ledger toll.** `may_act` stays the gate; the
rank step records its entry (a new undo kind for a re-ranked or
snoozed card); the engine's tool calls land as ledger entries with
`undo_kind` set, or they are refused. Nothing autonomous happens
outside Activity.

**The first run comes now.** `schedule.interval_due` records "now" on
first sight instead of deferring a full interval, and the startup
desk-check window widens to cover the first pass (the map's smallest
change). The pinned tests that assert the hour-long deferral are
re-worded, not deleted.

**The screen listens.** The dashboard polls `/api/dashboard` every
eight seconds while the tab is visible and pauses when hidden, the
Memory island's own pattern (`MemoryLoop.tsx`); a change in the
payload's agent-activity stamp re-renders and names what changed, one
line, in the Brief's existing voice. No socket, no SSE, no new
dependency.

**The connect step (kept slice, ticket 023-1).** As specified on
#287: the index of org and person entities built once per dashboard
read, the longest-whole-word matcher, the refusals, the "Also in your
desk" line as a note block with its sources named. It runs without a
model, so it works with no key and cannot invent a relationship.

**Copy.** Nothing user-facing is named Hermes. The engine's activity
reads as the desk's own: "The desk checked your sources", "The desk
suggests", "The desk learned". The Activity page and the ledger spell
the same words.

## Testing Decisions

- The harness gains a `FakeEngine` returning canned events, so every
  engine-driven test stays hermetic and offline; the side-car itself is
  never started by a test.
- The side-car smoke is an opt-in script (`tools/engine_sidecar_check.py`),
  not part of CI: it boots the mock endpoint, runs one real turn, and
  prints the event kinds it saw. It is evidence, not a gate, until the
  engine lands in its own spec slice.
- Four new readiness checks extend the frozen list with new numbers
  (the rule: a new check is a new number, none removed):
  R26 a fresh desk acts by itself within 120 seconds of first boot;
  R27 the dashboard payload carries what changed and the poll hook
  re-fetches (HTTP check plus vitest for the hook);
  R28 the connect line names only names the desk holds (HTTP check on
  the sample desk, per #287);
  R29 every action in the engine's first pass has a ledger entry with
  an undo kind, and Undo works on one of them.
- The four behaviours are also pinned by harness tests at the seams
  the map named: the first-run seed in `agentloop/schedule.py`, the
  poll in `App.tsx`, the connect matcher as a pure function, and the
  ledger toll on the rank step.

## Acceptance Criteria

- A fresh desk, left alone, has acted within two minutes of first
  start, and the dashboard has said so by itself, without a click.
- A plugin card on the sample desk names what the desk holds about the
  names it shows, with its sources; a fresh desk shows no line.
- The engine's first pass leaves every action in Activity, each with a
  working Undo; the rank step no longer skips the ledger.
- With the side-car absent, the desk behaves exactly as today (the
  fallback proves the boundary).
- R26 to R29 pass; the full local gate passes; nothing user-facing is
  named Hermes; no new plugin, connection or assistant entry point
  exists.

## Out of Scope

- Messaging connectors, computer use, browser tools, the terminal and
  web UIs, Nous Portal, the updater: none of the side-car's surfaces
  are exposed; the desk drives one turn at a time over its own
  vocabulary.
- Shipping the side-car to a locked-down corporate laptop (A9.2's
  territory; the POC runs on dev machines, and the fallback covers
  machines without it).
- Replacing the assistant's single-prompt path, multi-agent, or
  cross-plugin write access.
- Any new setting, page or navigation beyond what the behaviours need.

## Further Notes

**History.** This spec was first written (2026-11-23, morning) as one
deterministic line on a plugin card, under the session's reading that
Hermes stayed a source of patterns and never a runtime. The founder
corrected that reading the same day, chose the engine order that night
(alternative first, else the real Hermes patched in, as the POC), and
this rewrite records both. The second-opinion review of the morning
slice (the surface, the refusals, block-not-element) survives inside
ticket 023-1, which is again the first thing to build.

**The loop map this spec was written from** (facts with references,
read 2026-11-23): the step registry and first-run deferral
(`agentloop/loop.py`, `agentloop/schedule.py`), the boot desk-check
(`deskcheck/fixes.py`, the two auto-fixes and their ledger kinds), the
rank step's missing ledger entry (`recommend/rank.py`), the
dashboard's single mount fetch (`App.tsx`) against the Memory island's
visible-tab poll (`MemoryLoop.tsx`), the deterministic rules
(`recommend/rules.py`) and the retired insight families
(`insight/service.py`), the single prompt with no tool calling
(`llm.py`), and the ledger's kinds and gate (`ledger/store.py`,
`ledger/undo.py`, `ledger/__init__.py`).
