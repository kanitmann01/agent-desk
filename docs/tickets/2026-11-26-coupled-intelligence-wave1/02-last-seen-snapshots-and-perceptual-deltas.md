# 02: Last-seen snapshots and perceptual deltas

**What to build:** Persist a per-tile last-seen snapshot watermark in the desk data directory that advances only when the user explicitly views the dashboard (`POST /api/dashboard/view`), never on GET reads or background polls, and prepend a concise 1-line perceptual delta block (`"Since you last looked: ..."`) whenever a tile has changed since the user's last view.

**Build in:** `src/agentdesk/insight/snapshots.py` (new), `src/agentdesk/insight/service.py`, `src/agentdesk/server/app.py` (`with_insight` and `_dashboard_view_report` only), and `tests/test_insight_snapshots.py`. Do not edit `types.py`, `reading.py`, `research.py`, `workbook.py`, `relations.py`, `_plugin_widget`, `pages.py`, or `frontend/`.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `SnapshotStore` persists `<data_dir>/insight_snapshots.json` (version 1) atomically (`tmp` + `os.replace`) and treats missing, corrupt, or non-object files as empty without crashing.
- [ ] `card_signature(card)` extracts a compact, deterministic perceptual signature covering freshness/cause, workbook tracker value/unit/delta/headers/rowsSeen/top finding, digest thread subjects/senders/ages (up to 10), calendar next meeting title/time/meta/prep count, research answer timestamp/summary prefix/sources count, and generic metric/status/list counts.
- [ ] `perceptual_delta(previous, current)` returns `""` when `previous is None` or nothing meaningful changed, and otherwise returns one concise sentence prefixed with `"Since you last looked: "` prioritizing freshness transitions, appeared/removed workbook columns or moved values, new/quiet/aged threads, shifted meeting times/titles, or newer research answers.
- [ ] `service.attach_cards(cards, context, *, snapshots=None)` leaves all direct callers (`snapshots=None`) 100% unchanged (including `payload=None` cards); when `snapshots` is provided and `perceptual_delta` is non-empty, it prepends `{"kind": "delta", "text": line}` to `payload["insight"]["blocks"]`, initializing a minimal `payload`/`insight` dict even for non-family or `payload=None` attention tiles when a non-empty delta exists.
- [ ] `app.with_insight` reads `SnapshotStore(default_data_dir()).read()` purely, and `app._dashboard_view_report` (`POST /api/dashboard/view`) records the current tile snapshots after recording pilot views.
- [ ] `tests/test_insight_snapshots.py` covers signature diffs per family, corrupt/empty store recovery, and HTTP round-trips proving repeated `GET /api/dashboard` polls preserve the delta until `POST /api/dashboard/view` advances the watermark. All Python code parses under 3.10 and carries docstrings.
