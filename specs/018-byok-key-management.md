# Spec 018: BYOK key management: named connections, per-job models, keychain secrets

Status: ready-for-agent (2026-11-21). Filed as issue #219; when the file
and the issue disagree, the issue body is the live copy.

## Problem Statement

The desk has room for exactly one model endpoint. Three settings rows (base
URL, API key, model) serve every model call, a second pair of rows serves
web research for presentations, and that is the whole configuration. The
key sits in the settings database in plaintext: masked on screen, readable
by anything that can open the file.

What a user with more than one provider cannot do today:

- Save two keys. One endpoint row means one provider at a time; switching
  means retyping the key.
- Give different jobs different models. The assistant, presentations,
  memory extraction and insight readings share one model string, when they
  read it at all: insight readings and plugin suggestions bypass the saved
  settings entirely, a known inconsistency.
- See models. The model field is typed blind; nothing lists what the
  endpoint offers.
- Keep keys safe. The plaintext row is the only store, so any backup or
  sync of the data folder carries the secret.
- Know a key works. The only test is a full chat completion, and nothing
  records health, last use or the last error.

The user's ask is the bar companies already meet: save keys, pick a
provider from presets, choose from the models the endpoint offers, and use
different keys for different jobs.

## Solution

Named connections in their own store, each bindable to a job.

- A new keys store (its own sqlite file in the data dir, the per-store
  schema pattern) holds connections: a label, a provider preset, a base
  URL, a keychain reference, a masked hint, optional headers for
  corporate gateways, default and enabled flags, health state, and a
  cached model list.
- Secrets live only in the OS keychain, written through the keyring
  library. The database stores references and masked hints, never secret
  material; there is no plaintext-file store.
- Seven jobs (default, assistant, agents, presentations, memory,
  insights, research-web) each bind to a connection and a model. One
  resolution hub answers which connection serves a job: the job's
  binding, then the default binding, then the single enabled connection,
  then environment variables, then a named "job unbound" error. Every
  model call-site routes through the hub.
- Migration on first boot: the legacy endpoint rows become connections,
  their keys move to the keychain, the default and research-web jobs
  bind, and the old rows stay read-only as fallback. The old endpoint
  form fields retire from the Settings page.
- The Settings page gains a server-rendered keys section: the connections
  list with masked keys, status badges and a default star; an add/edit
  form with a preset grid, console deep-links and a password field that
  reveals while you type; a per-job picker fed by cached or typed models;
  and a health strip.
- Testing a connection is a free model-list request; a one-token
  completion exists only as an explicit deeper check. Health updates from
  live traffic too.
- The audit trail records the key lifecycle, and every model-call row
  names the connection that served it.

## User Stories

1. As a user with a fresh desk, I want to pick a provider from a preset
   grid, have the base URL fill itself in, paste my key and save, so that
   configuring the desk is one screen instead of documentation reading.
2. As a user without a key yet, I want each preset to link to its
   provider's key console, so that I know where to get a key before I
   have one.
3. As a user pasting a key, I want the desk to check it with the provider
   when I save (a free model-list request, never a chat), so that a
   typo'd key is caught on the Settings page, not at the first broken
   answer.
4. As a user with a saved key, I want it shown only as a masked hint
   (first three and last four characters) and visible in full exactly
   once, while typing with a reveal toggle, so that I can check what I
   pasted and the value never returns to the screen afterwards.
5. As a user with a personal key and a work key for the same provider, I
   want both saved as separate named connections, so that switching is a
   binding change, not a retype.
6. As a user, I want to give the assistant one connection and model and
   presentations another, so that different jobs use different keys and
   models.
7. As a user, I want to star one connection as the default, so that
   unbound jobs have a home and a new surface works without per-job
   setup.
8. As a user with exactly one connection, I want every job to use it
   without any bindings, so that the simple case stays simple.
9. As a user editing a connection's label or base URL, I want the stored
   key kept when the key field is left empty and removed only by the
   separate clear action, so that fixing a typo never silently drops a
   secret.
10. As a user deleting a connection that serves jobs, I want to be told
    which jobs are bound before the delete lands, so that nothing goes
    quiet without my knowing.
11. As a user running Ollama, LM Studio or vLLM, I want a connection with
    no key at all, so that local models need no secret and no validation
    round-trip.
12. As a user with a saved connection, I want its model list fetched from
    the endpoint and offered in the job picker, so that I choose from
    what the endpoint actually serves.
13. As a user on an endpoint without a model list (Anthropic
    compatibility, some gateways), I want to type the model name by hand,
    so that a missing discovery endpoint never blocks saving.
14. As a user behind a corporate gateway, I want a custom connection with
    its own base URL and extra headers, so that gateways needing more
    than a Bearer key work like any preset.
15. As a user on Azure AI Foundry, I want the existing api-key header
    behavior to keep working, so that my current endpoint keeps answering
    under the new surface.
16. As a user who configures through environment variables, I want env to
    keep working when nothing is saved and saved connections to win over
    env when they exist, so that my setup survives the upgrade unchanged.
17. As a user running on env-supplied keys, I want the desk to never copy
    them into the keychain and never delete stored ones, so that env mode
    never mutates my saved secrets.
18. As a user upgrading with a saved endpoint, I want it to become a
    migrated connection with its key moved to the keychain and the
    default and research-web jobs bound, so that the upgrade changes
    nothing about what works.
19. As a user who makes a mistake in the new surface after upgrading, I
    want the legacy rows still there, read-only, as fallback, so that
    recovery is not a retype.
20. As a user whose test fails, I want the plain-language cause the desk
    already uses (rejected key, wrong base URL, a portal page, a
    timeout), so that the fix is named rather than a status code.
21. As a user with several connections, I want each one's badge to show
    ok, error or unknown with the last error inline, updated by real
    calls and not only by tests, so that a dead key is visible before a
    job fails on it.
22. As a user rate-limited by a provider, I want the connection marked ok
    with a limited note rather than broken, so that a quota answer is not
    reported as an outage.
23. As an operator reading the trail, I want key creates, updates,
    deletes and tests recorded and each model call naming the connection
    that served it, so that BYOK is auditable like every other desk
    action.
24. As a user on a machine with no keychain (CI, a headless box), I want
    the page to say secrets cannot be stored there and env still
    resolves, so that the state is named, not silent.
25. As a reviewer, I want the dependency statement to name keyring
    honestly and the packaged build's smoke test to keep passing, so that
    the app's dependency story stays true.

## Implementation Decisions

- **A new keys store owns connections.** Its own sqlite file in the data
  dir, created by the idempotent per-store schema step every store uses,
  constructed on (connection, clock) with one re-entrant lock serializing
  every statement, the inbox store's pattern. A connection row carries:
  id, label (unique), provider preset id, base URL, keychain reference,
  masked hint (first three and last four), headers for corporate
  gateways, is_default, enabled, status (unknown, ok or error),
  last_checked_at, last_error, last_used_at, a cached model list with its
  fetched-at time, created_at, updated_at. Multiple connections per
  provider are allowed, disambiguated by label. Rationale: the named
  connection is the object every surveyed tool and gateway converged on,
  and the store pattern is the house precedent.
- **Secrets live only in the OS keychain.** Written and read through the
  keyring library under one service name, one keychain entry per
  connection (username "key/<id>"); the database never stores secret
  material, and no plaintext-file store exists. keyring becomes the app's
  second runtime dependency: the touches-page dependency sentence, the
  SBOM and the license gate are updated with it, and the packaged build's
  smoke test in CI must still pass. Where no keyring backend exists (CI,
  headless machines), stored secrets simply do not exist: connections may
  exist with no secret, environment variables still resolve, and tests
  inject a fake keyring. Rationale: the split pattern (database
  reference, keychain secret) is the security research's recommendation,
  and the app already accepted a runtime dependency for encryption at
  rest.
- **A job bindings table maps jobs to connections.** job_key primary key,
  connection_id foreign key with cascade delete, model_id, updated_at.
  Seven jobs ship: default, assistant, agents, presentations, memory,
  insights, research-web; together they cover all fifteen model
  call-sites inventoried in the desk. Rationale: per-job assignment is
  the roles pattern from the dev-tools research, at single-user scale.
- **One resolution order, one hub.** For each model call: the job's
  binding, then the default binding, then the single enabled connection,
  then environment variables, then an explicit "job unbound" error naming
  the job. Saved-over-environment precedence matches today's documented
  behavior (saved settings win over environment variables). The hub
  extends the effective-client resolution the request path already
  resolves per call, and all fifteen call-sites route through it; this
  fixes the existing defect where insight readings and plugin suggestions
  ignore saved settings. Environment-supplied keys are never written to
  the keychain and never delete stored ones. Rationale: one resolution
  point makes the precedence documented, uniform and testable.
- **Migration is one boot, legacy read-only.** On the first boot after
  upgrade, legacy endpoint rows (and the research provider rows) become
  connections ("Migrated endpoint", "Migrated research provider"), the
  keys move into the keychain, the default and research-web jobs bind to
  them, the legacy rows stay read-only as fallback until the user deletes
  the migrated connections, and the old endpoint form fields retire from
  the Settings page. Rationale: nobody retypes a working key, and a desk
  that never opens Settings works exactly as before.
- **Validation is the free model-list request.** Testing a connection is
  a GET of the model list at its base URL with its key: free, and
  independent of any model. When a provider has no model-list endpoint
  (Anthropic compatibility), a one-token chat completion (max_tokens=1)
  runs only on explicit user action. Failures reuse the adapter's
  plain-language cause vocabulary. Status mapping: 401/403 mark the
  connection error, 429 marks it ok with a limited note, 5xx and timeouts
  are transient and keep the last status; last_used_at and last_error
  update from live traffic as well as tests. Rationale: validation must
  depend on the key alone, never on one blessed model.
- **The UI is server-rendered on the existing Settings page.** Not the
  SPA. Components: a connections list (label, preset, masked key, base
  URL, status badge, default star, Test, edit, and delete with a
  bound-jobs warning); an add/edit form (preset grid auto-filling the
  base URL and a console deep-link, a password field with reveal while
  typing, manual model entry always available); a per-job picker
  (connection select grouped by provider, model select from the cached
  list or typed); a health strip. Edit semantics: an empty key field
  keeps the stored key, and a separate clear action removes it, replacing
  today's split behavior where the endpoint form clears on empty and the
  research key keeps. Local presets (Ollama, LM Studio, vLLM): key
  optional, no keychain write, validation skipped for localhost base
  URLs. Rationale: the house rule that every page works without
  JavaScript, and one key-edit semantic everywhere.
- **A verified preset catalog.** openai, anthropic-compat, openrouter,
  groq, together, gemini, deepseek, mistral, ollama, lmstudio, vllm, and
  custom (base URL plus optional headers). Each preset carries its
  default base URL, a console URL for the deep-link, and whether the key
  is optional. The adapter's existing Azure/Foundry behavior (api-key
  header instead of Bearer on those hosts) keeps working under the custom
  preset. Rationale: presets remove the two first-run stumbles (where do
  I get a key, what is the base URL) with facts checked in the research.
- **The audit trail learns the key lifecycle.** New vocabulary rows
  keys.create, keys.update, keys.delete and keys.test in the audit
  store's pattern; the existing llm.* rows record which connection served
  each call. No secret material in any row. Rationale: a key lifecycle
  event is a decision like every other audited one.
- **The API joins the declarative route table.** Localhost JSON routes
  for listing, creating, updating and deleting connections (masked hints
  only; the secret is never echoed after create), testing a connection,
  listing models (cached, with an explicit refresh), and reading and
  writing job bindings. Binding writes ride POST, the only write method
  the dispatch table carries. Unknown fields are a 400 naming the
  accepted fields, the endpoint-save pattern. The upstream model-list GET
  happens server-side only. The route table is pinned verbatim by its
  test, so table and test change in one commit. Rationale: the table's
  ordering contract and the refusal vocabulary stay intact, and any drift
  is a test failure.

## Testing Decisions

- **The primary seam is HTTP end to end.** Tests boot the real server
  through the hermetic harness and run loopback stub endpoint servers
  that record the Authorization header and the model field of what
  arrives, so one test asserts job routing in full: which key, which
  base, which model served which job. Prior art: the settings API suite,
  the research API suite (its stub endpoint), the chat adapter suite
  (its scripted endpoint).
- **One new unit seam: job resolution on the keys store**, tested as a
  pure order table: binding, default binding, single enabled connection,
  environment, and the named unbound error.
- **Masking, validation and migration are asserted through the HTTP
  seam**: masked hints only in page and payloads; a stub answering 401
  turns the badge to error with the named cause; a pre-seeded legacy
  settings row comes back as a migrated connection with its jobs bound
  and its key out of the database.
- **The server-rendered forms are asserted through the same seam**: the
  Settings HTML contains the masked keys and preset entries, and the POST
  semantics (empty key keeps, clear removes, delete warns with the bound
  jobs) are real form posts, not script behavior.
- **A fake keyring is injected in tests**, and the CI python job passes
  with no OS keychain anywhere.
- **The route table and its pinning test are updated together**; drift
  between them is a failure by construction. Prior art: the route table
  suite.
- **The packaged build's smoke test staying green is an acceptance
  criterion**, not a nice-to-have, because keyring must package.

## Out of Scope

- Spend tracking, budgets and per-key caps.
- Virtual keys, teams, RBAC, anything multi-user.
- Fallback chains across providers, and model-class aliasing.
- The native Anthropic Messages API; the compatibility endpoint remains
  the only Anthropic shape.
- Moving Settings into the SPA.
- Background auto-rotation of keys, and auto-refresh of model lists.

## Further Notes

- Open questions, each with a recommended default; none is critical and
  tickets can be cut without resolving them:
  - The exact call-site-to-job mapping for the fifteen sites.
    Recommended default: research questions, assistant turns and the
    paused fill ride assistant; skill runs and the agents runner ride
    agents; presentation runs ride presentations and their web research
    rides research-web; memory extract, retain, reflect, observe and
    embeddings ride memory; insight readings and plugin suggestions ride
    insights; the wizard compiler and calendar breakdowns ride default.
    Veto point for the implementing reader.
  - Whether the settings-bound chat closure gains an explicit timeout
    parameter while the hub routes through it (presentations paper over
    its absence with introspection today). Recommended default: yes, add
    the parameter and remove the introspection. Veto point.
- The keyring/Nuitka packaging risk is the one place a locked decision
  can fail for environmental reasons: keyring discovers its backends
  through package metadata at runtime, which standalone Nuitka builds can
  fail to carry. The CI build smoke passing with keyring present is the
  acceptance criterion; if it fails after a reasonable packaging attempt,
  the fallback plan is encrypted-in-database secrets via the existing
  cryptography dependency, with the app key in a local key file exactly
  like the memory bank's, the same store schema, and the keychain
  remaining primary wherever the build supports it. The fallback is a
  replacement store, not an addition: still no plaintext file, ever.
- The full key is visible exactly once, in the create form, with reveal
  while typing; after save, the masked hint is the only form it takes.
  The JSON routes never echo the secret, so nothing key-shaped reaches
  the SPA.
- The config.env file rides the environment leg of the resolution order,
  exactly as today.
