# I2: The Windows Search collector

Part of specs/024-outlook-metadata-feeder.md (G2, G4, G5). Blocked by: I1.

## Context

Windows Search exposes mail metadata through `Provider=Search.CollatorDSO;Extended Properties='Application=Windows';` and the `SYSTEMINDEX` view. The probe on this machine confirmed `System.Subject`, `System.Message.FromAddress`, `System.Message.FromName`, `System.Message.ToAddress`, `System.Message.ToName`, `System.Message.DateReceived`, `System.Message.DateSent`, `System.Message.HasAttachments`, `System.ItemType` and `System.Message.MessageClass` are queryable. `System.Kind = 'email'` returns items. The collector must not read bodies.

## Scope

- Add `src/agentdesk/mail/collectors/windows_search.py` and a PowerShell helper under `src/agentdesk/mail/collectors/`.
- The helper runs a parameterized `SYSTEMINDEX` query, selects metadata columns only, filters to email items, and prints one JSON array. It must not select `System.Search.Contents` or any body field. Scope to the Outlook store where the index exposes `System.ItemUrl` or `System.Message.Store`; otherwise return all email items and say so in the result.
- The Python collector runs the helper with a timeout, no window, no shell, parses the JSON, maps to `MessageHeader`, and returns `available()` false off Windows or when the helper or index is missing.
- Tests use a fake subprocess output with at least three messages, one missing date, one missing message id, and one missing sender. Assert mapping, timeouts, nonzero exit, malformed JSON, and the absence of body columns in the query.
- A live smoke run against this machine's index is allowed and should be recorded in `evidence/`; it must print counts and field names only, never mail text.

## Acceptance

The collector maps a fake index response to headers that pass the I1 writer; the PowerShell helper contains no body column; a missing index or a disabled service returns an honest unavailable state.
