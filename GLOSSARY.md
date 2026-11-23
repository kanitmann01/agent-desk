# Agent Desk

The words the desk uses for its own concepts, on screen and in code. One
concept, one word. The words under _Avoid_ are still read in old code and
old documents; they are not written in new copy or new identifiers.

## Language

### The model

**AI connection**:
A saved provider together with its key and the model it uses. It is the
desk's only way of reaching a language model. On screen it is "Your AI".
_Avoid_: endpoint, provider (for the whole thing), model connection, a bare "connection"

**Model**:
The exact model name an AI connection sends with every request.
_Avoid_: model id, model_id

**Job**:
One place the desk asks the model something: the assistant, memory, the
calendar breakdowns, insights, web research, presentations, the wizard.
Internal only; on screen it is "what uses your AI".
_Avoid on screen_: job, binding, bound, unbound

### The tools

**Source**:
A business tool the desk reads: the sales workbook, the calendar, the mail
folder. On screen it is "Your tools".
_Avoid_: data source, bridge, watch, connector (until a connector framework exists)

**Get started strip**:
The three-step checklist at the top of the home screen, shown only while
the AI or a real source is not connected.
_Avoid_: onboarding, setup wizard, tour

**Sample data**:
The labelled example set a fresh desk opens with so every tile can be
tried before any real source is connected. Everything in it carries the
words "Sample".

### What the desk shows

**Tile**:
One box of the home screen: Pipeline, Moves, Decisions, Digest, Desk
health, Tracker, Page watch.
_Avoid on screen_: widget, card (for a home-screen box)

**Suggestion card**:
One item in the Inbox that the desk proposes and the user accepts or
dismisses in one click.

**Decision**:
A suggestion card that asks the user to do something, shown with its
reason and a "Not now".

**Plugin**:
An add-on that gives the desk a new tile or tool, installed from the
catalog or built by describing it in plain English.

**Skill**:
A saved ask that re-runs in one click.

### Memory

**Fact**:
One thing the desk remembers about the user or their work, together with
where it came from. Recall reads facts and nothing else.
_Avoid_: knowledge point, entity line, observation (for a single fact)

**Learning**:
The desk saving facts by itself from how the user works. On screen it is
"Learn automatically".
_Avoid on screen_: capture, auto-approve, retain, extraction, reflect

## Connecting (spec 023)

**Connect step**:
The agent layer's step that relates what a plugin's card shows to the
people and companies the desk already holds. On screen it appears as
"Also in your desk". It is never a plugin's job, and nothing on screen is
named Hermes.
