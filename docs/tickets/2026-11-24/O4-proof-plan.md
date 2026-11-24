# O4: What is the proof plan?

Type: task. Claim: unclaimed. Blocked by: O1, O2, O3.

## Question

What must the implementation prove, on this machine, without touching real mail, before the spec is called decision-ready?

Produce:

- a synthetic fixture set that exercises every header field, a malformed file, a missing profile and an empty source;
- the exact commands for the feeder self-check, the app tests and a local end-to-end run;
- the evidence to record (command output, file list, app status, screenshots if a UI changes);
- the test that fails if the feeder starts reading bodies, makes a network call, or shows a number in an attention state.

## Answer

The proof plan:

1. **Synthetic stores, no real mail.** Build a WPN store with the live schema and a macOS Notification Center store with `app` and `record`. Each has one Outlook mail alert with a sentinel preview/body token, one Outlook reminder, one non-Outlook alert, and one duplicate row.
2. **Writer round-trip.** Every generated `.eml` parses through `parse_eml`, carries the expected sender, subject and date, has a unique Message-ID, CRLF, no BOM, an empty body, and no bytes after the blank line.
3. **No leak.** The sentinel preview/body token appears in no generated file, no status file and no audit row. A test fails if the readers import a network or model client.
4. **Idempotence.** A second pass over the same store writes nothing new and the file count is unchanged.
5. **Honest states.** A store with no Outlook handler, a missing store, a schema error and a macOS permission denial each return a named cause and no number.
6. **Live smoke, metadata only.** On this Windows machine, run the WPN reader against the real store and record counts and handler ids only, never payload text. On macOS, record a written manual procedure: grant Full Disk Access, send a self-addressed test message with a unique subject token and a body canary, press Fetch now twice, assert the subject token appears on `/mail`, the body canary appears nowhere, and the second pass adds no duplicate. Mark the macOS result as unverified until a real Mac run is recorded.
7. **Commands.** The focused feeder tests, the mail/settings/route/IT-surface tests, and the local app start command. Evidence goes under `docs/evidence/` with the exact commands and outputs.

This plan proves the parser, the readers and the honesty states. It does not claim that a real Outlook mailbox was read on this machine.
