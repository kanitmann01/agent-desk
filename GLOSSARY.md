# Nexuus Bot

**Nexuus Bot** is the product's name and the name of the agent inside it.
New copy says Nexuus Bot. Some identifiers carry the old code identity and
keep their names as compatibility contracts, so existing desks, plugins and
scripts keep working: the `agentdesk` Python import path, the `AGENTDESK_`
environment prefix, the `.agent-desk` data folder and the `agentdesk_session`
session cookie. They are not wordmarks, and new copy never imitates them: it
spells the product name.

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

## Architecture vocabulary

The desk's domain words and the interface names the architecture review
of 2026-11-24 introduced. The architecture vocabulary itself (module,
interface, seam, depth, adapter, leverage, locality) is the codebase-design
skill's; this file holds the product and engine terms.

### Product surfaces

- **Deck**: the presentation a run writes: one shell variant, the filled
  outline, the rendered preview, the pdf and the images, under a
  hex-named run folder.
- **Deck artifact**: the card a presentation run stores about its deck
  (pack identity, phase, the run-folder paths). One builder:
  `presentations.artifact.deck_artifact`.
- **Deck tool**: a capability a template pack declares; the run result
  and the audit record name the plugin whose catalog row answered
  (`presentations.tools.run_tool`).

### Presentation pipeline

- **Plan**: the LLM-chosen recipe sections for a brief
  (`pipeline.parse_plan`); a run that cannot be planned is degraded with
  the plan cause.
- **Fill**: turning each planned section into slides and the outline
  into a written deck. One entry, `pipeline.run_fill`, serves the fresh
  run and the research resume alike; it returns the delivered deck or a
  cause, and `pipeline.fill_cause` is the one mapping from a pipeline
  exception to the honest sentence.
- **Research pause**: a run that stops at the provider question and
  stores its state on the artifact; the resume calls the same
  `run_fill` entry.

### Plugins

- **Emission target**: the plugin target a dashboard card is answered
  for; an alias or instance-capable plugin folds into its target and is
  yielded once. The spine is `PluginRuntime.emission_targets`, under
  `layout_keys`, `widget_cards` and `record_dashboard_view`; each keeps
  its own edge decision (the unconfirmed-main-instance key, the tampered
  attention card, the pilot-view spend).
- **Safety grammar**: the containment patterns a manifest must speak
  (the safe name, the JSON selector grammar, the two path roots). One
  owner: `validator.grammar`; lint, runtime, sources and the plugin
  config import it.

### Marketplace and consent

- **Decision diff**: the scope diff that decides re-consent. The
  runtime's own diff (value-keeping, `pending_diff`) is the only one; a
  held update always waits for the user. The marketplace's manifest
  comparison fills the response's display lists only.

### Engine

- **Pass**: one loop wake: the steps run once, isolated, in declared
  order.
- **Step order**: a step's declared place in a pass (`Step.order`, the
  `STEP_ORDER_*` constants beside the registry); the pass sorts on it,
  stable on registration sequence, so import order carries no meaning.
- **Serialized store**: a store whose connection-touching methods run
  under its one re-entrant lock. The rule's one owner is
  `agentdesk.locking.serialized`; stores sharing a connection share the
  lock handed over by their boot (`agentdesk.locking.store_lock`).
- **Store guard**: the one refusal for an optional collaborator that is
  not configured (`DashboardHandler._require_store`): a 503 naming the
  store, and a None for the handler to return on.

### Memory recall

- **Hybrid recall**: the production scorer for recall (memory/hybrid.py).
  The retired token-overlap scorer was deleted with the 2026-11-24
  review; git history is its baseline.
