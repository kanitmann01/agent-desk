# I3: The macOS Spotlight collector

Part of specs/024-outlook-metadata-feeder.md (G3, G4, G5). Blocked by: I1.

## Context

macOS Spotlight indexes mail items and exposes metadata through `mdfind` and `mdls`. The collector must work with Outlook for Mac where Spotlight indexes it, without reading bodies and without a dependency. The exact attribute names must follow the macOS research note at `D:/20-projects/Personal Agents/.scratch/notes/macos-outlook-research.md` when it exists. If an attribute is missing, leave the header out rather than inventing it.

## Scope

- Add `src/agentdesk/mail/collectors/spotlight.py`.
- Query with `mdfind` for mail items, then read metadata with `mdls` (or `mdls -raw` / `plutil` if the research proves a cleaner form). Use a bounded subprocess timeout and no shell.
- Map the returned attributes to `MessageHeader`: subject, authors or sender, recipients, received or sent date, message id when present.
- `available()` is false off macOS, when `mdfind` or `mdls` is missing, or when the query returns no items. The unavailable cause names Spotlight privacy and Outlook indexing.
- Tests use fake `mdfind` and `mdls` output for at least three messages, one missing date, one missing message id, one missing sender, one non-mail path. Assert mapping, timeouts, nonzero exit, malformed output, and that no body attribute is requested.
- A manual check on a real Mac is recorded as evidence; CI uses fakes only.

## Acceptance

The collector maps fake Spotlight output to headers that pass the I1 writer; the query and attribute list contain no body field; an unavailable Spotlight returns an honest state with the privacy cause.
