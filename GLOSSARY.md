# Glossary

The desk's domain words and the interface names the architecture review
of 2026-11-24 introduced. The architecture vocabulary itself (module,
interface, seam, depth, adapter, leverage, locality) is the codebase-design
skill's; this file holds the product and engine terms.

## Product surfaces

- **Deck**: the presentation a run writes: one shell variant, the filled
  outline, the rendered preview, the pdf and the images, under a
  hex-named run folder.
- **Deck artifact**: the card a presentation run stores about its deck
  (pack identity, phase, the run-folder paths). One builder:
  `presentations.artifact.deck_artifact`.
- **Deck tool**: a capability a template pack declares; the run result
  and the audit record name the plugin whose catalog row answered
  (`presentations.tools.run_tool`).

## Presentation pipeline

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

## Plugins

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

## Marketplace and consent

- **Decision diff**: the scope diff that decides re-consent. The
  runtime's own diff (value-keeping, `pending_diff`) is the only one; a
  held update always waits for the user. The marketplace's manifest
  comparison fills the response's display lists only.

## Engine

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

## Memory

- **Hybrid recall**: the production scorer for recall (memory/hybrid.py).
  The retired token-overlap scorer was deleted with the 2026-11-24
  review; git history is its baseline.
