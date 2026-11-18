# 01: Every reading says what it used

**What to build:** the reading type carries receipts — the preference keys whose value changed the output, and the inputs it consulted — and both surfaces print them as one quiet line under the reading.

**Build in:** `src/agentdesk/insight/types.py`, `service.py`, the four family modules, `src/agentdesk/server/app.py` (`_plugin_element_html`), `frontend/src/types.ts`.

**Blocked by:** none.

**Status:** ready-for-agent
**GitHub:** issue #137

- [ ] `InsightReading` gains `used: tuple[str, ...]` and `inputs: tuple[str, ...]`; `service.attach_cards` writes `payload["insight"]["receipts"] = {"preferences": [...], "inputs": [...]}` and leaves the existing fields untouched.
- [ ] Vocabulary is fixed and validated: inputs are drawn from `rows`, `memory`, `calendar`; preference receipts are keys of the preferences document. An unknown name is dropped rather than printed.
- [ ] The workbook family declares `chart` only when the stored value is not `auto`, the digest family declares `replyTone`/`replyLength` only when they changed the skeleton, the calendar family declares `prepMinutes` only when a window is set, and the research family declares none of them.
- [ ] A reading that consulted memory says `memory`; one that ran with a sealed bank does not, and the existing note still names why.
- [ ] The server-rendered card prints one line: "Used: your chart preference · memory (2 notes) · this card's rows", and "Used the defaults; read only this card's rows." when nothing else applies.
- [ ] No receipt ever prints a preference value (a topic list never appears).
- [ ] tests/test_insight_receipts.py covers the vocabulary filter, each family's declarations, the defaults line, and the sealed-bank case; tests/test_server_insight_html.py gains the printed line and its escaping.
