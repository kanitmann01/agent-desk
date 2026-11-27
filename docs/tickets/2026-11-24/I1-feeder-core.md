# I1: The feeder core and the header-only .eml writer

Part of specs/028-outlook-metadata-feeder.md (G1, G4, G5). Blocked by: none.

## Context

The app already reads header-only `.eml` files (`src/agentdesk/mail/core.py`) and has a frozen `Message` type with no body field. The feeder needs one platform-agnostic core that turns collector records into those files and reports honestly. No Windows or macOS import may be required to import the core.

## Scope

Create `src/agentdesk/feeder/`:

- `contract.py`:
  - `MailCollector` protocol: `name`, `available() -> tuple[bool, str]`, `collect(since, limit) -> list[Message]`. The return type is the existing `agentdesk.mail.core.Message`, so the no-body invariant is inherited.
  - `UnavailableCollector`: always unavailable; its cause names the manual Save as path.
- `writer.py`:
  - `render_eml(message: Message) -> bytes`: exactly `From`, `To`, `Cc`, `Subject`, `Date` (`email.utils.formatdate(..., usegmt=True)`), `Message-ID`, `In-Reply-To`, `Importance`, CRLF, UTF-8 without BOM, CR/LF stripped from values, header block ending at a blank line and no body.
  - `write_mail(messages, folder, *, now, window_days)`: deterministic filename from the message id (or a stable hash), temp file in the same folder, `os.replace`, and prune feeder-owned `.eml` files older than the window. A rerun overwrites, not duplicates.
  - `write_status(status, path)`: atomic JSON status.
- `runner.py`:
  - `OutlookFeeder` with injected collectors, folder provider, clock and status path. `run_once()` selects the first available collector, collects, writes, records `collector`, `platform`, `lastRunTs`, `lastResult`, `lastError`, `written`, then returns the status dict. A lock (reuse `agentloop.schedule.claim_run`) prevents overlapping runs. No network, no model, no body.
- `platform.py`:
  - `default_collectors(platform: str | None = None)` returns the manual collector for now; I2 and I3 add the Windows and macOS collectors. The only platform branch lives here.
- Tests in `tests/test_feeder_contract.py`, `tests/test_feeder_writer.py`, `tests/test_feeder_runner.py`, `tests/test_feeder_platform.py`:
  - A fake collector returns `Message` records; the writer round-trips through `parse_eml` and every field matches.
  - No body: no bytes after the blank line, and a body token never appears in any file.
  - CRLF, no BOM, unique Message-ID, deterministic filename, idempotent rerun, atomic replace under a fault.
  - A collector failure leaves the folder untouched and returns an honest status; the manual fallback names Save as.
  - The core imports no platform module and no HTTP/model client.

## Acceptance

`python -m pytest tests/test_feeder_contract.py tests/test_feeder_writer.py tests/test_feeder_runner.py tests/test_feeder_platform.py -q` passes; a generated file parses with `parse_eml` and carries no body; the core imports on any platform.

## Resolution (2026-11-24)

Resolved. `src/agentdesk/feeder/` now holds `contract.py`, `writer.py`, `runner.py` and `platform.py`, with the four focused test files. The writer round-trips through `parse_eml`, strips CR/LF from values, writes CRLF UTF-8 without BOM, synthesizes a stable Message-ID, writes atomically, prunes only feeder-owned files, and leaves no bytes after the blank line. The runner selects the first available collector, records an honest status, and holds a cross-process run claim. No feeder core module imports a platform, a subprocess or a network or model client. The focused feeder suite is 66 passed, 1 skipped.
