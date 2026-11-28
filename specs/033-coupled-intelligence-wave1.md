# Spec 033: Coupled intelligence wave 1

**Status:** ready-for-agent (2026-11-26). Workspace-internal wave, no GitHub issues filed. Tickets: `docs/tickets/2026-11-26-coupled-intelligence-wave1/01` through `06`
`GLOSSARY.md` is the vocabulary.
Builds on Spec 009 (coupled intelligence) and Spec 010 (acting on the reading).

## Problem Statement

The coupled readings already tell the user what a tile holds and let them press a button to explain a range or draft a reply, but four gaps keep the desk from feeling attentive and trustworthy day to day:

1. **No sense of change since the last visit.** Opening the desk after a day away shows the current numbers and threads with no memory of what the user last saw. A background poll refreshes the screen every few seconds, so any naive comparison against the previous poll erases the difference before the user notices it.
2. **Shallow provenance.** A tile prints a one-line receipt ("Used: your chart preference · memory (2 notes) · this tile's rows") without letting a sceptical reader inspect which exact columns or cells, which rule and threshold, or which cited facts and sources stand behind the sentence.
3. **One-sided research readings.** A stored research answer gets next-question prompts and memory links, yet never names what evidence would overturn its own conclusion or gives the user a one-click way to test counter-evidence with Your AI.
4. **Row-level anomaly without cause or next step.** An outlier finding on the workbook tile names the odd row and its standard-deviation gap, leaving the user to hunt through the table for which category or date segment shifted most and what to check first.

## Solution

Extend the existing host-side insight seam and both dashboard surfaces (the SPA and the server-rendered fallback page) with four tightly scoped loops, keeping plugins declarative, keeping GET reads pure, and keeping every new model call behind an explicit press:

1. **What changed since you last looked.** Persist a compact per-tile perceptual snapshot keyed by tile identity whenever the user explicitly views the dashboard, never on GET reads or background polls. On each read, diff the current tile against its last-viewed snapshot to prepend one concise perceptual delta line at the top of the tile ("Since you last looked: ...") covering live/attention transitions, sheet column or value moves, threads appearing or going quiet, next meeting shifts, or newer research answers.
2. **Provenance-first trust surface.** Carry memory fact identifiers alongside sources through the existing read-only recall context, attach structured `"why"` drilldown entries (claim, columns, bounded cell references, rule and threshold, cited fact IDs and sources) onto the reading's resolved `"receipts"` block, and surface them behind a zero-script expandable "Why" disclosure on both surfaces without altering existing pinned insight keys or element shapes.
3. **Research that argues back.** Deterministically generate one "What would change my mind" falsification block on every non-empty research reading from the stored answer's claims, and attach a "Check counter-evidence" press action that passes the bounded claim and falsification criterion through the existing press route with full disclosure and model-off refusal.
4. **Anomaly -> cause -> action.** Extend workbook outlier detection so that, whenever a table carries a categorical text column or a date column, it identifies the segment that shifted most from the rest of the column and appends one concrete action (falling back to a concrete row check when no segment column exists), while keeping the finding inside the existing element cap.

## User Stories

1. As a returning user, I want each tile to open with one quiet line telling me what changed since my last visit, so that I spot movement immediately instead of re-reading every number.
2. As a user leaving the dashboard tab open while background polls run, I want background polls never to overwrite my last-viewed baseline, so that the change since my previous visit stays visible while I read.
3. As a first-time user with no prior view recorded, I want tiles to show no invented change line, so that the desk never fabricates movement on an empty history.
4. As a workbook user, I want the change line to call out a newly appeared column or a moved summary figure, so that structural sheet edits do not go unnoticed.
5. As a mail brief user, I want the change line to tell me when a new thread arrived, a thread went quiet, or a waiting thread aged, so that inbox drift is legible at a glance.
6. As a calendar user, I want the change line to name when my next meeting moved time or changed title, so that schedule shifts stand out at the top of the tile.
7. As a research user, I want the change line to note when a newer research answer landed, so that I know the brief refreshed.
8. As a sceptical user, I want every reading's receipt line to carry a one-click "Why" drilldown, so that I can inspect the exact basis of a claim without cluttering the tile.
9. As a workbook user inspecting "Why", I want to see the columns, bounded cell references, and statistical rule/threshold that fired, so that I can verify the desk's arithmetic.
10. As a user inspecting "Why" on a reading that consulted memory, I want to see the cited fact IDs and sources without raw private fact text leaking into the trust payload, so that provenance is auditable and safe to share.
11. As a user inspecting "Why" on a workbook tile connected to desk entities, I want to see which held org or person and fact count matched, so that "Also in your desk" links are traceable.
12. As a no-JS server-page user, I want the "Why" drilldown and the top-of-tile change line to work using native HTML disclosure markup, so that zero client script is required.
13. As a research user reading a stored answer, I want a deterministic "What would change my mind" line beneath the reading, so that every answer names what would falsify it even when Your AI is off.
14. As a research user wanting to test a conclusion, I want a "Check counter-evidence" button that asks Your AI for the strongest opposing evidence or blind spot, so that confirmation bias is challenged in one press.
15. As a user pressing "Check counter-evidence", I want to see an exact disclosure of what travels and what stays local, and a clear refusal when Your AI is turned off, so that no call surprises me.
16. As a workbook user seeing an outlier finding, I want the reading to name the category or date segment that moved most and one concrete action to verify it, so that an anomaly tells me where to look next.
17. As a workbook user with an outlier on a flat-label table that has no categorical or date segments, I want a concrete row-level check action without an invented segment, so that the desk stays honest.
18. As an operator running tests or upgrading existing tiles, I want existing card payloads without snapshots, provenance, or falsification blocks to keep their exact previous wire keys and element ordering, so that backward compatibility holds.

## Implementation Decisions

- **Preserve existing wire invariants at the seam.** Existing tests pin the exact top-level keys of `payload["insight"]` (`status`, `source`, `preferences`, `note`, `blocks`, `press`) and exact element sequences on workbook and research readings. All Wave 1 additions ride inside `payload["insight"]["blocks"]`, `press`, or existing finding text rather than adding new top-level keys to `payload["insight"]` or changing element counts on `reading.elements`.
- **Snapshot persistence & schema (version 1).** One atomic JSON document in the desk data directory stores per-tile last-viewed signatures keyed by tile `id`:
  ```json
  {
    "version": 1,
    "viewedAt": 0.0,
    "cards": {
      "<cardId>": {
        "seenAt": 0.0,
        "pluginId": "<pluginId>",
        "signature": {}
      }
    }
  }
  ```
  Each `signature` captures a bounded, deterministic perceptual summary (freshness/cause, tracker value/unit/delta/headers/rowsSeen/top finding, digest thread list up to 10 subjects/senders/ages, calendar next meeting title/time/meta/prep count, research answer timestamp/summary prefix/sources count, and generic metric/status/list counts).
- **Watermark read/write split at existing seams.** The dashboard state assembly (`build_dashboard_state` -> `with_insight` -> `attach_cards`) only reads the snapshot store; `attach_cards` accepts an optional `snapshots` mapping (defaulting to `None` so direct unit callers are unaffected) and prepends `{"kind": "delta", "text": "Since you last looked: ..."}` to `payload["insight"]["blocks"]` when a prior snapshot exists and changed. When `snapshots` is provided and a tile's perceptual delta is non-empty, `attach_cards` initializes a minimal `payload`/`insight` dict even for non-family or `payload=None` attention tiles, while leaving `snapshots=None` or empty-delta tiles untouched. Only the existing explicit view endpoint (`POST /api/dashboard/view`) records updated snapshots to disk.
- **Sitting stability across 8-second SPA polls.** Because the SPA reports `POST /api/dashboard/view` once on initial mount, subsequent background polls during the same sitting receive no server-side delta unless new changes arrive. The SPA root caches each tile's initial sitting `"delta"` block keyed by its non-delta content signature so the line does not vanish 8 seconds after page load, clearing or replacing it whenever the tile's underlying content changes.
- **Provenance (`why`) schema on `"receipts"` blocks.** `InsightReading` gains `why: tuple[dict, ...] = ()` and `falsify: str = ""` at the end of its fields. Recall rows preserve integer fact `id` alongside `text` and `source` only when the fact object exposes an integer `id`. Each `why` item contains only non-empty bounded fields: `claim` (string), `columns` (list of strings), `cells` (list of up to 6 short strings), `rule` (string naming rule and threshold), and `facts` (list of `{"id": int, "source": str}` or entity summary `{"entityId": int, "name": str, "factCount": int}`). When `reading.why` is non-empty, `blocks(reading)` attaches `"why": [...]` directly onto the `"receipts"` block; when empty, `"why"` is omitted so existing block equality assertions stay identical.
- **Per-surface `"why"` and `"delta"` rendering.**
  - On both surfaces, any block with `kind == "delta"` renders at the top of the tile body (above primary elements/figure, including on attention tiles), while `"receipts"`, `"falsify"`, and `"note"` render in order below elements.
  - On server HTML, `"why"` renders inside a native `<details class="w-why"><summary>Why</summary>...</details>` using `<ul><li>` markup (never `<p class="w-note">`), preserving the exact quiet-paragraph contract while remaining zero-script and HTML-escaped at the boundary.
  - On the SPA, a single shared blocks renderer is exported and reused across both generic plugin tiles and classic workbook tracker tiles so markup never drifts.
- **Research falsification and counter-evidence press.**
  - `research.derive` generates one deterministic `falsify` string (`"What would change my mind: ..."`, <= 200 chars) from the stored answer's comparative, causal, quantitative, or keyword claims, emitted as a `{"kind": "falsify", "text": ...}` block (rather than a `text` element, preserving existing element-kind contracts when stale or quiet) plus a matching `why` provenance entry.
  - `research.derive` attaches a press offer with `kind: "check-counter"`, `label: "Check counter-evidence"`, `route: "/api/insight/draft"`, and bounded `text` carrying the answer summary and falsifier (`<= 400` chars).
  - The press handler adds `"check-counter"` to the fixed press vocabulary with a dedicated prompt, explicit disclosure lines (`"Sends: the stored answer summary and the desk's falsification criterion."` / `"Does not send: your workbook, your mail, your calendar, or any memory."`), and a `409` `insight:model-off` refusal when Your AI is off.
- **Outlier segment cause and action.** `relations.outliers` evaluates categorical text columns (reusing the existing categorical cardinality guard) and date columns (grouping by exact date or `YYYY-MM` month bucket passing the categorical cardinality guard with at least 2 rows per segment, so a unique-date-per-row column never treats a single row's date as a segment) to find the segment whose mean shifted most from the remaining rows (`|segment_mean - rest_mean|`), records the segment, bounded cell evidence, rule/threshold, and concrete action on `Finding`, and appends the cause and action clauses to the outlier finding text (capped cleanly so quiet/normal/chatty density element counts remain unchanged and `Finding.suggested` remains `(outlier_index,)`).
- **Project vocabulary, Python 3.10 floor, and docstrings.** All new user-facing copy follows the domain glossary (`tile`, `fact`, `Your AI`, `Source`, never `widget` or `Hermes` in new UI copy), all Python code parses under the Python 3.10 grammar without new third-party dependencies, and every new function, method, and class carries a concise docstring.

## Testing Decisions

Test external behaviour only, at the highest existing seam:

- **Snapshot store and perceptual deltas:** Unit-test signature extraction and perceptual diffs across workbook, digest, calendar, research, and generic tiles (including no-delta on identical state, no-delta on first-ever snapshot, and priority ordering). Test over HTTP via the server harness that repeated `GET /api/dashboard` calls do not mutate stored snapshots, `POST /api/dashboard/view` advances them, and subsequent `GET /api/dashboard` calls clear old deltas and emit new ones when underlying data changes.
- **Provenance ("why") contract and memory IDs:** Test through the reading presentation and `attach_cards` seam that recalled facts with integer IDs emit `why` citing fact IDs and sources without exposing raw fact text, mock facts without `id` keep existing recall compatibility, workbook/digest/calendar/research families populate accurate rules/columns/cells, and empty `why` omits the `"why"` key cleanly.
- **Anomaly -> cause -> action:** Test `relations.outliers` and `workbook.derive` on tables with categorical segments, date segments, and flat-label-only tables, verifying the most-moved segment, concrete action, preserved `suggested == (index,)`, and unchanged existing threshold refusals.
- **Research falsification and counter-evidence press:** Test `research.derive` for deterministic `"What would change my mind"` block generation across comparative, quantitative, and plain claims; test `press.draft_reply` (and HTTP `/api/insight/draft` + `/insight/press`) for `"check-counter"` disclosure, injected model prompt/answer, oversized-text 400 refusal, and 409 `insight:model-off` refusal.
- **Server HTML and SPA surfaces:** Test server HTML rendering for top-of-tile `"delta"` placement, `"falsify"` block rendering, `<details class="w-why">` rendering and HTML escaping, and preservation of quiet-paragraph ordering. Test SPA components via Vitest (`PluginCardView`, `TrackerCard`, and `DashboardApp` polling) for top-of-tile delta, sitting stability across poll ticks, `<details class="w-why">` drilldown, and `"check-counter"` press phase/label, plus `tsc --noEmit` and SPA rebuild.
- **Prior art to follow:** `tests/test_insight_seam.py`, `tests/test_insight_blocks.py`, `tests/test_insight_receipts.py`, `tests/test_insight_relations.py`, `tests/test_insight_workbook.py`, `tests/test_insight_research.py`, `tests/test_insight_press.py`, `tests/test_server_insight_html.py`, `tests/test_dashboard_state.py`, and `frontend/src/test/press.test.tsx`, `frontend/src/test/tracker-cards.test.tsx`, `frontend/src/test/dashboard-poll.test.tsx`.

## Out of Scope

- Cross-tile synthesis (Monday memo, desk-wide question answering), personal entity graph editing, commitments ledger, preference autopilot, and voice-matched drafting.
- Any automatic memory writes or background LLM calls on dashboard load or poll.
- Client-side JavaScript on the server-rendered fallback dashboard page.
- Changes to plugin manifests or addition of new Python/npm runtime dependencies.

## Further Notes

- The 6 tickets keep each parallel pair (`01` with `02`, `03` with `04`, `05` with `06`) file-disjoint so those pairs run concurrently; the two shared files (`reading.py` between `01` and `04`, `app.py` between `02` and `05`) sit on blocked-by edges and stack cleanly in ticket order.
- All frontend verification requires dependencies installed (`npm ci` when `node_modules` is absent) and `NODE_ENV=test` when running Vitest in environments that export `NODE_ENV=production`.
