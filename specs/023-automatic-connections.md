# Spec 023: The desk connects what a plugin brings to what it already holds

Status: proposed on 2026-11-23 as a first slice, and narrower than the
founder's direction. Read the correction below before building anything.
Parent spec: 022.

## Correction from the founder (2026-11-23, later the same day)

The founder's words: "But i want the underlying system to be hermes (or
hermes like) i just said don't make it into an explicit plugin. The feeling
should be autonomous like it's with hermes."

Read together with the first message, the direction is this: the agent
system underneath the desk is to be Hermes, or Hermes-like, and it is to
feel autonomous. The only thing ruled out is Hermes as an explicit plugin
(and, from the first message, as a separate assistant entry point).
Plugins stay data aggregators and connectors.

This spec was written narrower than that. What follows describes one
deterministic line on a plugin card, with no model call and no new loop
step, because the session read the first message as "Hermes stays a source
of patterns, never a runtime". That reading was the session's, not the
founder's. So:

- Treat what follows as, at most, a first visible slice of the connecting
  behaviour, not as the scope.
- The scope is the autonomous engine. The repository has already reasoned
  about it. `docs/research.md` A8.8 chose "Hermes Agent as the invisible
  engine" behind a thin adapter when autonomy is in scope. A9.2 (binding,
  2026-11-11) set the Hermes runtime aside for deployment reasons and kept
  "Hermes remains an optional future backend behind" the adapter
  vocabulary. `specs/001-agent-desk-v1.md` keeps "a future engine swap
  possible without touching the product". In the code today there is no
  adapter boundary: fifteen modules carry ported Hermes patterns behind a
  fixed-step loop.
- Whether the engine is the real Hermes Agent or the desk's own core made
  to behave like it is the founder's decision. It is open.
- Re-plan before building ticket #287.

## Problem Statement

The founder's direction, in their words: "I want the underlying system of
agents to work like hermes and grok bot, making automatic connections
between what already exists and what the plugins bring. Plugins are just
data aggregators and connectors."

What the code does today (read on 2026-11-23):

- Plugins bring data, and every plugin card explains only itself. Nothing
  relates a row a plugin produced to what the desk already holds.
- Seven deterministic name matches exist and none touches data a plugin
  produced. The meeting rule matches a calendar subject to people and
  companies in memory (`recommend/rules.py`); the workbook capture matches
  a row name to memory (`memory/resolve.py`). The gap between the two is
  the one this spec closes.
- Five of six insight families are keyed to plugin ids that were retired,
  so a plugin outside the one shipped family gets no reading at all.
- The assistant and research leave the connecting to the model inside one
  prompt (`assistant/context.py`): it needs a key, and the person cannot
  see which things were related.

The result is the founder's complaint in one sentence: cards that sit next
to each other and never meet.

## Solution

One deterministic step in the agent layer, where plugin cards already get
their reading: for every row a card shows, find the names it shares with
the people and companies the desk already holds, and show on the card what
the desk holds about them. It runs without a model, so it works with no
key and cannot invent a relationship.

A person sees it as one line on the card: "Also in your desk: Halvorsen
Freight, 3 things you told the desk, renewal call today at 14:38."

Later slices, each its own ticket and not in this one: a Decision when a
connection is time-bound and the two existing rules do not already cover
it; the same step feeding the assistant's context; an optional sentence
written by the model when the person asks for one.

## Implementation Decisions

**Plugins bring, the agent layer connects.** A plugin manifest never
declares a relationship. The connect step reads what a card already shows
and the desk's own names. Nothing user-facing is named Hermes.

**The index is built once per dashboard read.** It lives on the insight
context every family already reads (`insight/context.py::build_context`),
empty by default on `InsightContext`, so a context built directly in a
test behaves exactly as before. It holds every memory entity of type
`org` or `person` (canonical name and aliases) with what the desk holds
about it (its fact count and ids) and the next calendar event whose
subject names it, read from the day view's upcoming list.

**The match.** For each row of text a card shows, the longest entity name
present as a whole word, case-insensitive (`re.escape` with word
boundaries, so "Marlow & Finch" matches as written). One connection per
entity id, so a name and its alias count once. Longest match wins in a
row. At most three per card, in the order the rows name them.

**Refusals.** Entities not typed `org` or `person` (concepts are excluded,
as the meeting rule already does). A name whose longest word is under six
letters. A single-word alias. A sealed or locked memory bank contributes
no names (the existing precedent in `insight/context.py`): the card shows
no memory clause and nothing about locking, and calendar clauses still
work. An empty memory shows no line anywhere.

**Where it runs.** The workbook family (`insight/workbook.py`) passes the
tracker table's label column and merges the sentence into its note block.
A fallback family for any other card with list rows is added only if the
shipped payload shapes carry list rows in a predictable form; otherwise
it waits for its own ticket.

**It is a block, never an element.** The line is a note block with
`inputs=("rows", "memory", "calendar")` and `memory_notes` set, so the
card's existing "Used:" line stays honest and the element count tests are
untouched. It obeys the density preference and appears only while the card
is fresh.

**Copy.** "Also in your desk:" then one clause per name: the name, "N
thing(s) you told the desk", and the next event when there is one
("renewal call today at 14:38"). No rule names, no ids, no "entity".

**Known limit, said plainly.** On the sample desk both sides of the line
come from the labelled sample set, and a plugin card has no sample marker
of its own (a recommendation card does). The line does not claim
otherwise: the card it sits on already wears its SAMPLE DATA tag.

## Testing Decisions

- Unit, through the server harness: longest match wins; a name and its
  alias count once; the cap; each refusal (concept, short word,
  single-word alias, sealed bank, empty memory).
- Through the product: on the sample desk the Workbook tracker card's
  payload carries the line and it names only names that exist in memory;
  with an empty memory the payload carries no line; a card with no rows
  carries none.
- The frozen readiness list of spec 022 is unchanged.

## Acceptance Criteria

- On the sample desk the Workbook tracker card shows the line, and it
  names only names that exist in memory.
- A fresh desk with nothing saved shows no line on any card.
- No new setting, no new page, no new navigation.
- The targeted tests, the docstring gate and the full local gate pass.

## Out of Scope

- A new recommendation rule or a Decision card (a third rule tonight would
  duplicate the meeting rule, whose withdrawal on a sealed bank is
  unverified).
- Any model call.
- Cross-plugin comparison, polling, the assistant's context.
- New plugins or connectors.

## Further Notes

The second-opinion review of 2026-11-23 confirmed the plugin card as the
right surface for this slice (it renders on both the SPA and the no-script
page, and the receipt machinery already prints an honest "Used:" line),
set the refusals above from existing precedent, and warned that the
connection must be a block and never an element. It was asked about one
line on a card, not about an autonomous engine, so it says nothing about
the scope the founder means (see the correction at the top).
