# 01: The insight seam and the tracker table the reading needs

**What to build:** every plugin card on the dashboard carries, beside its existing elements, a short reading computed by the host from that card's own data. The pass never breaks a card: a failing derivation leaves the card untouched plus one honest status line. This ticket ships the seam, the frozen interfaces the other four tickets fill, and the tracker table those readings reason over.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] read_tracker() returns the bounded table it already parses (headers plus up to 60 rows by 10 columns) beside the existing aggregate keys, and the tracker card payload carries it through.
- [x] agentdesk.insight exposes InsightContext (preferences document, clock, density, a read-only recall callable, a memory note), InsightReading (elements, press, note) and attach_cards(cards, ctx).
- [x] attach_cards dispatches by plugin id to workbook, calendar, digest and research families, appends their elements to payload["elements"], and records payload["insight"] = {status, source, preferences, note, press}.
- [x] A derivation that raises degrades to status "unavailable" with a sentence (the family's own when it refused deliberately) and appends no element; the card's original elements and payload keys survive untouched.
- [x] An empty reading produces status "empty" and no elements, so silence is distinguishable from failure.
- [x] dashboard_payload() calls the pass once, over every card, and the pass performs no network and no memory write.
- [x] GET and POST /api/preferences and POST /api/insight/draft are routed and delegate to the insight package (this server mutates over POST only, never PUT); the draft route always answers with the disclosure it would send, and while no composer is connected it says so as status "empty" instead of inventing text.
- [x] tests/test_insight_seam.py covers dispatch, append, empty, degraded and no-network behaviour.
- [x] Built and tested: 22 tests in tests/test_insight_seam.py; tracker, dashboard and plugin suites unchanged (317 tests green).
