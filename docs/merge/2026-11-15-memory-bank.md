# memory-bank replication merge record, 2026-11-15

## Context

The teammate's memory-bank project (dhyeyvipulbhaid/memory-bank, MIT licensed) proved out a
local knowledge-graph memory system: facts with kinds and occurrence times, entities with
aliases and merge rules, hybrid recall over keyword, entity-graph and vector signals, LLM
fact extraction from conversations, derived observations with citations, and field-level
AES-256-GCM encryption. This port replicates that behavior natively on the agent-desk
chassis (Python stdlib plus one new dependency, below). It is a behavior replication, not a
vendor: no donor code is copied, and the donor tree stays checkable through the
`memory-bank` remote pinned at commit d35b686a2d757627e1b0cd78d56d10d9dec790fd. The spec is
issue #88 (snapshot at specs/002-memory-bank-port.md); the tickets are #89 through #96.

The user's settled decisions (2026-11-15): native Python port; approval-card retain (no
auto-capture, ever); probe-gated embeddings; encryption in scope, accepting the
`cryptography` package as the app's first third-party runtime dependency.

## Provenance

| Commit | Ticket | Donor (memory-bank) | Ported | Deliberate divergences |
| --- | --- | --- | --- | --- |
| 0f3218a | #89 | `src/schema.ts`, `src/dedupe.ts` | schema v2: sources, entities (aliases JSON, typed), edges, observations + citation tables, schema_meta versioning; facts gain kind (world/experience), occurrence_ts, source_id; one-time identical-fact dedupe on upgrade (normalized text, oldest keeper) | no `bank_id` isolation (single-bank app); no `source_chunks` (retained excerpts are single texts; chunking has no behavioral surface here); integer ids and epoch REAL timestamps instead of the donor's text ids and ISO strings; the ALTER-with-CHECK upgrade path is verified on SQLite 3.50 rather than diverging |
| d7c1714 | #90 | `src/hybrid.ts`, `src/recall.ts`, `src/tokens.ts`, `src/time-window.ts`, `src/names.ts` | deterministic hybrid recall: keyword leg (meaningful tokens, donor stopword list), graph leg (entity-name tiers 10+3p / 5+2p / 2p over canonical + aliases, one-hop seeding), RRF fusion k=60 unit weights, recency 0.5^(age/30d) on occurrence-else-created, UTC time-window parsing with drop + prior, final order score/created/id; store.recall and both surfaces (preview, assistant block) use it; block bounds unchanged (5 facts / 500 chars, whole facts) | the donor's stopword list is 61 words (the spec draft said 63; the donor source is authoritative and a test pins it); the donor's optional LLM rerank is not ported (a model call per recall would break offline determinism and latency); the vector leg is deferred to ticket #95 (fusion already accepts it at unit weight); the old overlap `rank()` remains exported and tested as the fallback scorer |
| 61ec067 | #91 | `src/extract/*`, `src/resolve.ts`, `src/names.ts`, `src/knowledge-gap.ts`, retain flow in `src/bank.ts` | the extractor port (donor system prompt verbatim, tolerant parse: think blocks, brace slice, facts array; validation: 2000-char bound, kind vocabulary, typed entities), knowledge-gap drops, cap five, the occurrence gate (kept only when the source text names an occurrence), entity resolution (exact/typo/weak tiers, longest-first, strong-then-any passes, strictly-best-positive-untied co-occurrence winner, alias accumulation, canonical promotion), `POST /memory/retain`, `memory_draft` inbox cards, `llm.retain` audit | approval cards are the only write path: the donor writes extracted facts directly, this chassis keeps the recorded no-auto-capture rule (accept an editable card or nothing); the chassis's single-prompt LLM seam carries the donor's system + user messages as one prompt, system first; the post-filters run in the route so injected fake extractors filter identically; zero surviving candidates write nothing at all (the donor keeps an orphan source row); ISO timestamps without offset read as UTC |
| 9193970 | #94 | `src/crypto.ts`, `src/sealed.ts`, `src/encrypt-bank.ts`, open-time binding in `src/db.ts` | field-level AES-256-GCM (envelope: version byte, 12-byte IV, ciphertext, 16-byte tag; AAD binds table/column/row id), HKDF-SHA256 empty-salt enc/mac keys under the donor info strings, HMAC-SHA256 blind indexes (fact text, entity names via entity_name_index, observation text and scope), key-check marker, one-transaction conversion (dedupe + prune first, sources, entities, facts, observations, marker; checkpoint + vacuum), dry-run counts, `memory.key` (32 bytes, 0o600 where honored), sealed reads require ciphertext so mixed state is a hard error, specific locked/wrong-key/refusal causes surfaced on the memory page, `memory.encrypt` audit | `cryptography>=44` becomes the app's first runtime dependency (user decision; dual Apache-2.0 OR BSD-3-Clause, admitted by the license manifest gate, which now understands OR-expressions); resolution under seal scans decrypted names rather than index-only (a recorded donor limit at personal scale); a running server re-binds its store in place after conversion instead of requiring a restart; the key file's restrictive permissions are best-effort on Windows |
| d9033d4 | #92 | write path of `src/dedupe.ts`, updateFact/removeFacts in `src/bank.ts`, prune in `src/reflect.ts`, sweep rules in `src/knowledge-gap.ts` | write-time dedup (normalized text; blind-index lookup under seal; occurrence backfilled into nulls only), edit-merge (mentions moved, edited row deleted, merge notice on the page), entity merge action on the memory page (alias union, edge relink, index trim), junk sweep: dry-run preview with reasons then all-or-nothing delete with orphan pruning, `memory.sweep` / `memory.merge` audits | the sweep POST re-verifies each id is still a junk candidate (400 stale, 404 missing) before deleting; entity merge upgrades the survivor's type only from "other", mirroring the automatic resolution rule; these supersede the #89/#94 pins that write-time dedup did not yet exist |
| 71e96fc | #93 | `src/reflector.ts`, `src/reflect.ts`, reflect flow in `src/bank.ts` | gather (query: hybrid top-40 non-derived keeping score >= best*0.5; no query: latest 40; since inclusive / until exclusive), the donor reflector prompt verbatim over `id / kind / created / text` lines, acceptance filters (speculative and meta regexes verbatim, confidence 0..1, citations within the gather, requireTwo with the single-entity exception, Jaccard >= 0.55 near-dup, cap five by confidence), scope-key upsert with unkept-row prune, `POST /memory/reflect`, `memory_reflection` cards, the observations section with citations, `llm.reflect` / `memory.observation` audits | approval cards pace the writes the donor makes atomically: save_observation takes the accepted card's created_ts so a multi-card run prunes exactly the pre-run rows (donor semantics) without deleting sibling cards; the embedding-cosine near-dup hook is deferred to #95; single-fact delete also prunes citations (the ticket criterion extends #92's remove_facts pruning); reflect failures reuse retain's degraded-turn JSON surface |

## Binding constraints honored

- Bring-your-own endpoint: extraction and reflection ride the chassis's existing LLM seam
  and its audit trail; no Ollama, no Bun, no new network surface (the embeddings route is
  #95, probe-gated, not in this merge).
- No auto-capture: facts enter only through an accepted inbox card or the memory-page
  form; chat alone never writes. Every new write path is an accepted card.
- The interruption budget: retain and reflect are user-triggered buttons; nothing is
  scheduled and no cards arrive unasked.
- Localhost and auth: every new route (`/memory/retain`, `/memory/encrypt`,
  `/memory/sweep`, `/memory/entities/merge`, `/memory/reflect`) authenticates like the
  rest and rejects bad origins.
- Hermetic tests: no test touches the network; extractors, reflectors and endpoints are
  scripted; clocks are injectable and frozen where recency matters.
- Permissive licenses only: stdlib plus `cryptography` (Apache-2.0 OR BSD-3-Clause); the
  manifest tool and THIRD-PARTY-LICENSES.md were updated in the same commit; the donor is
  MIT and nothing from it is vendored.
- Class D plugins: untouched; memory is a core feature, not a plugin surface.
- The audit trail grows with the feature: llm.retain, llm.reflect, memory.encrypt,
  memory.sweep, memory.merge, memory.observation join memory.fact.

## Out of scope, deferred

Open tickets on the same spec: #95 (probe-gated embeddings: capabilities probe, audited
embeddings client, backfill, the vector leg of hybrid recall) and #96 (server-rendered
graph view: entity/temporal/citation edges now possible, semantic edges once #95 lands).
Recorded known limits carried from the donor: sealed-mode entity resolution scans
decrypted names; encryption covers the file at rest, not the running process.

## Collaboration note

The `memory-bank` remote (dhyeyvipulbhaid/memory-bank) stays configured on the branch so
every donor path named above remains checkable against the exact tree it came from
(commit d35b686a). The donor is MIT licensed; this port replicates behavior with
attribution and copies no code.
