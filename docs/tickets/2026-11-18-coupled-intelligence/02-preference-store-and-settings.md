# 02: Preferences the user owns, and the settings form that edits them

**What to build:** a typed preferences document the user edits in Settings — chart shape, reply tone, reply length, focus topics, prep window, card verbosity — validated on write, merged with defaults on read, and honoured by every reading.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Preferences live in one versioned JSON document in the data dir; read returns defaults merged with stored values, write validates the whole document and persists atomically.
- [ ] Unknown keys, wrong types and values outside the vocabulary are refused with a named code and leave the stored document unchanged.
- [ ] GET /api/preferences returns the document; PUT accepts a partial patch and returns the merged document.
- [ ] The Settings page renders and submits the six controls, shows a named error for a refused value, and keeps the existing settings page untouched in behaviour.
- [ ] prompt_lines() gives the readings at most six bounded lines describing the user's stated preferences, and nothing when the user left defaults.
- [ ] tests/test_insight_preferences.py covers defaults, round-trip, each refusal, and the HTTP path.
