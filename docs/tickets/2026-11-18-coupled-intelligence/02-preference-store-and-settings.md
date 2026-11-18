# 02: Preferences the user owns, and the settings form that edits them

**What to build:** a typed preferences document the user edits in Settings — chart shape, reply tone, reply length, focus topics, prep window, card verbosity — validated on write, merged with defaults on read, and honoured by every reading.

**Blocked by:** 01.

**Status:** done

- [x] Preferences live in one versioned JSON document in the data dir; read returns defaults merged with stored values, write validates the whole document and persists atomically.
- [x] Unknown keys, wrong types and values outside the vocabulary are refused with a named code and leave the stored document unchanged.
- [x] GET /api/preferences returns the document; POST /api/preferences accepts a partial patch and returns the merged document. This server has no PUT at all, so the mutating verbs are POST and the no-JS form post to `/settings/preferences`.
- [x] The Settings page renders and submits the six controls, shows a named error for a refused value, and keeps the existing settings page untouched in behaviour.
- [x] prompt_lines() gives the readings at most six bounded lines describing the user's stated preferences, and nothing when the user left defaults.
- [x] tests/test_insight_seam.py (store + JSON route), tests/test_insight_settings.py (the card) and tests/test_server_preferences_form.py (the form post) cover defaults, round-trip, each refusal, and both HTTP paths.
