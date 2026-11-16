# Spec: knowledge-graph memory (memory-bank replication)

Seams confirmed with the owner: primary seam is the local HTTP API (boots the real
server); second seam is the Extractor interface with a scripted fake; third is the
memory package's pure functions tested directly. Donor reference:
dhyeyvipulbhaid/memory-bank at commit d35b686a (MIT), kept checkable as the
`memory-bank` git remote. This issue's body is canonical; this file is the
convenience snapshot.

## Problem Statement

The agent's memory today is a flat list of one-line facts matched by keyword
overlap. Ask the same thing with different words and the right fact is missed;
nothing links facts to the people, teams and products they mention; there is no
way to save what a conversation taught the agent without retyping it by hand;
long-lived observations have nowhere to live; and the memory database sits in
plaintext on disk. The teammate's memory-bank project proved the answers out
(locally, in TypeScript); this spec replicates its behavior on the agent-desk
chassis.

## Solution

Memory becomes a local knowledge graph. A "save this conversation to memory"
action extracts candidate facts through the app's existing LLM endpoint, and
every candidate waits in the inbox as its own editable card: nothing enters
memory until the user accepts it. Accepted facts carry a kind (world or
experience), an occurrence time when the text names one, and links to entities
(people, organizations, places, products, concepts) that merge automatically
across typos, aliases and partial names. Recall becomes hybrid: keyword,
entity-graph and recency signals fused deterministically, plus an optional
semantic (embedding) leg that activates only when the endpoint provides
embeddings; without it, recall silently stays deterministic. A reflect action
derives observations that each cite at least two accepted facts, again through
approval cards, listed separately from facts. Duplicate facts collapse on
write, junk (assistant knowledge-gap text) is swept on request, and the whole
memory database can be encrypted at rest with field-level AES-256-GCM using a
locally generated key. Auto-capture remains banned: facts enter only through an
accepted card or the explicit memory-page form.

## User Stories

1. As a manager, I want a "save this conversation to memory" action on the
   chat, so that useful things the agent learned do not evaporate.
2. As a manager, I want each extracted candidate fact to arrive as its own
   inbox card, so that I accept exactly what I want remembered.
3. As a manager, I want to edit a candidate fact's text before accepting it,
   so that typos and half-sentences never enter memory.
4. As a manager, I want to dismiss any candidate with nothing written, so that
   declining is always safe.
5. As a manager, I want a failed extraction to leave memory untouched with a
   plain-language cause, so that a broken endpoint never corrupts the bank.
6. As a manager, I want recall to find facts through the entities they mention,
   so that paraphrases still hit ("how is the Acme renewal going" finds "Renewal
   with Acme signed").
7. As a manager, I want recent facts to rank above stale ones, so that memory
   reflects what is current.
8. As a manager, I want time words in my question ("last week", "in March") to
   restrict recall to that window, so that time-scoped questions get
   time-scoped answers.
9. As a manager, I want facts to distinguish world facts from agent
   experiences, so that what the agent did and what it knows stay separable.
10. As a manager, I want a fact to record when something happened when the text
    names a time, so that "we met Tuesday" carries Tuesday.
11. As a manager, I want entity typos to merge automatically (one letter off,
    six or more letters long), so that "Stephanie" and "Stepahnie" are one
    person.
12. As a manager, I want partial names to resolve weakly ("Maya" matching "Maya
    Patel") only when unambiguous, so that common first names do not fuse two
    people.
13. As a manager, I want aliases kept on entities and visible, so that "Acme"
    and "Acme Corp" show as one entity with both names.
14. As a manager, I want a merge action on the memory page, so that I can fuse
    duplicate entities the automatic rules missed.
15. As a manager, I want to reflect on a topic, so that recurring patterns in my
    facts become durable observations.
16. As a manager, I want observations to cite the facts they rest on, so that I
    can check any conclusion in one glance.
17. As a manager, I want observations to wait in the inbox as cards, so that
    nothing derived enters memory unseen.
18. As a manager, I want hedging or speculative observations rejected, so that
    memory states patterns, not guesses.
19. As a manager, I want duplicate facts to collapse automatically, so that
    saving the same thing twice does not double it.
20. As a manager, I want a cleanup action that previews junk before deleting,
    so that knowledge-gap filler ("I don't know who Pepper is") leaves memory
    safely.
21. As a manager, I want to encrypt my memory with one action, so that the
    database on disk is unreadable without my key.
22. As a manager, I want a missing or wrong key to stop the app with a clear
    message, so that encrypted memory never silently falls back to plaintext.
23. As a manager, I want semantic recall when my endpoint offers embeddings,
    so that meaning-level matches work without me configuring anything.
24. As a manager, I want a backfill action for embeddings, so that existing
    facts gain vectors without re-entering them.
25. As a manager, I want an embedding failure never to block saving a fact, so
    that memory works even when the embedding model is down.
26. As a manager, I want a graph view of my memory, so that I can see how
    facts, entities and observations connect.
27. As the technical owner, I want every extraction, reflection and embedding
    call audited like every other outbound call, so that the audit trail stays
    complete.
28. As the technical owner, I want the prompt block bounded as today (at most
    five facts, five hundred characters), so that the assistant's context
    budget does not grow.
29. As IT, I want field-level AES-256-GCM with per-value IVs and
    table/column/row binding, so that ciphertext leakage between fields is
    structurally prevented.
30. As IT, I want lookups on encrypted data to use keyed blind indexes rather
    than plaintext, so that encryption does not disable dedup and recall.

## Implementation Decisions

Source of truth for every rule below is the donor at commit d35b686a; each
numbered rule is either a faithful replication or an explicit divergence with
its reason. The provenance table in the merge record maps every rule to its
donor module.

### Schema (in-place migration, version 2)

1. The memory database gains tables `sources` (original retained text, speaker,
   context, creation time), `entities` (canonical name, aliases as a JSON
   array, type constrained to person, org, place, product, concept, other),
   `edges` (one row per fact-mentions-entity, unique per pair),
   `observations` (scope key, text, confidence, created, updated),
   `observation_sources` (observation-to-fact citations), and a `schema_meta`
   key-value table carrying the schema version. Divergence: the donor's
   `source_chunks` table is not ported (retained conversation excerpts are
   single texts in this app; chunking has no behavioral surface here) and the
   donor's `bank_id` isolation column is dropped (single-bank app).
2. The existing `facts` table gains columns: `kind` constrained to world or
   experience defaulting to world, `occurrence_ts` nullable (epoch seconds,
   when the event happened, distinct from creation time), `source_id` nullable
   referencing sources, and later `embedding` blob, `embedding_model`,
   `embedding_dim` (added with the semantic phase). Existing rows migrate as
   kind world, no occurrence, no source. Divergence: the donor stores ISO
   strings and text ids; this chassis keeps epoch REAL timestamps and integer
   ids everywhere, matching every other store.
3. Migration runs at store construction, is idempotent, and performs the
   donor's startup dedupe once on upgrade: facts whose normalized texts are
   identical merge into the oldest row (mention edges move; occurrence and
   embedding backfill only into nulls).
4. The donor's observations design is kept: derived observations live in their
   own table with citations, not as flagged facts. The facts table has no
   derived column.

### Retain (extraction through approval cards)

5. An `Extractor` port (single callable, injected like the assistant's LLM
   closure) takes content, speaker, context, mentioned-at; returns candidate
   facts (text, kind, occurrence time, entities with name and type). The
   endpoint-backed implementation sends the donor's extraction system prompt
   verbatim and parses the reply with the donor's tolerant rules: strip think
   blocks, slice first brace to last brace, require a facts array, validate
   each fact (non-empty text at most 2000 characters, kind in vocabulary,
   parseable occurrence or none, typed entities).
6. Two error classes, both raised before anything is written:
   extractor-unavailable (endpoint unreachable or HTTP error) and
   extraction-failed (model answered but the payload is unusable). The bank is
   untouched; remember and recall keep working.
7. Candidates are filtered like the donor: assistant knowledge-gap texts
   dropped, at most five per retain.
8. The donor's occurrence gate is kept: an extracted occurrence time survives
   only when the retained source text itself names an occurrence (weekday,
   month-day, ISO date, numeric date, ordinal day, or relative-day wording).
   A clock time or a preference is not an occurrence; missing stays missing,
   never "now".
9. Divergence (binding): each candidate fact becomes its own inbox card (new
   card kind), editable as a draft, sharing a source id for grouping. The
   donor writes extracted facts directly; here acceptance of the card is the
   only write path, extending the existing card-acceptance fact flow with
   kind, occurrence, entities and the source link. Dismissal writes nothing.
   The retain action is a button on the chat surface posting the recent
   conversation; it follows the same endpoint gating and audit as every LLM
   call. The donor's automatic retain-on-transcript is deliberately not
   ported: auto-capture stays banned.
10. The memory-page add form stays text-only (kind defaults to world); the
    manual path does not grow entity fields. Entities flow from extraction,
    merges and the graph view.

### Entity resolution

11. Name normalization, display names and match tiers replicate the donor
    exactly: exact (normalized equal); typo (same token count, two or more
    tokens, exactly one differing token, edit distance one, longest token at
    least six characters); weak (leading-name subset: every token of the
    shorter name matches positionally with strictly fewer tokens).
12. Resolution order: mentions sorted longest-name-first; a strong pass
    (exact, then typo) before a weak pass; unresolved mentions create
    entities. When several candidates match, a co-occurrence winner (the
    candidate sharing the most distinct facts with already-bound entities,
    strictly best, positive, untied) decides; otherwise a new entity is
    created. Divergence: the donor's sealed-mode blind-index fast path is part
    of encryption, not resolution; the encrypted port resolves by scanning
    (acceptable at personal-bank scale, recorded as a known limit).
13. Type inference only upgrades from other; aliases accumulate (deduped by
    normalized form); a weak match with more tokens than the canonical name
    promotes the mention to canonical and demotes the old canonical to alias.
14. A merge action on the memory page fuses two entities (aliases union, facts
    relinked), for duplicates the automatic rules miss.

### Recall (deterministic hybrid)

15. Tokenization replicates the donor: NFKC, lowercase, split on
    non-alphanumerics; meaningful tokens drop single characters and a fixed
    63-word stopword list, deduped order-preserving. Token cost is estimated as
    one per four characters.
16. The keyword leg scores plus one per meaningful query token present in the
    fact's raw tokens. The graph leg scores entity names in three tiers (full
    phrase inside the query: ten plus three per name part; every part of at
    least three characters present: five plus two per part; any overlap: two
    per overlapping part), adds matched entities' weights to their facts, and
    one-hop expands: entities linked to already-scored facts seed their other
    facts at one.
17. Legs fuse by reciprocal rank fusion with k sixty and unit weights; the
    vector leg joins at unit weight when embeddings are active. Each list
    ranks score-descending then id; a leg's contribution is weight over k plus
    rank plus one (rank zero-based). Facts with no signal never recall.
18. Recency replicates the donor: score multiplies by one half per thirty-day
    half-life of age (occurrence time when present, else creation time;
    undated facts get factor zero). When the query names a time window the
    donor's parser recognizes (ISO day, month-day in either order, month with
    optional year, yesterday, today, tomorrow, last or this week with Monday
    starts, last or this month; missing year disambiguated against now), facts
    outside the window drop and in-window facts gain a small constant prior.
    Divergence: the donor computes windows in UTC for cross-machine
    determinism; the port keeps UTC and the injectable clock.
19. Final order: fused score descending, creation time descending, id
    ascending. The assistant prompt block and the recall preview use this
    ranking; the block's bounds are unchanged (five facts, five hundred
    characters, whole facts only). Divergence: the donor's optional LLM
    re-ranking step is not ported (a model call on every recall would break
    the app's offline determinism and latency posture; fusion order stands).
20. The existing simple overlap ranking remains exported and tested as the
    fallback scorer and migration baseline; the store's recall delegates to
    the hybrid ranker.

### Reflect (observations)

21. Gathering replicates the donor: with a query, hybrid recall of at most
    forty non-derived facts keeping those scoring at least half the best;
    without, the forty most recent; optional since (inclusive) and until
    (exclusive) filters on occurrence-else-creation time. Zero gathered facts
    is an error and writes nothing.
22. The reflector sends the donor's prompt verbatim (one observation per
    pattern, cite at least two facts, no hedging words, no meta commentary,
    confidence zero to one, at most five) over the gathered facts and parses
    like the extractor.
23. Acceptance filters replicate the donor: speculative-word and meta-comment
    regexes reject; confidence must be zero-to-one; citations must reference
    gathered facts and number at least two (one allowed only in a
    single-entity scope); near-duplicates drop (normalized equal, or token
    Jaccard at least zero point five five, or embedding cosine at least
    zero point eight five, keeping the higher confidence).
24. Divergence (binding): surviving observations become approval cards (one
    card per observation, text editable, citations shown); acceptance writes
    the observation with its citations. Reflect is a user-triggered action on
    the memory page (optional topic or entity), never scheduled, so the
    interruption budget is untouched. Observations render on the memory page
    in their own section with citations; re-reflecting the same scope upserts
    (matched by normalized text within the scope key) and drops unkept ones,
    exactly like the donor. Orphan citations and uncited observations are
    pruned whenever facts are deleted.

### Hygiene (dedup, update-merge, junk sweep)

25. Fact normalization (trim, collapse whitespace, lowercase) gates every
    write: identical normalized text reuses the existing row, linking new
    entity mentions, backfilling occurrence and embedding only into nulls.
    Editing a fact onto another fact's normalized text merges mentions into
    that fact and deletes the edited row.
26. The junk sweep replicates the donor: reasons empty, unknown placeholder,
    inability, knowledge-gap, session-narration (in that priority);
    sentence-level (a disclaimer mixed with a real sentence stays); dated
    events escape; dry-run preview lists candidates with reasons before any
    deletion; deletion also removes citations, orphan observations and orphan
    entities.

### Semantic leg (probe-gated)

27. A capabilities-style probe tests the endpoint's embeddings surface once
    (cached, re-testable), the same cache-then-retest pattern as the other
    gates. Embeddings activate only when the probe passes and a settings
    toggle (default on) allows them; otherwise recall is fully deterministic
    and the user sees nothing broken.
28. Embeddings call the endpoint's OpenAI-compatible embeddings route with a
    configurable model name (settings row, default text-embedding-3-small;
    veto point below). Vectors store as little-endian float32 blobs with model
    and dimension per row; cosine is brute force; only same-model
    same-dimension rows compare. A "backfill embeddings" action on the memory
    page embeds missing facts oldest-first, one committed row at a time
    (retryable), reporting counts; new facts embed at write when active. An
    embedding failure at write stores the fact without a vector, like the
    donor. Every embedding call is audited.

### Encryption (first runtime dependency)

29. Memory encryption is opt-in via a one-action conversion (settings
    confirmation), replicating the donor's design on the `cryptography`
    package, the app's first third-party runtime dependency (dual
    Apache-2.0/BSD, inside the license manifest's allowed set; pyproject,
    README's zero-dependency claims, the license manifest and the local CI
    gate all updated in the same ticket).
30. Crypto replicates the donor exactly: 32-byte key; HKDF-SHA256 with empty
    salt deriving an encryption key (info "memory-bank:enc:v1") and a MAC key
    (info "memory-bank:mac:v1"); per-value envelope version byte, 12-byte
    random IV, ciphertext, 16-byte GCM tag; associated data binds
    table/column/row-id; blind indexes are HMAC-SHA256 over the normalized
    text or name; a key-check marker row ("memory-bank-ok" sealed under the
    schema-meta aad) marks the database.
31. The conversion dedupes and prunes first, counts the fields it will touch
    (dry-run supported), then encrypts sources, entities (rebuilding the
    entity name index), facts and observations in one transaction, checkpoints
    and vacuums. Sealed writes blank plaintext columns; reads require
    ciphertext (mixed plaintext/ciphertext is a hard error, never a silent
    fallback); a marker without a key, a wrong key, or a key on a populated
    plaintext database each stop with a specific error.
32. The key is a locally generated file under the app's data directory with
    user-only permissions; the app reads it at startup when present.
    Divergence recorded: OS-keychain storage is deferred (the donor also
    leaves key management to the host); the library-level interface takes raw
    key bytes, like the donor.
33. Encrypted lookups (duplicate detection, entity name resolution) use the
    blind indexes; the recall path over an encrypted bank decrypts rows in
    memory (a known donor limit at personal scale, recorded).

### Graph view

34. A server-rendered graph page replaces the donor's dev-only graph server:
    nodes are in-window facts and observations (occurrence-else-creation
    instant, newest first, default two hundred, cap one thousand; labels
    truncated at eighty characters; recency shading with the same thirty-day
    half-life); edges cap at four thousand: semantic (cosine at least zero
    point seven two, top three per origin), temporal (consecutive nodes within
    seven days), entity (facts sharing an entity, next three in time order per
    entity), and directed observation-to-fact citations. Rendered as static
    server-side SVG; no client framework, no animation.

### Audit and policy

35. New audit vocabulary joins the existing memory entry: memory retain,
    reflect, encrypt and embedding actions, and every outbound extraction,
    reflection and embedding call carries the endpoint audit the assistant
    loop already writes. Facts still enter only via accepted cards or the
    memory-page form; chat alone never writes (existing tests stay binding).

## Testing Decisions

A good test exercises external behavior through a seam and asserts on
observable outcomes, never internals. Three seams, confirmed with the owner:

- Seam 1, the local HTTP API (primary): the harness boots the real server and
  drives the product without a browser. New coverage: retain action (success,
  endpoint-unavailable, unusable-payload) leaving the bank untouched on
  failure; candidate cards created, edited, accepted (fact plus entities plus
  edges plus source visible), dismissed (nothing written); hybrid recall
  preview and the assistant prompt block through paraphrase, entity linkage,
  recency under a frozen clock, and time-window queries; reflect happy path
  and rejection paths (speculative text, single-fact citations) with
  observation cards, acceptance and separate rendering; dedup on write;
  entity merge action; junk sweep dry-run then delete; encryption conversion,
  restart with key, wrong-key and missing-key errors, and recall over an
  encrypted bank; embeddings probe pass and fail with deterministic fallback;
  backfill counts; graph page contents. Authentication and origin rejection
  apply to every new route, as today.
- Seam 2, the Extractor port: a scripted fake (the donor's fake extractor is
  prior art) returns fixed candidates or raises; tests assert the prompt
  contract (verbatim system prompt, user message shape) and the tolerant
  parser (think blocks, fenced JSON, junk payloads) without any network. The
  reflector and embedder ride the same pattern.
- Seam 3, pure functions: normalization, match tiers and resolution order,
  fusion and recency arithmetic, time-window parsing, junk rules and near-
  duplicate rules tested directly with table-driven cases, extending the
  existing memory service tests.

Hermetic always: no network, no Ollama, no Bun; recency tests use an
injectable frozen clock. Prior art: the existing memory store, service and
server API tests; the scripted-endpoint LLM tests; the frozen-clock budget
tests. The existing memory tests remain binding where behavior is unchanged
(schema migration must keep them green unmodified) and are updated only where
this spec deliberately changes observable behavior (recall ordering).

## Out of Scope

- Auto-capture of any kind (retained transcripts are never scanned in the
  background); the donor's automatic retain stays out.
- The Ollama and Bun runtimes; the donor CLI and its dev graph server
  (replaced by the server-rendered page); ANN indexes; multi-bank isolation.
- The donor's optional LLM re-ranking of recall results.
- OS-keychain key storage (file-based key now, interface ready).
- Encrypting stores other than memory; full-database encryption.
- SPA/dashboards changes: memory surfaces stay server-rendered.

## Further Notes

Open decisions, each with a recommended default. These are veto points:
tickets may be cut against the defaults, and a decision changes here before
it changes in code.

- Embeddings model default: text-embedding-3-small on the endpoint's
  OpenAI-compatible route, overridable by settings row.
- Semantic toggle default: on (inactive until the probe passes).
- Key file name and location: memory.key in the app data directory, created by
  the encryption action with user-only permissions.
- Retain candidate cap: five per action (donor default).
- Reflect scope: user-triggered with optional topic or entity; no scheduled
  reflection in this phase.
- Divergences recorded here and in the merge record: no source chunks, no
  bank ids, integer ids and epoch timestamps, no LLM rerank, entity-graph
  resolution scans under encryption, observations approval-gated (the donor
  writes them), retain approval-gated (the donor writes directly).

Donor provenance: the `memory-bank` remote stays configured on the branch so
every rule above is checkable against commit d35b686a. The merge record
(docs/merge/2026-11-15-memory-bank.md) carries the commit-by-commit
provenance table when the port lands.
