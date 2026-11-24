# I5: Docs, walkthrough and evidence

Part of specs/024-outlook-metadata-feeder.md (G3, G7, G8). Blocked by: I2, I3, I4.

## Context

The feature is only trustworthy if the docs say what it does, what it cannot do, and which platform source was actually available. The repo keeps date-stamped evidence under `docs/evidence/` and product limitations in `docs/known-limitations.md`.

## Scope

- Write `docs/research/2026-11-24-outlook-metadata-feeder.md`: the ranked mechanisms, the collector matrix, the rejected paths (Graph, IMAP, EWS, Power Automate, add-ins), the local probe facts, and the macOS manual check.
- Update `docs/known-limitations.md`: the feeder only sees what the OS index contains; it does not mirror a mailbox; bodies are never read; macOS depends on Spotlight; no OS task or service is created.
- Update `README.md` and the Settings copy where they describe the mail source.
- Update the wayfinder map's Decisions so far and close O1 to O4 with answers.
- Evidence: focused test output, a live Windows Search run with counts and field names only, a generated `.eml` listing with no body, and a settings screenshot or HTML snapshot with the feeder on, off and unavailable. The macOS check is a written manual procedure, not a claimed result.
- Record the exact commands a reviewer can rerun.

## Acceptance

The docs match the code; the evidence folder contains the commands and outputs; the wayfinder map has no open decision tickets; no document claims macOS was verified on a Mac that was not used.
